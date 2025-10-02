"""
Agent Test Page – Minimal, focused harness to exercise Cortex Agents REST API
Modeled after Snowflake quickstart patterns, with explicit tool config and live SSE parsing.
"""

import streamlit as st
import pandas as pd
import snowflake.connector
import os
import json
import requests
import toml
import sys
from typing import Dict
from shared_utils import (
    recalculate_similarity_for_test_id,
    DEFAULT_THRESHOLDS,
)

# Page configuration
st.set_page_config(page_title="🧪 Agent Test", page_icon="🧪", layout="wide")

# Constants
SEMANTIC_MODEL_PATH = "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"


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
                    'warehouse': 'COMPUTE_WH'
                }
        else:
            connection_params = {
                'account': os.getenv('SNOWFLAKE_ACCOUNT'),
                'user': os.getenv('SNOWFLAKE_USER'),
                'password': os.getenv('SNOWFLAKE_PASSWORD'),
                'database': 'MDM_CUSTOMER_MATCHING',
                'schema': 'PUBLIC',
                'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH')
            }
        connection_params = {k: v for k, v in connection_params.items() if v is not None}
        return snowflake.connector.connect(**connection_params)
    except Exception as e:
        st.error(f"Failed to connect to Snowflake: {str(e)}")
        st.stop()


def resolve_host(conn) -> str:
    host = os.getenv('SNOWFLAKE_HOST')
    if not host:
        rest_obj = getattr(conn, 'rest', None)
        if rest_obj is not None and hasattr(rest_obj, 'host') and rest_obj.host:
            host = rest_obj.host
    if not host:
        # Try Streamlit secrets first
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


def parse_agent_path(agent_path: str):
    """Split 'DB.SCHEMA.AGENT' into components. Returns (db, schema, agent) or (None, None, agent_path)."""
    try:
        parts = (agent_path or '').split('.')
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return None, None, agent_path
    except Exception:
        return None, None, agent_path


def create_thread(pat_token: str, host: str, origin_application: str = "AgentTest") -> str:
    """Create a Cortex thread and return its ID using Bearer PAT. Returns None on failure."""
    try:
        url = f"https://{host}/api/v2/cortex/threads"
        headers = {
            "Authorization": f"Bearer {pat_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Snowflake requires origin_application <= 16 bytes
        safe_origin = (origin_application or "AgentTest")[:16]
        body = {"origin_application": safe_origin}
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        st.session_state['thread_create_last_status'] = getattr(resp, 'status_code', None)
        try:
            st.session_state['thread_create_last_body'] = resp.text[:1000]
        except Exception:
            st.session_state['thread_create_last_body'] = None
        if resp.status_code >= 400:
            return None
        data = resp.json() if resp.content else {}
        # Support a few possible shapes
        thread_id = (
            data.get("thread_id")
            or data.get("id")
            or (data.get("thread") or {}).get("id")
        )
        return thread_id
    except Exception:
        st.session_state['thread_create_last_status'] = 'exception'
        st.session_state['thread_create_last_body'] = 'exception during POST to /api/v2/cortex/threads'
        return None


def post_thread_message(pat_token: str, host: str, thread_id: str, prompt: str):
    """Post a user message to an existing thread; return (message_id, debug_dict)."""
    dbg = {}
    try:
        url = f"https://{host}/api/v2/cortex/threads/{thread_id}/messages"
        headers = {
            "Authorization": f"Bearer {pat_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        }
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        dbg['status'] = getattr(resp, 'status_code', None)
        try:
            dbg['body'] = resp.text[:1000]
        except Exception:
            dbg['body'] = None
        if resp.status_code >= 400:
            return None, dbg
        data = resp.json() if resp.content else {}
        # Common shapes: { id: "..." } or { message: { id: "..." } }
        mid = data.get('id') or (data.get('message') or {}).get('id')
        return mid, dbg
    except Exception:
        dbg['status'] = 'exception'
        return None, dbg


def call_agent(prompt: str, conn, use_sse: bool = True, request_timeout: int = 60, sse_max_seconds: int = 25, pat_token: str = None, host_override: str = None, agent_name: str = None, thread_id: str = None, parent_message_id: str = None, on_event=None):
    """Call Cortex Agents REST API, optionally stream SSE, capture Analyst SQL, and return results + debug.

    Adds robust timeouts and returns debug metadata to avoid the UI appearing to hang.
    """
    host = host_override or resolve_host(conn)
    if not host:
        return {"error": "Unable to determine Snowflake host. Set SNOWFLAKE_HOST or SNOWFLAKE_ACCOUNT."}

    # Prefer PAT if provided; otherwise fall back to session token from connector
    token = None
    if not pat_token:
        token = get_auth_token(conn)
        if not token:
            return {"error": "Unable to obtain Snowflake session token for REST call. Provide PAT or ensure active connector session."}

    # Prefer DB/SCHEMA/AGENT scoped endpoint per Quickstart
    db_name, schema_name, short_agent = parse_agent_path(agent_name or "")
    if db_name and schema_name and short_agent:
        api_url = f"https://{host}/api/v2/databases/{db_name}/schemas/{schema_name}/agents/{short_agent}:run"
    else:
        api_url = f"https://{host}/api/v2/cortex/agent:run"

    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        }
    ]

    request_body = {
        "agent": agent_name or "SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT",
        "model": "llama3.3-70b",
        "response_instruction": (
            "For any question about matches, similarity, categories, or counts, you MUST use your tools: "
            "first use cortex_analyst_text_to_sql (semantic model) to generate SQL, then use sql_exec to run it. "
            "Do not answer from general knowledge without querying the data. Return a concise textual answer and include SQL when appropriate."
        ),
        "experimental": {},
        "tool_choice": {"type": "auto"},
        "messages": messages
    }
    # If using threads, ensure parent_message_id is present; if not, create a message first
    posted_msg_debug = None
    if thread_id:
        # Only include thread_id if we also have/obtain a parent_message_id
        if pat_token and not parent_message_id:
            _mid, posted_msg_debug = post_thread_message(pat_token, host, thread_id, prompt)
            parent_message_id = _mid
        if parent_message_id:
            request_body["thread_id"] = thread_id
            request_body["parent_message_id"] = parent_message_id
            # When referencing a thread message, omit inline messages to avoid duplication
            request_body.pop("messages", None)
        else:
            # Fallback: do NOT pass thread_id; let server run stateless and return thread info
            request_body.pop("thread_id", None)

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if use_sse else "application/json",
    }
    if pat_token:
        headers["Authorization"] = f"Bearer {pat_token}"
    else:
        headers["Authorization"] = f'Snowflake Token="{token}"'

    try:
        # Use separate connect/read timeouts to avoid hanging indefinitely between frames
        response = requests.post(
            api_url,
            json=request_body,
            headers=headers,
            timeout=(min(10, request_timeout), request_timeout),
            stream=use_sse,
        )
    except Exception as e:
        return {"error": f"Request failed: {str(e)}", "debug": {"host": host, "use_sse": use_sse, "timeout": request_timeout}}
    if response.status_code >= 400:
        return {"error": f"Agent REST error {response.status_code}: {response.text[:500]}", "debug": {"host": host, "use_sse": use_sse, "timeout": request_timeout, "status": response.status_code}}

    sse_lines = []
    text_chunks = []
    analyst_sql = None
    tools_observed = []  # Collect tool_use and tool_results for debugging and UI
    thinking_buffer = []  # Collect response.thinking.delta
    events_collected = []  # Collect raw SSE events for UI
    charts_collected = []  # Collect Vega-Lite specs
    tables_collected = []  # Collect table result_set payloads
    returned_thread_id = None

    ctype = response.headers.get('Content-Type', '')

    # Helper to avoid duplicate consecutive text chunk appends (some servers emit both text.delta and delta.content)
    def _append_text_chunk_unique(chunk_text: str):
        try:
            if not isinstance(chunk_text, str) or not chunk_text:
                return
            if text_chunks and chunk_text == text_chunks[-1]:
                return
            text_chunks.append(chunk_text)
        except Exception:
            # Fallback to simple append on unexpected types
            try:
                text_chunks.append(chunk_text)
            except Exception:
                pass
    if use_sse and 'text/event-stream' in ctype:
        import time as _time
        start_ts = _time.monotonic()
        current_event = None
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if line.startswith('event:'):
                current_event = line[len('event:'):].strip()
                continue
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            sse_lines.append(payload)
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            # Collect raw event for downstream display
            try:
                events_collected.append({"event": current_event or (obj.get('type') if isinstance(obj, dict) else None), "payload": obj})
            except Exception:
                pass
            # Try to capture thread id from frame
            if isinstance(obj, dict):
                if 'response' in obj and isinstance(obj['response'], dict):
                    returned_thread_id = obj['response'].get('thread_id') or returned_thread_id
                if 'message' in obj and isinstance(obj['message'], dict):
                    returned_thread_id = obj['message'].get('thread_id') or returned_thread_id
            # Use named event types when provided (per Quickstart)
            etype = current_event or (obj.get('type', '') if isinstance(obj, dict) else '')
            if etype == 'response.text.delta' and isinstance(obj, dict):
                data_block = obj.get('data') or obj.get('delta') or obj
                text_val = data_block.get('text') if isinstance(data_block, dict) else None
                if isinstance(text_val, str):
                    _append_text_chunk_unique(text_val)
                    if callable(on_event):
                        try:
                            on_event('response.text.delta', text_val)
                        except Exception:
                            pass
            elif etype == 'response.status' and isinstance(obj, dict):
                # No-op: could surface as progress text in future
                if callable(on_event):
                    try:
                        msg = (obj.get('data') or {}).get('message') if isinstance(obj.get('data'), dict) else None
                        on_event('response.status', msg)
                    except Exception:
                        pass
            elif etype == 'response.thinking.delta' and isinstance(obj, dict):
                data_block = obj.get('data') or obj.get('delta') or obj
                tval = data_block.get('text') if isinstance(data_block, dict) else None
                if isinstance(tval, str):
                    thinking_buffer.append(tval)
                    if callable(on_event):
                        try:
                            on_event('response.thinking.delta', tval)
                        except Exception:
                            pass
            elif etype == 'response.thinking' and isinstance(obj, dict):
                # Some implementations send the final thinking text; replace buffer to avoid duplication
                data_block = obj.get('data') or obj
                tval = data_block.get('text') if isinstance(data_block, dict) else None
                if isinstance(tval, str):
                    thinking_buffer = [tval]
                    if callable(on_event):
                        try:
                            on_event('response.thinking', tval)
                        except Exception:
                            pass
            elif etype == 'response.tool_use' and isinstance(obj, dict):
                tu = obj.get('data') or obj.get('tool_use') or obj
                tname = tu.get('name', '')
                ttype = tu.get('type')
                tools_observed.append({"phase": "tool_use", "name": tname, "type": ttype})
                if callable(on_event):
                    try:
                        on_event('response.tool_use', {"name": tname, "type": ttype})
                    except Exception:
                        pass
            elif etype == 'response.tool_result' and isinstance(obj, dict):
                tr = obj.get('data') or obj.get('tool_results') or obj
                tname = tr.get('name', '')
                status = tr.get('status')
                tools_observed.append({"phase": "tool_results", "name": tname, "status": status})
                if isinstance(tname, str) and 'analyst' in tname.lower():
                    for c in (tr.get('content') or []):
                        if c.get('type') == 'json' and isinstance(c.get('json'), dict):
                            possible_sql = c['json'].get('sql')
                            if possible_sql:
                                analyst_sql = possible_sql
                if callable(on_event):
                    try:
                        on_event('response.tool_result', {"name": tname, "status": status})
                    except Exception:
                        pass
            elif etype == 'response.chart':
                try:
                    data_block = obj.get('data') or obj
                    spec_raw = data_block.get('chart_spec')
                    if isinstance(spec_raw, str):
                        import json as _json
                        charts_collected.append(_json.loads(spec_raw))
                    elif isinstance(spec_raw, dict):
                        charts_collected.append(spec_raw)
                except Exception:
                    pass
            elif etype == 'response.table':
                try:
                    data_block = obj.get('data') or obj
                    if 'result_set' in data_block:
                        tables_collected.append(data_block['result_set'])
                except Exception:
                    pass
            elif isinstance(obj, dict) and 'delta' in obj:
                # Documented pattern: response.* with delta
                delta = obj.get('delta') or {}
                # Some variants embed content list, others provide text directly
                if 'content' in delta:
                    for item in delta.get('content', []):
                        if item.get('type') == 'text' and item.get('text'):
                            _append_text_chunk_unique(item['text'])
                        elif item.get('type') == 'tool_results':
                            tr = item.get('tool_results', {})
                            tool_name = tr.get('name', '')
                            status = tr.get('status')
                            if tool_name or status:
                                tools_observed.append({"phase": "tool_results", "name": tool_name, "status": status})
                            if isinstance(tool_name, str) and 'analyst' in tool_name.lower():
                                for c in tr.get('content', []):
                                    if c.get('type') == 'json' and isinstance(c.get('json'), dict):
                                        possible_sql = c['json'].get('sql')
                                        if possible_sql:
                                            analyst_sql = possible_sql
                elif 'text' in delta and isinstance(delta.get('text'), str):
                    _append_text_chunk_unique(delta['text'])
            # else: other event types ignored for now
            # Stop streaming if we have any text or analyst SQL and we've streamed for long enough
            if (_time.monotonic() - start_ts) > sse_max_seconds:
                break
    else:
        # Non-SSE: attempt simple JSON parse
        try:
            obj = response.json()
            # Detect session expiration (390112) and surface explicitly
            if isinstance(obj, dict):
                code_val = str(obj.get('code') or obj.get('error_code') or '')
                msg_val = str(obj.get('message') or '')
                if code_val == '390112' or 'session has expired' in msg_val.lower():
                    return {
                        "error": msg_val or "Session expired",
                        "expired_session": True,
                        "text": None,
                        "analyst_sql": None,
                        "sse": [],
                        "debug": {
                            "host": host,
                            "use_sse": use_sse,
                            "timeout": request_timeout,
                            "content_type": ctype,
                            "status": getattr(response, 'status_code', None),
                            "json": obj,
                        },
                    }
            # Capture thread id from standard JSON response
            if isinstance(obj, dict):
                returned_thread_id = (
                    obj.get('thread_id')
                    or (obj.get('response') or {}).get('thread_id')
                    or (obj.get('message') or {}).get('thread_id')
                    or returned_thread_id
                )
            if isinstance(obj, dict) and 'message' in obj and 'content' in obj['message']:
                parts = obj['message']['content']
                texts = [p.get('text') for p in parts if p.get('type') == 'text' and p.get('text')]
                if texts:
                    text_chunks.append("\n\n".join(texts))
                for p in parts:
                    if p.get('type') == 'tool_results':
                        tr = p.get('tool_results', {})
                        tool_name = tr.get('name', '')
                        status = tr.get('status')
                        if tool_name or status:
                            tools_observed.append({"phase": "tool_results", "name": tool_name, "status": status})
                        if 'analyst' in tool_name.lower():
                            for c in tr.get('content', []):
                                if c.get('type') == 'json' and isinstance(c.get('json'), dict):
                                    sql = c['json'].get('sql')
                                    if sql:
                                        analyst_sql = sql
                    elif p.get('type') == 'tool_use':
                        tu = p.get('tool_use', {})
                        tool_type = tu.get('type')
                        tname = tu.get('name', '')
                        if tname or tool_type:
                            tools_observed.append({"phase": "tool_use", "name": tname, "type": tool_type})
            # Fallback: sometimes responses may nest data differently; include object in debug
            fallback_json = obj
        except Exception:
            fallback_json = None

    result_payload = {
        "text": "".join(text_chunks) if text_chunks else None,
        "analyst_sql": analyst_sql,
        "sse": sse_lines,
        "thinking": "".join(thinking_buffer) if thinking_buffer else None,
        "events": events_collected,
        "charts": charts_collected,
        "tables": tables_collected,
        "debug": {
            "host": host,
            "use_sse": use_sse,
            "timeout": request_timeout,
            "content_type": ctype,
            "status": getattr(response, 'status_code', None),
        },
    }
    if posted_msg_debug is not None:
        result_payload["debug"]["posted_thread_message"] = posted_msg_debug
    if tools_observed:
        result_payload["debug"]["tools"] = tools_observed
    if returned_thread_id:
        result_payload["thread_id"] = returned_thread_id

    # If we used a thread and have a final assistant text, append it to the thread as an assistant message
    try:
        if pat_token and (thread_id or returned_thread_id) and result_payload.get('text'):
            tid = thread_id or returned_thread_id
            url = f"https://{host}/api/v2/cortex/threads/{tid}/messages"
            headers_pm = {
                "Authorization": f"Bearer {pat_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            body_pm = {
                "role": "assistant",
                "content": [{"type": "text", "text": result_payload['text']}]
            }
            # Best effort, ignore failures
            try:
                requests.post(url, headers=headers_pm, json=body_pm, timeout=10)
            except Exception:
                pass
    except Exception:
        pass
    # If nothing useful extracted, surface body preview and parsed JSON for troubleshooting
    if not result_payload["text"] and not result_payload["analyst_sql"]:
        try:
            body_preview = response.text[:1000]
        except Exception:
            body_preview = None
        result_payload["debug"]["body_preview"] = body_preview
        if 'fallback_json' in locals() and fallback_json is not None:
            # Truncate nested JSON for readability
            try:
                import json as _json
                result_payload["debug"]["json"] = _json.loads(_json.dumps(fallback_json))
            except Exception:
                result_payload["debug"]["json"] = str(fallback_json)[:1000]
    return result_payload


def update_test_record_via_sql(_conn, record_id: str, updates: Dict) -> bool:
    """Update a TEST_MATCHES record and refresh its embedding."""
    try:
        cursor = _conn.cursor()

        set_clauses = []
        params = []

        for field, value in updates.items():
            if field.upper() in [
                'NAME', 'SOURCE_SYSTEM', 'ADDRESS_LINE_1', 'ADDRESS_LINE_2',
                'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY'
            ]:
                set_clauses.append(f"{field.upper()} = %s")
                params.append(value)

        if not set_clauses:
            return False

        # Always recompute CUSTOMER_FULL_DETAIL based on current values
        set_clauses.append("CUSTOMER_FULL_DETAIL = %s")

        cursor.execute(
            "SELECT NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY FROM TEST_MATCHES WHERE SOURCE_PKEY = %s",
            (record_id,)
        )
        current_record = cursor.fetchone()

        if not current_record:
            cursor.close()
            return False

        updated_values = list(current_record)
        field_names = ['NAME', 'ADDRESS_LINE_1', 'ADDRESS_LINE_2', 'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY']
        for i, field in enumerate(field_names):
            if field in updates:
                updated_values[i] = updates[field]

        full_detail = " ".join([str(v) for v in updated_values if v]).strip()
        params.append(full_detail)
        params.append(record_id)

        update_sql = f"UPDATE TEST_MATCHES SET {', '.join(set_clauses)} WHERE SOURCE_PKEY = %s"
        cursor.execute(update_sql, params)

        # Refresh the embedding for the updated record
        embedding_sql = (
            """
            UPDATE TEST_MATCHES
            SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
            WHERE SOURCE_PKEY = %s
            """
        )
        cursor.execute(embedding_sql, (record_id,))

        cursor.close()
        return True

    except Exception as e:
        st.error(f"Error updating record via SQL: {str(e)}")
        return False


def get_updated_top_matches(_conn, test_id: str, limit: int = 5, thresholds: Dict[str, float] = None) -> pd.DataFrame:
    """Return top-N matches for a specific TEST record using the same thresholds."""
    try:
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()

        query_sql = (
            """
            SELECT 
                v.ID AS VALID_ID,
                v.CUSTOMER_FULL_DETAIL AS VALID_CUSTOMER_FULL_DETAIL,
                t.SOURCE_PKEY AS TEST_ID,
                t.CUSTOMER_FULL_DETAIL AS TEST_CUSTOMER_FULL_DETAIL,
                VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) AS SIMILARITY_SCORE,
                CASE 
                    WHEN SIMILARITY_SCORE >= %s THEN 'EXACT'
                    WHEN SIMILARITY_SCORE >= %s THEN 'VERY_CLOSE'
                    WHEN SIMILARITY_SCORE >= %s THEN 'SOMEWHAT_CLOSE'
                    ELSE 'NOT_CLOSE'
                END AS MATCH_CATEGORY
            FROM VALID_CUSTOMERS v
            CROSS JOIN TEST_MATCHES t
            WHERE 
                t.SOURCE_PKEY = %s
                AND v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR IS NOT NULL 
                AND t.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL
            ORDER BY SIMILARITY_SCORE DESC
            LIMIT %s
            """
        )

        matches = pd.read_sql(
            query_sql,
            _conn,
            params=(
                thresholds['exact'],
                thresholds['very_close'],
                thresholds['somewhat_close'],
                test_id,
                limit,
            ),
        )
        return matches

    except Exception as e:
        st.error(f"Error getting updated top matches: {str(e)}")
        return pd.DataFrame()


def show_inline_edit_form_for_customer(_conn, source_pkey: str, thresholds: Dict[str, float]):
    """Inline form to edit a specific TEST_MATCHES record and recalc its similarity."""
    with st.expander(f"📝 Edit Customer: {source_pkey}", expanded=True):
        try:
            cursor = _conn.cursor()
            cursor.execute(
                """
                SELECT SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1,
                       ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY,
                       CUSTOMER_FULL_DETAIL
                FROM TEST_MATCHES
                WHERE SOURCE_PKEY = %s
                """,
                (source_pkey,),
            )
            result = cursor.fetchone()
            cursor.close()

            if not result:
                st.error(f"Customer {source_pkey} not found")
                return

            columns = [
                'SOURCE_PKEY', 'NAME', 'SOURCE_SYSTEM', 'ADDRESS_LINE_1',
                'ADDRESS_LINE_2', 'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY', 'CUSTOMER_FULL_DETAIL'
            ]
            record = dict(zip(columns, result))

            with st.form(f"agent_edit_form_{source_pkey}"):
                st.write(f"**Current Details:** {record['CUSTOMER_FULL_DETAIL']}")

                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("Name", value=record['NAME'] or '')
                    source_system = st.text_input("Source System", value=record['SOURCE_SYSTEM'] or '')
                    address1 = st.text_input("Address 1", value=record['ADDRESS_LINE_1'] or '')
                    city = st.text_input("City", value=record['CITY'] or '')

                with col2:
                    address2 = st.text_input("Address 2", value=record['ADDRESS_LINE_2'] or '')
                    state = st.text_input("State", value=record['STATE'] or '')
                    postal = st.text_input("Postal Code", value=record['POSTAL_CODE'] or '')
                    country = st.text_input("Country", value=record['COUNTRY'] or '')

                if st.form_submit_button("💾 Update Customer", use_container_width=True):
                    updates = {
                        'NAME': name,
                        'SOURCE_SYSTEM': source_system,
                        'ADDRESS_LINE_1': address1,
                        'ADDRESS_LINE_2': address2,
                        'CITY': city,
                        'STATE': state,
                        'POSTAL_CODE': postal,
                        'COUNTRY': country,
                    }

                    if update_test_record_via_sql(_conn, source_pkey, updates):
                        st.success("✅ Customer updated successfully!")
                        # Recalculate similarity for just this record
                        recalc_success = recalculate_similarity_for_test_id(_conn, source_pkey, thresholds)
                        if recalc_success:
                            st.success("✅ Similarity recalculated for this record!")
                            updated_matches = get_updated_top_matches(_conn, source_pkey, 5, thresholds)
                            if not updated_matches.empty:
                                st.markdown("**New Top 5 Similarity Scores:**")
                                for _, match in updated_matches.iterrows():
                                    similarity_pct = match['SIMILARITY_SCORE'] * 100
                                    match_category = match['MATCH_CATEGORY']
                                    color = (
                                        "🟢" if match_category == 'EXACT' else
                                        "🟡" if match_category == 'VERY_CLOSE' else
                                        "🟠" if match_category == 'SOMEWHAT_CLOSE' else
                                        "🔴"
                                    )
                                    st.write(f"{color} **{similarity_pct:.4f}%** ({match_category}) - {match['VALID_CUSTOMER_FULL_DETAIL']}")
                        # Clear cached data between interactions
                        st.cache_data.clear()
                    else:
                        st.error("❌ Failed to update customer")
        except Exception as e:
            st.error(f"Error loading customer {source_pkey}: {str(e)}")


def run_and_render(prompt: str, conn, use_sse: bool, timeout_sec: int, pat_token: str = None, host_override: str = None, agent_name: str = None, thread_id: str = None):
    # Show prior history while current request streams
    history_area = st.container()
    with history_area:
        render_results_area(conn)

    # Live streaming containers - thinking first, then response
    thinking_area = st.empty()
    live_area = st.empty()

    def _on_event(evt_type, data):
        if evt_type == 'response.text.delta' and isinstance(data, str):
            # Append streamed text
            existing = st.session_state.get('stream_text', '')
            existing += data
            st.session_state['stream_text'] = existing
            live_area.markdown(existing)
        elif evt_type == 'response.thinking.delta' and isinstance(data, str):
            # Accumulate delta chunks for live display
            current_delta = st.session_state.get('stream_thinking_delta', '')
            current_delta += data
            st.session_state['stream_thinking_delta'] = current_delta
            
            # Show complete thinking + current delta
            complete_thinking = st.session_state.get('stream_thinking_complete', '')
            full_display = complete_thinking + current_delta
            
            thinking_area.empty()
            with thinking_area.container():
                with st.expander("Thinking", expanded=True):
                    st.write(full_display)
        elif evt_type == 'response.thinking' and isinstance(data, str):
            # Complete sentence - add to complete thinking and clear delta
            # Replace with the final complete thinking returned by the event to avoid duplication
            complete_thinking = data
            st.session_state['stream_thinking_complete'] = complete_thinking
            st.session_state['stream_thinking_delta'] = ''  # Clear the delta buffer
            
            thinking_area.empty()
            with thinking_area.container():
                with st.expander("Thinking", expanded=True):
                    st.write(complete_thinking)

    st.session_state['stream_text'] = ''
    st.session_state['stream_thinking'] = ''
    st.session_state['stream_thinking_complete'] = ''
    st.session_state['stream_thinking_delta'] = ''

    with st.spinner("Calling agent..."):
        result = call_agent(
            prompt,
            conn,
            use_sse=use_sse,
            request_timeout=timeout_sec,
            pat_token=pat_token,
            host_override=host_override,
            agent_name=agent_name,
            thread_id=thread_id,
            on_event=_on_event,
        )
    if result.get("expired_session"):
        st.toast("Session expired. Refreshing session and retrying...", icon="⚠️")
        get_snowflake_connection.clear()
        conn = get_snowflake_connection()
        with st.spinner("Retrying with refreshed session..."):
            result = call_agent(
                prompt,
                conn,
                use_sse=use_sse,
                request_timeout=timeout_sec,
                pat_token=pat_token,
                host_override=host_override,
                agent_name=agent_name,
                thread_id=thread_id,
                on_event=_on_event,
            )

    # Persist results (append to history) for subsequent renders
    st.session_state['show_examples'] = False
    # Ensure history list exists
    if 'agent_runs' not in st.session_state or not isinstance(st.session_state['agent_runs'], list):
        st.session_state['agent_runs'] = []
    # Build a stable entry for this run
    entry = {
        'text': result.get('text') or st.session_state.get('stream_text') or None,
        'thinking': result.get('thinking') or st.session_state.get('stream_thinking_complete') or None,
        'analyst_sql': result.get('analyst_sql'),
        'charts': result.get('charts') or [],
        'tables': result.get('tables') or [],
        'events': result.get('events') or [],
        'debug': result.get('debug') or {},
    }
    st.session_state['agent_runs'].append(entry)
    # Keep last_x for the right-side debug panels (most recent only)
    st.session_state["last_agent_result"] = result
    st.session_state['last_error'] = result.get('error')
    st.session_state['last_debug'] = result.get('debug')

    # If a thread id was returned by the API, store it for subsequent turns
    try:
        if isinstance(result, dict):
            api_thread_id = (
                result.get('thread_id')
                or (result.get('debug') or {}).get('thread_id')
                or None
            )
            if not api_thread_id:
                # Some responses might include it in the SSE lines we captured
                # Already parsed in call_agent -> returned_thread_id, so also try to propagate it via debug if available
                pass
            if api_thread_id:
                st.session_state['cortex_thread_id'] = api_thread_id
    except Exception:
        pass

    # Do not execute SQL locally; rely on server-side Agent tools only
    st.session_state['last_df'] = None

    # Clear live streaming areas to avoid duplicate on-screen output once history has been persisted
    try:
        thinking_area.empty()
        live_area.empty()
        history_area.empty()
    except Exception:
        pass


def render_results_area(conn):
    # Show any error/debug
    if st.session_state.get('last_error'):
        st.error(st.session_state['last_error'])
        if st.session_state.get('last_debug'):
            with st.expander("Debug info", expanded=False):
                st.json(st.session_state['last_debug'])
        return

    # Render full history (each run in order)
    history = st.session_state.get('agent_runs') or []
    for idx, ar in enumerate(history, start=1):
        # Thinking snapshot (final) if available
        if ar.get('thinking'):
            with st.expander(f"Thinking ({idx})", expanded=False):
                st.write(ar['thinking'])

        # Assistant response (final text)
        if ar.get('text'):
            st.markdown("**Assistant response:**")
            st.write(ar['text'])

        # Analyst SQL
        if ar.get('analyst_sql'):
            st.markdown("**Analyst SQL (informational):**")
            st.code(ar['analyst_sql'], language="sql")

        # Raw events
        if ar.get('events'):
            with st.expander(f"Agent events (raw) [{idx}]", expanded=False):
                st.json(ar['events'])

        # Charts
        if isinstance(ar.get('charts'), list) and ar['charts']:
            st.markdown("**Charts:**")
            for spec in ar['charts']:
                try:
                    st.vega_lite_chart(spec, use_container_width=True)
                except Exception:
                    st.json(spec)

        # Tables
        if isinstance(ar.get('tables'), list) and ar['tables']:
            st.markdown("**Tables:**")
            for tbl in ar['tables']:
                try:
                    import pandas as _pd
                    rows = tbl.get('data') or []
                    meta = (tbl.get('result_set_meta_data') or {}).get('row_type', [])
                    colnames = [c.get('name') for c in meta if isinstance(c, dict) and c.get('name')]

                    if rows and isinstance(rows[0], dict):
                        df = _pd.DataFrame(rows)
                    else:
                        df = _pd.DataFrame(rows, columns=colnames if colnames else None)

                    st.dataframe(df, use_container_width=True)
                except Exception:
                    st.json(tbl)

    # Render persistent results table with row selection
    df = st.session_state.get('last_df')
    if isinstance(df, pd.DataFrame) and not df.empty:
        st.markdown("**Results (select a row to edit):**")
        selection = st.dataframe(
            df,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            height=400,
        )
        if selection['selection']['rows']:
            sel_idx = selection['selection']['rows'][0]
            row = df.iloc[sel_idx]
            source_pkey = None
            for col in ['SOURCE_PKEY', 'TEST_ID', 'test_customer_id', 'TEST_CUSTOMER_ID']:
                if col in row and row[col]:
                    source_pkey = row[col]
                    break
            if not source_pkey and 'CUSTOMER_FULL_DETAIL' in row:
                import re as _re
                m = _re.search(r'TEST_[A-F0-9]+', str(row['CUSTOMER_FULL_DETAIL']))
                if m:
                    source_pkey = m.group(0)
            if source_pkey:
                show_inline_edit_form_for_customer(conn, str(source_pkey), DEFAULT_THRESHOLDS)

def main():
    st.title("🧪 Agent Test – Cortex Agents REST")
    conn = get_snowflake_connection()

    col_left, col_right = st.columns([3, 1])
    with col_right:
        with st.expander("🔧 Debug – Raw SSE frames", expanded=False):
            st.caption("Toggle SSE off if the agent appears to hang.")
            _res = st.session_state.get('last_agent_result')
            if _res and _res.get("sse"):
                for i, line in enumerate(_res["sse"], start=1):
                    st.text(f"[{i}] {line[:750]}")
            else:
                st.caption("Send a question to see streaming frames.")
        with st.expander("ℹ️ Request Debug", expanded=False):
            dbg = st.session_state.get('last_debug')
            if dbg:
                st.json(dbg)
            else:
                st.caption("Send a question to see request debug info (tools, thread, status).")

    # Controls: Only keep bottom input as the main prompt entry
    st.markdown("---")
    with col_left:
        use_sse = st.checkbox("Use streaming (SSE)", value=True)
        timeout_sec = st.number_input("Request timeout (seconds)", min_value=10, max_value=300, value=60, step=10)
        st.markdown("**Agent connection**")
        default_host = os.getenv('CORTEX_AGENT_DEMO_HOST') or os.getenv('SNOWFLAKE_HOST') or resolve_host(conn)
        default_agent = os.getenv('CORTEX_AGENT_DEMO_AGENT') or "SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT"
        host_input = st.text_input("Host (ACCOUNT_URL)", value=default_host or "")
        agent_input = st.text_input("Agent name", value=default_agent)
        # Load PAT from Streamlit secrets first, then env fallback
        pat_value = None
        try:
            if 'snowflake' in st.secrets and 'password' in st.secrets['snowflake']:
                pat_value = st.secrets['snowflake']['password']
        except Exception:
            pat_value = None
        if not pat_value:
            pat_value = os.getenv('CORTEX_AGENT_DEMO_PAT')
        if pat_value:
            st.session_state['cortex_pat'] = pat_value
            st.success("PAT configured from secrets")
        else:
            st.warning("PAT not found in secrets or env. Add to .streamlit/secrets.toml under [snowflake].password")
        # Thread management
        if pat_value and host_input:
            if 'cortex_thread_id' not in st.session_state or not st.session_state['cortex_thread_id']:
                tid = create_thread(pat_value, host_input)
                st.session_state['cortex_thread_id'] = tid
            colt1, colt2 = st.columns([1,1])
            with colt1:
                st.caption(f"Thread: {st.session_state.get('cortex_thread_id') or '—'}")
            with colt2:
                if st.button("Reset Thread", use_container_width=True):
                    st.session_state['cortex_thread_id'] = create_thread(pat_value, host_input)
                    st.toast("Thread reset.")
            # Expose last thread create debug info if no thread id
            if not st.session_state.get('cortex_thread_id'):
                with st.expander("Thread create debug", expanded=False):
                    st.write("status:", st.session_state.get('thread_create_last_status'))
                    st.code(st.session_state.get('thread_create_last_body') or '', language="json")
        with st.expander("Agent validation", expanded=False):
            if st.button("DESCRIBE AGENT", use_container_width=True):
                try:
                    cur = conn.cursor()
                    cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
                    cur.execute("USE SCHEMA PUBLIC")
                    cur.execute("DESCRIBE AGENT SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT")
                    rows = cur.fetchall()
                    cur.close()
                    st.json({"describe_agent": rows[:50]})
                except Exception as e:
                    st.error(f"Describe agent failed: {str(e)}")

    # Example questions (top) remain for first run only
    if st.session_state.get('show_examples', True):
        st.subheader("🤖 Example Questions - Powered by Cortex Agent")
        example_questions = [
            "Which test customers are exact matches?",
            "Show me customers with very close similarity scores",
            "What's the breakdown of match categories?",
            "Show me the top 5 matches for TEST_0FCD7224E341",
            "Give me the first 10 customers in the test entry table",
            "How many test customers have similarity above 95%?",
        ]
        cols = st.columns(2)
        for i, question in enumerate(example_questions):
            with cols[i % 2]:
                # Ensure stable, unique keys by including a prefix and index
                if st.button(question, key=f"exampleset1_{i}", use_container_width=True):
                    st.session_state['selected_prompt'] = question
                    st.session_state['show_examples'] = False

    # Dedicated results area
    if st.session_state.get('selected_prompt'):
        run_and_render(
            st.session_state['selected_prompt'],
            conn,
            use_sse,
            timeout_sec,
            pat_token=st.session_state.get('cortex_pat'),
            host_override=host_input or None,
            agent_name=agent_input or None,
            thread_id=st.session_state.get('cortex_thread_id'),
            # No explicit parent_message_id; call_agent will post into the thread when needed
        )
        st.session_state['selected_prompt'] = None

    render_results_area(conn)

    st.markdown("---")
    followup = st.text_input("Ask a question:", value="", placeholder="Type your question...")
    if st.button("Send", use_container_width=True):
        if followup.strip():
            # Set the prompt and rerun so results render above this input area
            st.session_state['selected_prompt'] = followup.strip()
            st.rerun()


if __name__ == "__main__":
    main()

