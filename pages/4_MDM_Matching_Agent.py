import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import requests
import sseclient
import streamlit as st
import snowflake.connector
import toml

from models import (
    ChartEventData,
    DataAgentRunRequest,
    ErrorEventData,
    Message,
    MessageContentItem,
    StatusEventData,
    TableEventData,
    TextContentItem,
    TextDeltaEventData,
    ThinkingDeltaEventData,
    ThinkingEventData,
    ToolResultEventData,
    ToolUseEventData,
)


st.set_page_config(
    page_title="MDM Matching Agent",
    page_icon="🤖",
    layout="wide",
)


@st.cache_resource
def get_snowflake_connection():
    """Create Snowflake connection using snow CLI config or environment variables."""
    try:
        connections_path = os.path.expanduser("~/.snowflake/connections.toml")
        if os.path.exists(connections_path):
            with open(connections_path, 'r') as f:
                config = toml.load(f)
                default_conn = config.get('default', {})
                connection_params = {
                    'account': default_conn.get('account'),
                    'user': default_conn.get('user'),
                    'password': default_conn.get('password'),
                    'database': 'MDM_CUSTOMER_MATCHING',
                    'schema': 'PUBLIC',
                    'warehouse': 'COMPUTE_WH',
                }
        else:
            connection_params = {
                'account': os.getenv('SNOWFLAKE_ACCOUNT'),
                'user': os.getenv('SNOWFLAKE_USER'),
                'password': os.getenv('SNOWFLAKE_PASSWORD'),
                'database': 'MDM_CUSTOMER_MATCHING',
                'schema': 'PUBLIC',
                'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH'),
            }

        connection_params = {k: v for k, v in connection_params.items() if v is not None}
        return snowflake.connector.connect(**connection_params)
    except Exception as e:
        st.error(f"Failed to connect to Snowflake: {str(e)}")
        st.stop()


def resolve_host(conn) -> str:
    """Resolve Snowflake account host using secrets/env/connection."""
    host = os.getenv('SNOWFLAKE_HOST')
    if not host:
        try:
            if 'snowflake' in st.secrets and 'account' in st.secrets['snowflake']:
                account = st.secrets['snowflake']['account']
                if account:
                    host = f"{account}.snowflakecomputing.com"
        except Exception:
            pass
    if not host:
        account = os.getenv('SNOWFLAKE_ACCOUNT')
        if account:
            host = f"{account}.snowflakecomputing.com"
    # Final normalize
    if host:
        host = host.replace('https://', '').replace('http://', '').strip('/')
        if '_' in host:
            host = host.replace('_', '-')
    return host


def get_auth_token(conn) -> str:
    rest_obj = getattr(conn, 'rest', None)
    if rest_obj is not None and hasattr(rest_obj, 'token') and rest_obj.token:
        return rest_obj.token
    token = getattr(conn, '_auth_token', None)
    return token


# Defaults per user confirmation
DEFAULT_DATABASE = "SNOWFLAKE_INTELLIGENCE"
DEFAULT_SCHEMA = "AGENTS"
DEFAULT_AGENT = "MDM_MATCHING_AGENT"


def agent_run(conn) -> requests.Response:
    """Calls the REST API with session auth and returns a streaming client."""
    host = resolve_host(conn)
    if not host:
        raise Exception("Unable to resolve Snowflake host from connection/environment.")

    token = get_auth_token(conn)
    if not token:
        raise Exception("Unable to obtain Snowflake session token for REST call.")

    request_body = DataAgentRunRequest(
        model="llama3.3-70b",  # ignored by agents endpoint, safe to include
        messages=st.session_state.messages,
    )

    url = (
        f"https://{host}/api/v2/databases/{DEFAULT_DATABASE}/schemas/{DEFAULT_SCHEMA}/agents/{DEFAULT_AGENT}:run"
    )

    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    resp = requests.post(
        url=url,
        data=request_body.to_json(),
        headers=headers,
        stream=True,
    )
    if resp.status_code < 400:
        return resp  # type: ignore
    else:
        raise Exception(f"Failed request with status {resp.status_code}: {resp.text}")


def stream_events(response: requests.Response):
    content = st.container()
    # Content index to container section mapping
    content_map = defaultdict(content.empty)
    # Content index to text buffer
    buffers = defaultdict(str)
    spinner = st.spinner("Waiting for response...")
    spinner.__enter__()

    events = sseclient.SSEClient(response).events()
    for event in events:
        match event.event:
            case "response.status":
                spinner.__exit__(None, None, None)
                data = StatusEventData.from_json(event.data)
                spinner = st.spinner(data.message)
                spinner.__enter__()
            case "response.text.delta":
                data = TextDeltaEventData.from_json(event.data)
                buffers[data.content_index] += data.text
                content_map[data.content_index].write(buffers[data.content_index])
            case "response.thinking.delta":
                data = ThinkingDeltaEventData.from_json(event.data)
                buffers[data.content_index] += data.text
                content_map[data.content_index].expander(
                    "Thinking", expanded=True
                ).write(buffers[data.content_index])
            case "response.thinking":
                # Thinking done, close the expander
                data = ThinkingEventData.from_json(event.data)
                content_map[data.content_index].expander("Thinking").write(data.text)
            case "response.tool_use":
                data = ToolUseEventData.from_json(event.data)
                content_map[data.content_index].expander("Tool use").json(data)
            case "response.tool_result":
                data = ToolResultEventData.from_json(event.data)
                content_map[data.content_index].expander("Tool result").json(data)
            case "response.chart":
                data = ChartEventData.from_json(event.data)
                spec = json.loads(data.chart_spec)
                content_map[data.content_index].vega_lite_chart(
                    spec,
                    use_container_width=True,
                )
            case "response.table":
                data = TableEventData.from_json(event.data)
                data_array = np.array(data.result_set.data)
                column_names = [
                    col.name for col in data.result_set.result_set_meta_data.row_type
                ]
                content_map[data.content_index].dataframe(
                    pd.DataFrame(data_array, columns=column_names)
                )
            case "error":
                data = ErrorEventData.from_json(event.data)
                st.error(f"Error: {data.message} (code: {data.code})")
                # Remove last user message, so we can retry from last successful response.
                st.session_state.messages.pop()
                return
            case "response":
                data = Message.from_json(event.data)
                st.session_state.messages.append(data)
    spinner.__exit__(None, None, None)


def process_new_message(conn, prompt: str) -> None:
    message = Message(
        role="user",
        content=[MessageContentItem(TextContentItem(type="text", text=prompt))],
    )
    render_message(message)
    st.session_state.messages.append(message)

    with st.chat_message("assistant"):
        with st.spinner("Sending request..."):
            response = agent_run(conn)
        st.markdown(
            f"```request_id: {response.headers.get('X-Snowflake-Request-Id')}```"
        )
        stream_events(response)


def render_message(msg: Message):
    with st.chat_message(msg.role):
        for content_item in msg.content:
            match content_item.actual_instance.type:
                case "text":
                    st.markdown(content_item.actual_instance.text)
                case "chart":
                    spec = json.loads(content_item.actual_instance.chart.chart_spec)
                    st.vega_lite_chart(spec, use_container_width=True)
                case "table":
                    data_array = np.array(
                        content_item.actual_instance.table.result_set.data
                    )
                    column_names = [
                        col.name
                        for col in content_item.actual_instance.table.result_set.result_set_meta_data.row_type
                    ]
                    st.dataframe(pd.DataFrame(data_array, columns=column_names))
                case _:
                    st.expander(content_item.actual_instance.type).json(
                        content_item.actual_instance.to_json()
                    )


def main():
    st.title("MDM Matching Agent")

    # Ensure connection (for session token + host)
    conn = get_snowflake_connection()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        render_message(message)

    if user_input := st.chat_input("What is your question?"):
        process_new_message(conn, prompt=user_input)


if __name__ == "__main__":
    main()


