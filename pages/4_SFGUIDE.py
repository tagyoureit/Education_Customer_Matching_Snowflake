import streamlit as st
import json
from snowflake.snowpark.session import Session
import snowflake.connector
import requests
import os
import toml

@st.cache_resource
def create_connections():
    try:
        creds = st.secrets["snowflake"]
        snowpark_session = Session.builder.configs(creds).create()
        connector_conn = snowflake.connector.connect(**creds)
        try:
            cur = connector_conn.cursor()
            cur.execute("USE WAREHOUSE COMPUTE_WH")
            cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
            cur.execute("USE SCHEMA PUBLIC")
            cur.close()
        except Exception as e:
            st.error(f"Failed to set context on connector: {e}")
        return snowpark_session, connector_conn
    except Exception as e:
        st.error(f"Failed to create Snowflake connections: {e}")
        return None, None

session, conn = create_connections()

API_ENDPOINT = "/api/v2/cortex/agent:run"
API_TIMEOUT = 50000  # in milliseconds

#CORTEX_SEARCH_SERVICES = "sales_intelligence.data.sales_conversation_search"
SEMANTIC_MODELS = "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"
TOOL_NAME_ANALYST = "analyst1"
TOOL_NAME_SQL_EXEC = "sql_execution_tool"

def run_snowflake_query(query):
    try:
        df = session.sql(query.replace(';',''))
        
        return df

    except Exception as e:
        st.error(f"Error executing SQL: {str(e)}")
        return None, None

def build_agent_payload(messages):
    return {
        "model": "llama3.3-70b",
        "messages": messages,
        "tools": [
            {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": TOOL_NAME_ANALYST}},
            {"tool_spec": {"type": "sql_exec", "name": TOOL_NAME_SQL_EXEC}},
            {"tool_spec": {"type": "data_to_chart", "name": "data_to_chart"}},
        ],
        "tool_resources": {
            TOOL_NAME_ANALYST: {"semantic_model_file": SEMANTIC_MODELS}
        }
    }

def resolve_host():
    # Prefer st.secrets if provided
    creds = st.secrets.get("snowflake", {})
    host = creds.get("host")
    if host:
        return host.replace("_", "-").lower()

    # Next prefer account from secrets
    account = creds.get("account")
    if account:
        normalized = str(account).replace("_", "-").lower()
        return f"{normalized}.snowflakecomputing.com"

    # Try Snowflake CLI config (~/.snowflake/connections.toml)
    try:
        connections_path = os.path.expanduser("~/.snowflake/connections.toml")
        if os.path.exists(connections_path):
            config = toml.load(connections_path)
            default_section = config.get("default", {})
            cli_host = default_section.get("host")
            if cli_host:
                return str(cli_host).replace("_", "-").lower()
            cli_account = default_section.get("account")
            if cli_account:
                normalized = str(cli_account).replace("_", "-").lower()
                return f"{normalized}.snowflakecomputing.com"
    except Exception:
        pass

    return None

def snowflake_api_call(messages):
    payload = build_agent_payload(messages)
    try:
        host = resolve_host()
        if not host:
            st.error("Missing 'host' in st.secrets['snowflake']. Please provide your account host, e.g., xy12345.us-east-1.aws.snowflakecomputing.com")
            return None

        headers = {
            "Authorization": f"Snowflake Token=\"{conn.rest.token}\"",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            url=f"https://{host}{API_ENDPOINT}",
            json=payload,
            headers=headers,
            timeout=API_TIMEOUT / 1000.0,
        )

        request_id = resp.headers.get("X-Snowflake-Request-Id")
        if resp.status_code >= 400:
            st.error(f"❌ HTTP Error: {resp.status_code}")
            st.write(f"Request ID: {request_id}")
            st.write(resp.text[:500])
            return None

        return resp.content
    except Exception as e:
        st.error(f"Error making request: {str(e)}")
        return None

def process_sse_response(response_content):
    """Process SSE response. Capture text, sql, citations, and sql_exec instruction."""
    text = ""
    sql = ""
    citations = []
    sql_exec = {"tool_use_id": None, "name": None, "sql": None}

    if not response_content:
        return text, sql, citations, sql_exec

    try:
        events = response_content.decode('utf-8').strip().split('\n\n')
        for event_str in events:
            if not event_str.strip():
                continue
            lines = event_str.strip().split('\n')
            event_type, data_json = "", ""
            for line in lines:
                if line.startswith('event:'):
                    event_type = line.split(':', 1)[1].strip()
                elif line.startswith('data:'):
                    data_json = line.split(':', 1)[1].strip()

            if event_type == "message.delta" and data_json:
                data = json.loads(data_json)
                for content_item in data.get('delta', {}).get('content', []):
                    content_type = content_item.get('type')
                    if content_type == "tool_results":
                        for result in content_item.get('tool_results', {}).get('content', []):
                            if result.get('type') == 'json':
                                json_content = result.get('json', {})
                                text += json_content.get('text', '')
                                sql = json_content.get('sql', sql)
                                for sr in json_content.get('searchResults', []):
                                    citations.append({'source_id': sr.get('source_id',''), 'doc_id': sr.get('doc_id','')})
                    elif content_type == 'text':
                        text += content_item.get('text', '')
                    elif content_type == 'tool_use':
                        tool_use = content_item.get('tool_use', {})
                        name = tool_use.get('name')
                        if name == TOOL_NAME_SQL_EXEC:
                            sql_exec['tool_use_id'] = tool_use.get('tool_use_id')
                            sql_exec['name'] = name
                            # Some variants include input.sql in tool_use; capture if present
                            input_obj = tool_use.get('input', {}) or {}
                            if isinstance(input_obj, dict):
                                sql_candidate = input_obj.get('sql')
                                if sql_candidate:
                                    sql_exec['sql'] = sql_candidate

    except Exception as e:
        st.error(f"Error processing SSE events: {str(e)}")

    return text, sql, citations, sql_exec

def main():
    st.title("Intelligent Sales Assistant")

    # Sidebar for new chat
    with st.sidebar:
        if st.button("New Conversation", key="new_chat"):
            st.session_state.messages = []
            st.rerun()

    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'].replace("•", "\n\n"))

    if query := st.chat_input("Would you like to learn?"):
        # Add user message to chat
        with st.chat_message("user"):
            st.markdown(query)
        st.session_state.messages.append({"role": "user", "content": query})
        
        # 1) Send initial request to Agent with user's question
        with st.spinner("Processing your request..."):
            initial_messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": query}]
                }
            ]
            response_content = snowflake_api_call(initial_messages)
            text, sql, citations, sql_exec_info = process_sse_response(response_content)
            
            # Add assistant response to chat
            if text:
                text = text.replace("【†", "[")
                text = text.replace("†】", "]")
                st.session_state.messages.append({"role": "assistant", "content": text})
                
                with st.chat_message("assistant"):
                    st.markdown(text.replace("•", "\n\n"))
                    if citations:
                        st.write("Citations:")
                        for citation in citations:
                            doc_id = citation.get("doc_id", "")
                            if doc_id:
                                query = f"SELECT transcript_text FROM MDM_CUSTOMER_MATCHING.PUBLIC.sales_conversations WHERE conversation_id = '{doc_id}'"
                                result = run_snowflake_query(query)
                                result_df = result.to_pandas()
                                if not result_df.empty:
                                    transcript_text = result_df.iloc[0, 0]
                                else:
                                    transcript_text = "No transcript available"
                    
                                with st.expander(f"[{citation.get('source_id', '')}]"):
                                    st.write(transcript_text)

            # 2) If agent asked us to execute SQL, run it client-side and send follow-up with query_id
            executed_df = None
            executed_query_id = None
            sql_to_run = sql_exec_info.get('sql') or sql
            sql_tool_use_id = sql_exec_info.get('tool_use_id')
            if sql_to_run and sql_tool_use_id:
                try:
                    cur = conn.cursor()
                    cur.execute(sql_to_run)
                    executed_query_id = cur.sfqid
                    try:
                        executed_df = cur.fetch_pandas_all()
                    except Exception:
                        executed_df = None
                    cur.close()
                except Exception as e:
                    st.error(f"Error executing agent SQL: {e}")

                if executed_query_id:
                    followup_messages = [
                        {"role": "user", "content": [{"type": "text", "text": query}]},
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "tool_use": {
                                        "tool_use_id": sql_tool_use_id,
                                        "name": TOOL_NAME_SQL_EXEC,
                                        "input": {"sql": sql_to_run}
                                    }
                                }
                            ]
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_results",
                                    "tool_results": {
                                        "tool_use_id": sql_tool_use_id,
                                        "name": TOOL_NAME_SQL_EXEC,
                                        "content": [{"type": "json", "json": {"query_id": executed_query_id}}]
                                    }
                                }
                            ]
                        }
                    ]
                    followup_resp = snowflake_api_call(followup_messages)
                    f_text, _, _, _ = process_sse_response(followup_resp)
                    if f_text:
                        st.session_state.messages.append({"role": "assistant", "content": f_text})
                        with st.chat_message("assistant"):
                            st.markdown(f_text.replace("•", "\n\n"))

            # Show SQL and optional results for transparency
            if sql_to_run:
                st.markdown("### Generated SQL")
                st.code(sql_to_run, language="sql")
                if executed_df is not None:
                    st.write("### Query Results")
                    st.dataframe(executed_df)

if __name__ == "__main__":
    main()