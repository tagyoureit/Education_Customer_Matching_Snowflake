import streamlit as st
import pandas as pd
import json
from snowflake.snowpark.session import Session
import snowflake.connector # Import the standard connector

# --- 1. CONNECTION INITIALIZATION ---
# Use st.cache_resource to create the connections only once.
@st.cache_resource
def create_connections():
    """
    Creates two connections:
    1. A Snowpark Session for DataFrame operations (session.sql).
    2. A standard Snowflake Connector for raw API calls.
    """
    try:
        creds = st.secrets["snowflake"]
        snowpark_session = Session.builder.configs(creds).create()
        connector_conn = snowflake.connector.connect(**creds)
        return snowpark_session, connector_conn
    except Exception as e:
        st.error(f"Failed to create Snowflake connections: {e}")
        return None, None

# Create and unpack both connection objects
session, conn = create_connections()

# --- 2. CONSTANTS (UNCHANGED) ---
API_ENDPOINT = "/api/v2/cortex/agent:run"
API_TIMEOUT = 50000  # in milliseconds

CORTEX_SEARCH_SERVICES = "sales_intelligence.data.sales_conversation_search"
SEMANTIC_MODELS = "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"

# --- 3. HELPER FUNCTIONS ---

def run_snowflake_query(query: str) -> pd.DataFrame:
    """Executes a query using the Snowpark session and returns a Pandas DataFrame."""
    if not session:
        st.error("Snowflake session not available.")
        return pd.DataFrame()
    try:
        return session.sql(query.replace(';','')).to_pandas()
    except Exception as e:
        st.error(f"Error executing SQL: {str(e)}")
        return pd.DataFrame()

def snowflake_api_call(sf_connector_conn, query: str, limit: int = 10):
    """
    Makes a POST request to a Snowflake internal API endpoint using the standard connector.
    FIX: This function now requires the standard 'snowflake.connector' connection object.
    """
    if not sf_connector_conn:
        st.error("Snowflake connector not available for API call.")
        return None

    payload = {
        "model": "claude-4-sonnet",
        "messages": [{"role": "user", "content": [{"type": "text", "text": query}]}],
        "tools": [
            {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "analyst1"}},
            {"tool_spec": {"type": "cortex_search", "name": "search1"}}
        ],
        "tool_resources": {"analyst1": {"semantic_model_file": SEMANTIC_MODELS}}
    }

    try:
        # FIX: Use the standard connector object's public method.
        # The body (payload) should be a dict, which the method handles.
        resp = sf_connector_conn.send_snow_api_request(
            "POST",
            API_ENDPOINT,
            {}, {},
            payload,
            None,
            API_TIMEOUT,
        )

        if resp["status"] != 200:
            st.error(f"❌ HTTP Error: {resp['status']} - {resp.get('reason', 'Unknown reason')}")
            st.json(resp)
            return None

        # The content is the raw byte string, which is what process_sse_response expects
        return resp["content"]

    except Exception as e:
        st.error(f"Error making API request: {str(e)}")
        return None


def process_sse_response(response_content):
    """Process Server-Sent Events (SSE) response which is a byte string."""
    text = ""
    sql = ""
    citations = []

    if not response_content:
        return text, sql, citations

    try:
        events = response_content.decode('utf-8').strip().split('\n\n')
        for event_str in events:
            if not event_str.strip(): continue
            lines = event_str.strip().split('\n')
            event_type, data_json = "", ""
            for line in lines:
                if line.startswith('event:'): event_type = line.split(':', 1)[1].strip()
                elif line.startswith('data:'): data_json = line.split(':', 1)[1].strip()

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

    except Exception as e:
        st.error(f"Error processing SSE events: {str(e)}")

    return text, sql, citations


def main():
    st.title("Intelligent Sales Assistant")

    # Check that both connections were successful
    if not session or not conn:
        st.warning("Could not connect to Snowflake. Please check your credentials in st.secrets.")
        st.stop()
    else:
        st.success("❄️ Connected to Snowflake!")

    with st.sidebar:
        if st.button("New Conversation", key="new_chat"):
            st.session_state.messages = []
            st.rerun()

    if 'messages' not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'].replace("•", "\n\n"))

    if query := st.chat_input("What would you like to know?"):
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.spinner("Thinking..."):
            # FIX: Pass the standard connector object 'conn' to the API call function
            response_content = snowflake_api_call(conn, query, 1)
            text, sql, citations = process_sse_response(response_content)

            if text:
                text = text.replace("【†", " [").replace("†】", "]")
                st.session_state.messages.append({"role": "assistant", "content": text})

                with st.chat_message("assistant"):
                    st.markdown(text.replace("•", "\n\n"))
                    if citations:
                        st.write("Citations:")
                        for citation in citations:
                            doc_id = citation.get("doc_id", "")
                            if doc_id:
                                query_str = f"SELECT transcript_text FROM sales_conversations WHERE conversation_id = '{doc_id}'"
                                result_df = run_snowflake_query(query_str)
                                transcript_text = result_df.iloc[0, 0] if not result_df.empty else "No transcript available"
                                with st.expander(f"Source [{citation.get('source_id', '')}]"):
                                    st.text(transcript_text)
            if sql:
                st.markdown("### Generated SQL")
                st.code(sql, language="sql")
                sales_results_df = run_snowflake_query(sql)
                if not sales_results_df.empty:
                    st.write("### Query Results")
                    st.dataframe(sales_results_df)

if __name__ == "__main__":
    main()
