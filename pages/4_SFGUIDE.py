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
            cur.execute("USE WAREHOUSE WAREHOUSE_L_G2")
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
API_TIMEOUT = 300000  # in milliseconds (SSE can take longer)

#CORTEX_SEARCH_SERVICES = "sales_intelligence.data.sales_conversation_search"
SEMANTIC_MODELS = "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"
# Normalize tool names to lowercase to match agent responses
TOOL_NAME_ANALYST = "customer_matching_analyst"
TOOL_NAME_SQL_EXEC = "sql_execution_tool"
TOOL_NAME_UPDATE_TEST = "update_test_record"
TOOL_NAME_GET_AI = "get_ai_analysis"
DEFAULT_WAREHOUSE = "WAREHOUSE_L_G2"

# High-level instructions aligned to the Agent configuration
AGENT_RESPONSE_INSTRUCTION = (
    "You are a top notch analyst that validates incoming TEST_MATCHES records against existing VALID_CUSTOMERS in MDM_CUSTOMER_MATCHING.PUBLIC. "
    "When a user asks for matching insights, first use the customer_matching_analyst tool to generate SQL, then execute it using the sql_execution_tool (sql_exec) and answer only with the results. "
    "Prefer concise answers over planning. If the user asks to update a test record, use the update_test_record tool."
)

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
        "response_instruction": AGENT_RESPONSE_INSTRUCTION,
        "messages": messages,
        "tools": [
            {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": TOOL_NAME_ANALYST}},
            {"tool_spec": {"type": "sql_exec", "name": TOOL_NAME_SQL_EXEC}},
            {"tool_spec": {"type": "data_to_chart", "name": "data_to_chart"}},
            {"tool_spec": {"type": "generic", "name": TOOL_NAME_UPDATE_TEST}},
        ],
        "tool_resources": {
            TOOL_NAME_ANALYST: {
                "semantic_model_file": SEMANTIC_MODELS
            },
            TOOL_NAME_SQL_EXEC: {
                "warehouse": DEFAULT_WAREHOUSE
            }
        },
        "tool_choice": {"type": "auto"}
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

def snowflake_api_call(messages, show_error=True):
    payload = build_agent_payload(messages)
    try:
        host = resolve_host()
        if not host:
            st.error("Missing 'host' in st.secrets['snowflake']. Please provide your account host, e.g., xy12345.us-east-1.aws.snowflakecomputing.com")
            return None

        headers = {
            "Authorization": f"Snowflake Token=\"{conn.rest.token}\"",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Connection": "keep-alive",
        }

        if st.session_state.get("debug_agent"):
            with st.expander("Debug: Agent request (payload)", expanded=False):
                st.write({"host": host, "endpoint": API_ENDPOINT})
                try:
                    st.code(json.dumps(payload, indent=2), language="json")
                except Exception:
                    st.code(str(payload))

        resp = requests.post(
            url=f"https://{host}{API_ENDPOINT}",
            json=payload,
            headers=headers,
            timeout=API_TIMEOUT / 1000.0,
            stream=True,
        )

        request_id = resp.headers.get("X-Snowflake-Request-Id")
        if resp.status_code >= 400:
            if show_error:
                st.error(f"❌ HTTP Error: {resp.status_code}")
                st.write(f"Request ID: {request_id}")
                if st.session_state.get("debug_agent"):
                    with st.expander("Debug: Agent HTTP error body", expanded=True):
                        try:
                            st.code(resp.text, language="json")
                        except Exception:
                            st.write(resp.text)
                    with st.expander("Debug: Agent response headers", expanded=False):
                        st.write(dict(resp.headers))
            return None

        # Aggregate SSE events into a single byte string so downstream parser can process it
        event_lines = []
        current_event = []
        for line in resp.iter_lines(decode_unicode=True):
            if line is None:
                continue
            if line == "":
                if current_event:
                    event_lines.append("\n".join(current_event))
                    # Break on explicit stop event if present in last event
                    if any(l.strip().startswith("event:") and l.strip().endswith("message.stop") for l in current_event):
                        break
                    current_event = []
                continue
            current_event.append(line)
        if current_event:
            event_lines.append("\n".join(current_event))

        if st.session_state.get("debug_agent"):
            with st.expander("Debug: Agent raw SSE", expanded=False):
                total = len(event_lines)
                # Show a compact view: first 3 and last 3 events, with counts
                head = event_lines[:3]
                tail = event_lines[-3:] if total > 3 else []
                compact = []
                if head:
                    compact.append("\n\n".join(head))
                if total > 6:
                    compact.append(f"\n\n… {total - 6} events omitted …\n\n")
                if tail:
                    compact.append("\n\n".join(tail))
                st.code("".join(compact))

        return ("\n\n".join(event_lines)).encode("utf-8")
    except Exception as e:
        st.error(f"Error making request: {str(e)}")
        return None

def process_sse_response(response_content):
    """Process SSE response. Capture text, sql, citations, and sql_exec instruction."""
    text = ""
    sql = ""
    citations = []
    sql_exec = {"tool_use_id": None, "name": None, "sql": None}
    generic_tool = {"tool_use_id": None, "name": None, "input": None}
    analyst_tool = {"tool_use_id": None, "name": None, "input": None}
    events_seen = []

    if not response_content:
        return text, sql, citations, sql_exec, generic_tool, analyst_tool, events_seen

    try:
        events = response_content.decode('utf-8').strip().split('\n\n')
        for event_str in events:
            if not event_str.strip():
                continue
            lines = event_str.strip().split('\n')
            event_type = ""
            data_lines = []
            for line in lines:
                if line.startswith('event:'):
                    event_type = line.split(':', 1)[1].strip()
                elif line.startswith('data:'):
                    # SSE can contain multiple data lines per event; concatenate per spec
                    data_lines.append(line.split(':', 1)[1])
            data_json = "".join([dl.strip() for dl in data_lines]) if data_lines else ""

            if event_type == "message.delta" and data_json:
                events_seen.append("message.delta")
                data = json.loads(data_json)
                for content_item in data.get('delta', {}).get('content', []):
                    content_type = content_item.get('type')
                    if content_type == "tool_results":
                        for result in content_item.get('tool_results', {}).get('content', []):
                            rtype = (result.get('type') or '').lower()
                            # Accept both json and application/json
                            if rtype in ('json', 'application/json'):
                                json_content = result.get('json', {})
                                if isinstance(json_content, dict):
                                    text += json_content.get('text', '') or ''
                                    sql = json_content.get('sql', sql)
                                    for sr in json_content.get('searchResults', []) or []:
                                        citations.append({'source_id': sr.get('source_id',''), 'doc_id': sr.get('doc_id','')})
                            elif rtype == 'text':
                                text += result.get('text', '') or ''
                    elif content_type == 'text':
                        text += content_item.get('text', '')
                    elif content_type == 'tool_use':
                        tool_use = content_item.get('tool_use', {})
                        # Normalize name for reliable comparisons
                        name = (tool_use.get('name') or '').strip().lower()
                        if name == TOOL_NAME_SQL_EXEC:
                            sql_exec['tool_use_id'] = tool_use.get('tool_use_id')
                            sql_exec['name'] = name
                            # Some variants include input.sql in tool_use; capture if present
                            input_obj = tool_use.get('input', {}) or {}
                            if isinstance(input_obj, dict):
                                sql_candidate = input_obj.get('sql')
                                if sql_candidate:
                                    sql_exec['sql'] = sql_candidate
                        elif name == TOOL_NAME_ANALYST:
                            analyst_tool['tool_use_id'] = tool_use.get('tool_use_id')
                            analyst_tool['name'] = name
                            analyst_tool['input'] = tool_use.get('input', {}) or {}
                        elif name in (TOOL_NAME_UPDATE_TEST, TOOL_NAME_GET_AI):
                            generic_tool['tool_use_id'] = tool_use.get('tool_use_id')
                            generic_tool['name'] = name
                            generic_tool['input'] = tool_use.get('input', {}) or {}

            elif event_type == "error" and data_json:
                events_seen.append("error")
                try:
                    data = json.loads(data_json)
                    err_msg = data.get('message') or data
                    st.error(f"Agent error: {err_msg}")
                except Exception:
                    st.error(f"Agent error event: {data_json}")
            elif event_type == "message.stop":
                # End of stream
                events_seen.append("message.stop")

    except Exception as e:
        st.error(f"Error processing SSE events: {str(e)}")

    if st.session_state.get("debug_agent"):
        with st.expander("Debug: Parsed events summary", expanded=False):
            st.write({
                "events_seen": events_seen,
                "has_sql_exec": bool(sql_exec.get('tool_use_id')),
                "has_generic_tool": bool(generic_tool.get('tool_use_id')),
                "sql_from_tool": sql,
            })

    return text, sql, citations, sql_exec, generic_tool, analyst_tool, events_seen


def execute_generic_tool(conn, name, input_obj):
    """Execute generic tool by calling the underlying procedure/function. Returns (ok, result_text)."""
    try:
        cur = conn.cursor()
        if name == TOOL_NAME_UPDATE_TEST:
            p_record_id = input_obj.get('p_record_id')
            p_updates_json = input_obj.get('p_updates_json')
            if p_record_id is None or p_updates_json is None:
                return False, "Missing required inputs for Update_Test_Record"
            try:
                cur.execute(
                    "CALL MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD(%s, %s)",
                    (p_record_id, p_updates_json),
                )
            except Exception:
                # Fallback to SELECT invocation style if it's a function
                cur.execute(
                    "SELECT MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD(%s, %s)",
                    (p_record_id, p_updates_json),
                )
            try:
                df = cur.fetch_pandas_all()
                return True, df.to_json(orient='records') if not df.empty else "OK"
            finally:
                cur.close()
        if name == TOOL_NAME_GET_AI:
            p_test_id = input_obj.get('p_test_id')
            p_valid_id = input_obj.get('p_valid_id')
            if p_test_id is None or p_valid_id is None:
                return False, "Missing required inputs for Get_AI_Analysis"
            try:
                cur.execute(
                    "CALL MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS(%s, %s)",
                    (p_test_id, p_valid_id),
                )
            except Exception:
                cur.execute(
                    "SELECT MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS(%s, %s)",
                    (p_test_id, p_valid_id),
                )
            try:
                df = cur.fetch_pandas_all()
                if not df.empty:
                    # Return first cell as the analysis text
                    return True, str(df.iloc[0, 0])
                return True, "OK"
            finally:
                cur.close()
        return False, f"Unsupported tool: {name}"
    except Exception as e:
        return False, f"Execution error: {str(e)}"

def main():
    st.title("Intelligent Sales Assistant")

    # Sidebar for new chat
    with st.sidebar:
        if st.button("New Conversation", key="new_chat"):
            st.session_state.messages = []
            st.rerun()
        st.checkbox("Debug agent calls", key="debug_agent", value=st.session_state.get("debug_agent", False))

    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    # We no longer persist API messages; we send minimal, valid turns each call
    if 'api_messages' in st.session_state:
        pass
    if 'results_history' not in st.session_state:
        st.session_state.results_history = []

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
            # Send a single-turn user message to comply with alternating role requirement
            initial_messages = [{"role": "user", "content": [{"type": "text", "text": query}]}]
            response_content = snowflake_api_call(initial_messages, show_error=True)
            text, sql, citations, sql_exec_info, generic_tool_info, analyst_tool_info, events_seen = process_sse_response(response_content)
            initial_text = text.replace("【†", "[").replace("†】", "]") if text else ""

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
                    # Follow-up per docs: assistant echoes the prior tool_use, user provides tool_results with query_id
                    analyst_content_items = []
                    if analyst_tool_info.get('tool_use_id'):
                        analyst_content_items.append({
                            "type": "tool_use",
                            "tool_use": {
                                "tool_use_id": analyst_tool_info.get('tool_use_id'),
                                "name": TOOL_NAME_ANALYST,
                                "input": analyst_tool_info.get('input') or {}
                            }
                        })
                        analyst_content_items.append({
                            "type": "tool_results",
                            "tool_results": {
                                "status": "success",
                                "tool_use_id": analyst_tool_info.get('tool_use_id'),
                                "content": [
                                    {"type": "json", "json": {"sql": sql_to_run, "text": f"Interpretation: {query}"}}
                                ]
                            }
                        })

                    assistant_content = analyst_content_items + [{
                        "type": "tool_use",
                        "tool_use": {
                            "tool_use_id": sql_tool_use_id,
                            "name": TOOL_NAME_SQL_EXEC,
                            "input": {"sql": sql_to_run}
                        }
                    }]

                    followup_messages = [
                        {"role": "user", "content": [{"type": "text", "text": query}]},
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": [{"type": "tool_results", "tool_results": {"tool_use_id": sql_tool_use_id, "name": TOOL_NAME_SQL_EXEC, "content": [{"type": "json", "json": {"query_id": executed_query_id}}]}}]}
                    ]
                    # Per docs, send a compact follow-up containing only the relevant turns
                    if st.session_state.get("debug_agent"):
                        with st.expander("Debug: sql_exec follow-up messages", expanded=False):
                            st.code(json.dumps(followup_messages, indent=2)[:4000], language="json")
                    followup_resp = snowflake_api_call(followup_messages, show_error=False)
                    f_text, _, _, _, _, _, _ = process_sse_response(followup_resp)
                    if f_text:
                        final_text = f_text
                    else:
                        final_text = initial_text
            elif sql and analyst_tool_info.get('tool_use_id'):
                # We have analyst SQL but no sql_exec tool_use; synthesize the assistant tool_use for sql_exec and proceed
                try:
                    cur = conn.cursor()
                    cur.execute(sql)
                    executed_query_id = cur.sfqid
                    try:
                        executed_df = cur.fetch_pandas_all()
                    except Exception:
                        executed_df = None
                    cur.close()
                except Exception as e:
                    st.error(f"Error executing analyst SQL: {e}")

                synthetic_tool_use_id = analyst_tool_info.get('tool_use_id') + "_exec"
                analyst_content_items = []
                if analyst_tool_info.get('tool_use_id'):
                    analyst_content_items.append({
                        "type": "tool_use",
                        "tool_use": {
                            "tool_use_id": analyst_tool_info.get('tool_use_id'),
                            "name": TOOL_NAME_ANALYST,
                            "input": analyst_tool_info.get('input') or {}
                        }
                    })
                    analyst_content_items.append({
                        "type": "tool_results",
                        "tool_results": {
                            "status": "success",
                            "tool_use_id": analyst_tool_info.get('tool_use_id'),
                            "content": [
                                {"type": "json", "json": {"sql": sql, "text": f"Interpretation: {query}"}}
                            ]
                        }
                    })

                assistant_content = analyst_content_items + [{
                    "type": "tool_use",
                    "tool_use": {
                        "tool_use_id": synthetic_tool_use_id,
                        "name": TOOL_NAME_SQL_EXEC,
                        "input": {"sql": sql}
                    }
                }]

                followup_messages = [
                    {"role": "user", "content": [{"type": "text", "text": query}]},
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user", "content": [{"type": "tool_results", "tool_results": {"tool_use_id": synthetic_tool_use_id, "name": TOOL_NAME_SQL_EXEC, "content": [{"type": "json", "json": {"query_id": executed_query_id}}]}}]}
                ]
                if st.session_state.get("debug_agent"):
                    with st.expander("Debug: synthesized sql_exec follow-up messages", expanded=False):
                        st.code(json.dumps(followup_messages, indent=2)[:4000], language="json")
                followup_resp = snowflake_api_call(followup_messages, show_error=False)
                f_text, _, _, _, _, _, _ = process_sse_response(followup_resp)
                if f_text:
                    final_text = f_text
                else:
                    final_text = initial_text

            # 3) If agent asked us to execute a generic tool, run it and send follow-up with tool_results
            gen_tool_use_id = generic_tool_info.get('tool_use_id') if generic_tool_info else None
            gen_tool_name = generic_tool_info.get('name') if generic_tool_info else None
            gen_tool_input = generic_tool_info.get('input') if generic_tool_info else None
            if gen_tool_use_id and gen_tool_name:
                ok, result_text = execute_generic_tool(conn, gen_tool_name, gen_tool_input or {})
                tool_results_payload = {"type": "json", "json": {"result": result_text, "ok": ok}}
                followup_messages = [
                    {"role": "user", "content": [{"type": "text", "text": query}]},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "tool_use": {
                                    "tool_use_id": gen_tool_use_id,
                                    "name": gen_tool_name,
                                    "input": gen_tool_input or {}
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
                                    "tool_use_id": gen_tool_use_id,
                                    "name": gen_tool_name,
                                    "content": [tool_results_payload]
                                }
                            }
                        ]
                    }
                ]
                # Per docs, send a compact follow-up containing only the relevant turns
                if st.session_state.get("debug_agent"):
                    with st.expander("Debug: generic tool follow-up messages", expanded=False):
                        st.code(json.dumps(followup_messages, indent=2)[:4000], language="json")
                followup_resp = snowflake_api_call(followup_messages, show_error=False)
                f_text, _, _, _, _, _ = process_sse_response(followup_resp)
                if f_text:
                    final_text = f_text
                else:
                    final_text = initial_text

            # After tool flows, render the final assistant text and any citations
            if initial_text or 'final_text' in locals():
                display_text = (locals().get('final_text') or initial_text)
                st.session_state.messages.append({"role": "assistant", "content": display_text})
                with st.chat_message("assistant"):
                    st.markdown(display_text.replace("•", "\n\n"))
                    if citations:
                        st.write("Citations:")
                        for citation in citations:
                            doc_id = citation.get("doc_id", "")
                            if doc_id:
                                query = f"SELECT transcript_text FROM MDM_CUSTOMER_MATCHING.PUBLIC.sales_conversations WHERE conversation_id = '{doc_id}'"
                                result = run_snowflake_query(query)
                                result_df = result.to_pandas()
                                transcript_text = result_df.iloc[0, 0] if not result_df.empty else "No transcript available"
                                with st.expander(f"[{citation.get('source_id', '')}]"):
                                    st.write(transcript_text)

            # Persist and show results without clearing previous ones
            if sql_to_run or executed_df is not None or 'final_text' in locals() or initial_text:
                st.session_state.results_history.append({
                    "question": query,
                    "text": (locals().get('final_text') or initial_text),
                    "sql": sql_to_run or sql,
                    "query_id": executed_query_id,
                    "df": executed_df
                })

            # Render full history of results
            for idx, item in enumerate(st.session_state.results_history, start=1):
                st.markdown(f"### Response {idx}")
                if item.get("text"):
                    st.markdown(item["text"].replace("•", "\n\n"))
                if item.get("sql"):
                    st.markdown("#### Generated SQL (from tools)")
                    st.code(item["sql"], language="sql")
                if item.get("df") is not None:
                    st.write(f"#### Query Results{f' (query_id: {item.get('query_id')})' if item.get('query_id') else ''}")
                    st.dataframe(item["df"])

if __name__ == "__main__":
    main()