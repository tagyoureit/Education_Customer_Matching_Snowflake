"""
Chat View Page - AI-powered chatbot for customer matching
"""

import streamlit as st
import pandas as pd
import snowflake.connector
import os
import json
import requests
import time
import re
import uuid
from typing import Dict, List, Optional
import toml
import sys
import logging
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from shared_utils import recalculate_all_similarities as shared_recalculate_all_similarities, DEFAULT_THRESHOLDS
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
logger = logging.getLogger("chat_view_copy")

# Page configuration
st.set_page_config(
    page_title="Chat View",
    page_icon="💬",
    layout="wide"
)

# Constants
DEFAULT_THRESHOLDS = {
    'exact': 0.995,
    'very_close': 0.980,
    'somewhat_close': 0.920
}

SEMANTIC_MODEL_PATH = "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"

@st.cache_resource
def get_snowflake_connection():
    """Create Snowflake connection"""
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

def get_predefined_response(user_message: str) -> Optional[Dict]:
    """Get predefined responses for common questions"""
    message_lower = user_message.lower()
    
    if "exact match" in message_lower:
        return {
            "sql": """
            SELECT 
                t.SOURCE_PKEY as test_customer_id,
                t.NAME as test_customer_name,
                t.CUSTOMER_FULL_DETAIL,
                cmr.SIMILARITY_SCORE * 100 as similarity_percentage,
                cmr.VALID_ID as matched_valid_customer_id,
                cmr.VALID_CUSTOMER_FULL_DETAIL,
                cmr.MATCH_CATEGORY
            FROM TEST_MATCHES t
            JOIN CUSTOMER_MATCH_RESULTS cmr ON t.SOURCE_PKEY = cmr.TEST_ID
            WHERE cmr.MATCH_CATEGORY = 'EXACT'
            ORDER BY cmr.SIMILARITY_SCORE DESC
            """,
            "explanation": "Here are all the test customers that have exact matches:"
        }
    elif "very close" in message_lower:
        return {
            "sql": """
            SELECT 
                t.SOURCE_PKEY as test_customer_id,
                t.NAME as test_customer_name,
                t.CUSTOMER_FULL_DETAIL,
                cmr.SIMILARITY_SCORE * 100 as similarity_percentage,
                cmr.VALID_ID as matched_valid_customer_id,
                cmr.VALID_CUSTOMER_FULL_DETAIL,
                cmr.MATCH_CATEGORY
            FROM TEST_MATCHES t
            JOIN CUSTOMER_MATCH_RESULTS cmr ON t.SOURCE_PKEY = cmr.TEST_ID
            WHERE cmr.MATCH_CATEGORY = 'VERY_CLOSE'
            ORDER BY cmr.SIMILARITY_SCORE DESC
            """,
            "explanation": "Here are the test customers with very close matches:"
        }
    elif "95" in message_lower and "97" in message_lower:
        return {
            "sql": """
            SELECT 
                t.SOURCE_PKEY as test_customer_id,
                t.NAME as test_customer_name,
                t.CUSTOMER_FULL_DETAIL,
                cmr.SIMILARITY_SCORE * 100 as similarity_percentage,
                cmr.VALID_ID as matched_valid_customer_id,
                cmr.VALID_CUSTOMER_FULL_DETAIL,
                cmr.MATCH_CATEGORY
            FROM TEST_MATCHES t
            JOIN CUSTOMER_MATCH_RESULTS cmr ON t.SOURCE_PKEY = cmr.TEST_ID
            WHERE cmr.SIMILARITY_SCORE >= 0.95 AND cmr.SIMILARITY_SCORE <= 0.97
            ORDER BY cmr.SIMILARITY_SCORE DESC
            """,
            "explanation": "Here are test customers with similarity between 95-97%:"
        }
    elif "show me" in message_lower and "vs valid id" in message_lower:
        # Extract TEST_ID and Valid ID from the message
        import re
        test_match = re.search(r'TEST_[A-F0-9]+', user_message)
        valid_match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', user_message)
        
        if test_match and valid_match:
            test_id = test_match.group(0)
            valid_id = valid_match.group(0)
            return {
                "sql": f"""
                SELECT 
                    t.SOURCE_PKEY as test_customer_id,
                    t.NAME as test_customer_name,
                    t.CUSTOMER_FULL_DETAIL as test_details,
                    v.ID as valid_customer_id,
                    v.CUSTOMER_FULL_DETAIL as valid_details,
                    VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) * 100 as similarity_percentage,
                    CASE 
                        WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= 0.995 THEN 'EXACT'
                        WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= 0.980 THEN 'VERY_CLOSE'
                        WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= 0.920 THEN 'SOMEWHAT_CLOSE'
                        ELSE 'NOT_CLOSE'
                    END AS MATCH_CATEGORY
                FROM TEST_MATCHES t
                CROSS JOIN VALID_CUSTOMERS v
                WHERE t.SOURCE_PKEY = '{test_id}' 
                AND v.ID = '{valid_id}'
                """,
                "explanation": f"Detailed comparison between {test_id} and Valid ID {valid_id}:"
            }
        else:
            return {"response": "Please provide both TEST_ID and Valid ID in the format: 'show me TEST_123 vs Valid ID abc-def-123'"}
    
    elif "show me matches on" in message_lower or "show me matches for" in message_lower:
        # Extract school name from the message
        import re
        # Look for school name after "on" or "for"
        match = re.search(r'(?:on|for)\s+(.+?)(?:\s*$)', user_message, re.IGNORECASE)
        if match:
            school_name = match.group(1).strip()
            return {
                "sql": f"""
                SELECT 
                    t.SOURCE_PKEY as test_customer_id,
                    t.NAME as test_customer_name,
                    t.CUSTOMER_FULL_DETAIL,
                    cmr.SIMILARITY_SCORE * 100 as similarity_percentage,
                    cmr.VALID_ID as matched_valid_customer_id,
                    cmr.VALID_CUSTOMER_FULL_DETAIL,
                    cmr.MATCH_CATEGORY
                FROM TEST_MATCHES t
                JOIN CUSTOMER_MATCH_RESULTS cmr ON t.SOURCE_PKEY = cmr.TEST_ID
                WHERE UPPER(t.NAME) LIKE UPPER('%{school_name}%') 
                   OR UPPER(t.CUSTOMER_FULL_DETAIL) LIKE UPPER('%{school_name}%')
                ORDER BY cmr.SIMILARITY_SCORE DESC
                """,
                "explanation": f"Here are all matches for '{school_name}':"
            }
        else:
            return {"response": "Please specify the school name, e.g., 'show me matches on Oologah Upper Elem School'"}
    
    elif "top 5" in message_lower and "match" in message_lower:
        return {
            "response": "To show top 5 matches for a specific customer, please provide the source_pkey (customer ID). For example: 'Show me top 5 matches for TEST_001'"
        }
    elif "match categor" in message_lower:
        return {
            "sql": """
            SELECT 
                cmr.MATCH_CATEGORY,
                COUNT(*) as customer_count,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM CUSTOMER_MATCH_RESULTS), 2) as percentage
            FROM CUSTOMER_MATCH_RESULTS cmr
            GROUP BY cmr.MATCH_CATEGORY
            ORDER BY customer_count DESC
            """,
            "explanation": "Here's the breakdown of test customers by match category:"
        }
    elif "edit" in message_lower and ("record" in message_lower or "test_match" in message_lower or "customer" in message_lower):
        # Try to extract the record ID from the message
        import re
        match = re.search(r'TEST_[A-F0-9]+', user_message)
        if match:
            return {
                "response": "edit_specific_record",
                "action": "edit_record",
                "record_id": match.group(0)
            }
        else:
            return {
                "response": "I can help you edit a test_match record! Please specify the record ID or select a row from the query results above."
            }
    elif "why" in message_lower and ("different" in message_lower or "records" in message_lower):
        return {
            "response": "analyze_differences",
            "action": "show_ai_analysis"
        }
    
    return None

def call_cortex_agent(messages: List[Dict], _conn) -> Dict:
    """Call the MDM_MATCHING_AGENT via Cortex Agents REST API (agent-only flow)."""
    try:
        # Extract the latest user message
        user_message = ""
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                user_message = msg.get('content', [{}])[0].get('text', '')
                break
        
        if not user_message:
            return {"error": "No user message found"}
        
        # Resolve account host for REST API
        host = os.getenv('SNOWFLAKE_HOST')
        if not host:
            rest_obj = getattr(_conn, 'rest', None)
            if rest_obj is not None and hasattr(rest_obj, 'host') and rest_obj.host:
                host = rest_obj.host
        if not host:
            # Fall back to account param env and construct standard host
            account = os.getenv('SNOWFLAKE_ACCOUNT')
            if account:
                host = f"{account}.snowflakecomputing.com"
        if host:
            # Normalize host to avoid SSL hostname mismatch (replace '_' with '-')
            host = host.replace('https://', '').replace('http://', '').strip('/')
            if '_' in host:
                host = host.replace('_', '-')
        if not host:
            return {"error": "Unable to determine Snowflake host. Set SNOWFLAKE_HOST env var (e.g., xyz.snowflakecomputing.com)."}
        logger.info(f"Agent host resolved: {host}")
        
        # Get session auth token
        auth_token = None
        rest_obj = getattr(_conn, 'rest', None)
        if rest_obj is not None and hasattr(rest_obj, 'token') and rest_obj.token:
            auth_token = rest_obj.token
        if not auth_token:
            auth_token = getattr(_conn, '_auth_token', None)
        if not auth_token:
            return {"error": "Unable to obtain Snowflake session token for REST call."}
        
        api_url = f"https://{host}/api/v2/cortex/agent:run"
        logger.info(f"Calling Cortex Agent: {api_url}")
        
        # Build REST body with alternating messages; start with only the latest user message
        request_messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_message}]
            }
        ]

        request_body = {
            "model": "llama3.3-70b",
            "response_instruction": (
                "For any question involving data, you MUST use your tools: "
                "first use cortex_analyst_text_to_sql (Customer_Matching_Analyst) to generate SQL, then use sql_exec to execute it. "
                "Do not answer from general knowledge without querying the data. "
                "Return a concise textual answer and include SQL when appropriate."
            ),
            "experimental": {},
            "tools": [
                {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "Customer_Matching_Analyst"}},
                {"tool_spec": {"type": "sql_exec", "name": "sql_execution_tool"}},
                {"tool_spec": {"type": "generic", "name": "Update_Test_Record"}},
                {"tool_spec": {"type": "generic", "name": "Get_AI_Analysis"}},
                {"tool_spec": {"type": "data_to_chart", "name": "data_to_chart"}}
            ],
            "tool_resources": {
                "Customer_Matching_Analyst": {
                    "semantic_model_file": SEMANTIC_MODEL_PATH,
                    "execution_environment": {"type": "warehouse", "warehouse": "WAREHOUSE_L_G2", "query_timeout": 120}
                },
                "Get_AI_Analysis": {
                    "type": "procedure",
                    "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS",
                    "name": "GET_AI_ANALYSIS(VARCHAR, VARCHAR)",
                    "execution_environment": {"type": "warehouse", "warehouse": "WAREHOUSE_L_G2", "query_timeout": 300}
                },
                "Update_Test_Record": {
                    "type": "procedure",
                    "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD",
                    "name": "UPDATE_TEST_RECORD(VARCHAR, OBJECT)",
                    "execution_environment": {"type": "warehouse", "warehouse": "WAREHOUSE_L_G2", "query_timeout": 60}
                }
            },
            "tool_choice": {"type": "auto"},
            "messages": request_messages
        }
        headers = {
            "Authorization": f'Snowflake Token="{auth_token}"',
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }
        
        logger.info("Posting agent:run with SSE...")
        response = requests.post(api_url, json=request_body, headers=headers, timeout=300, stream=True)
        if response.status_code >= 400:
            logger.error(f"Agent REST error {response.status_code}: {response.text[:300]}")
            return {"error": f"Agent REST error {response.status_code}: {response.text}"}
        
        content_type = response.headers.get('Content-Type', '')
        logger.info(f"Agent response Content-Type: {content_type}")
        accumulated_text = []
        sql_tool_use = None
        sql_tool_use_id = None
        sql_statement = None
        analyst_sql_statement = None
        
        if 'text/event-stream' in content_type:
            sse_count = 0
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    event_obj = json.loads(payload)
                except Exception:
                    continue
                sse_count += 1
                if sse_count <= 5:
                    logger.info(f"SSE[{sse_count}]: {payload[:200]}")
                if isinstance(event_obj, dict) and 'delta' in event_obj:
                    for item in event_obj['delta'].get('content', []):
                        if item.get('type') == 'text' and item.get('text'):
                            accumulated_text.append(item['text'])
                        elif item.get('type') == 'tool_use':
                            tu = item.get('tool_use', {})
                            tool_type = tu.get('type')
                            tool_name = tu.get('name', '')
                            if tool_type == 'sql_exec' or 'sql_exec' in tool_name.lower() or 'sql_execution_tool' in tool_name:
                                sql_tool_use = item
                                sql_tool_use_id = tu.get('tool_use_id')
                                input_obj = tu.get('input', {})
                                sql_statement = input_obj.get('sql') or input_obj.get('statement')
                                break
                        elif item.get('type') == 'tool_results':
                            tr = item.get('tool_results', {})
                            if tr.get('type') == 'cortex_analyst_text_to_sql':
                                for c in tr.get('content', []):
                                    if c.get('type') == 'json' and isinstance(c.get('json'), dict):
                                        analyst_sql_statement = c['json'].get('sql') or analyst_sql_statement
                    if sql_tool_use is not None:
                        break
                elif isinstance(event_obj, dict) and 'message' in event_obj and 'content' in event_obj['message']:
                    parts = event_obj['message']['content']
                    texts = [p.get('text') for p in parts if p.get('type') == 'text' and p.get('text')]
                    if texts:
                        accumulated_text.append("\n\n".join(texts))
        else:
            try:
                data = response.json()
                if isinstance(data, dict):
                    if 'message' in data and isinstance(data['message'], dict) and 'content' in data['message']:
                        parts = data['message']['content']
                        texts = [p.get('text') for p in parts if p.get('type') == 'text' and p.get('text')]
                        if texts:
                            accumulated_text.append("\n\n".join(texts))
                    if 'delta' in data and isinstance(data['delta'], dict) and 'content' in data['delta']:
                        for item in data['delta'].get('content', []):
                            if item.get('type') == 'text' and item.get('text'):
                                accumulated_text.append(item['text'])
            except Exception:
                return {"error": f"Agent returned non-JSON response: {response.text[:500]}"}
        
        if sql_tool_use_id and sql_statement:
            try:
                cursor = _conn.cursor()
                cursor.execute(sql_statement)
                query_id = getattr(cursor, 'sfqid', None)
                cursor.close()
            except Exception as exec_err:
                return {"error": f"Failed to execute agent SQL: {str(exec_err)}"}

            answers_body = {
                "agent": "SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT",
                "model": "llama3.3-70b",
                "response_instruction": "Provide concise answers summarizing the results.",
                "experimental": {},
                "tool_choice": {"type": "auto"},
                "messages": [
                    {"role": "assistant", "content": [{"type": "tool_use", "tool_use": sql_tool_use.get('tool_use', {})}]},
                    {"role": "user", "content": [{"type": "tool_results", "tool_results": {"tool_use_id": sql_tool_use_id, "name": "sql_execution_tool", "content": [{"type": "json", "json": {"query_id": query_id}}], "status": "success"}}]}
                ]
            }
            headers_ans = {
                "Authorization": f'Snowflake Token="{auth_token}"',
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
            }
            logger.info("Posting agent answers follow-up with query_id...")
            resp2 = requests.post(api_url, json=answers_body, headers=headers_ans, timeout=300, stream=True)
            if resp2.status_code >= 400:
                logger.error(f"Agent answers error {resp2.status_code}: {resp2.text[:300]}")
                return {"error": f"Agent answers error {resp2.status_code}: {resp2.text}"}
            final_text = []
            if 'text/event-stream' in resp2.headers.get('Content-Type', ''):
                for raw_line in resp2.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith('data:'):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and 'delta' in obj:
                        for c in obj['delta'].get('content', []):
                            if c.get('type') == 'text' and c.get('text'):
                                final_text.append(c['text'])
                    elif isinstance(obj, dict) and 'message' in obj and 'content' in obj['message']:
                        parts = obj['message']['content']
                        texts = [p.get('text') for p in parts if p.get('type') == 'text' and p.get('text')]
                        if texts:
                            final_text.append("\n\n".join(texts))
            else:
                try:
                    obj = resp2.json()
                    if isinstance(obj, dict) and 'message' in obj and 'content' in obj['message']:
                        parts = obj['message']['content']
                        texts = [p.get('text') for p in parts if p.get('type') == 'text' and p.get('text')]
                        if texts:
                            final_text.append("\n\n".join(texts))
                except Exception:
                    pass
            if final_text:
                return {"response": "".join(final_text)}

        if accumulated_text:
            return {"response": "".join(accumulated_text)}
        
        if analyst_sql_statement and not sql_tool_use_id:
            try:
                df = pd.read_sql(analyst_sql_statement, _conn)
                if not df.empty:
                    preview = df.head(10).to_string(index=False)
                    return {"response": f"Results preview (first 10 rows) for:\n```sql\n{analyst_sql_statement}\n```\n\n{preview}"}
                else:
                    return {"response": f"No rows returned for:\n```sql\n{analyst_sql_statement}\n```"}
            except Exception as e:
                return {"error": f"Failed to execute Analyst SQL: {str(e)}"}
        return {"response": "Your request was sent to the agent. Awaiting textual output."}
            
    except Exception as e:
        return {"error": f"Error calling Cortex Agent: {str(e)}"}

def execute_sql_query(_conn, sql_query: str) -> pd.DataFrame:
    """Execute a SQL query and return results as DataFrame"""
    try:
        return pd.read_sql(sql_query, _conn)
    except Exception as e:
        st.error(f"Error executing query: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def load_test_matches(_conn) -> pd.DataFrame:
    """Load test matches for editing"""
    try:
        query = """
        SELECT SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1,
               ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY,
               CUSTOMER_FULL_DETAIL
        FROM TEST_MATCHES
        ORDER BY SOURCE_PKEY
        """
        return pd.read_sql(query, _conn)
    except Exception as e:
        st.error(f"Error loading test matches: {str(e)}")
        return pd.DataFrame()

def get_updated_top_matches(_conn, test_id: str, limit: int = 5, thresholds: Dict[str, float] = None) -> pd.DataFrame:
    """Get updated top matches after recalculation"""
    try:
        # Use provided thresholds or defaults
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()
            
        query_sql = """
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
        
        matches = pd.read_sql(query_sql, _conn, params=(thresholds['exact'], thresholds['very_close'], thresholds['somewhat_close'], test_id, limit))
        return matches
        
    except Exception as e:
        st.error(f"Error getting updated top matches: {str(e)}")
        return pd.DataFrame()

def get_top_matches(_conn, test_id: str, thresholds: Dict[str, float], limit: int = 5) -> pd.DataFrame:
    """Get top matches for a specific customer"""
    try:
        query_sql = """
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
        
        matches = pd.read_sql(query_sql, _conn, params=(
            thresholds['exact'], 
            thresholds['very_close'], 
            thresholds['somewhat_close'], 
            test_id, 
            limit
        ))
        
        return matches
        
    except Exception as e:
        st.error(f"Error getting top matches: {str(e)}")
        return pd.DataFrame()

def update_test_record_via_sql(_conn, record_id: str, updates: Dict) -> bool:
    """Update test record using SQL"""
    try:
        cursor = _conn.cursor()
        
        set_clauses = []
        params = []
        
        for field, value in updates.items():
            if field.upper() in ['NAME', 'SOURCE_SYSTEM', 'ADDRESS_LINE_1', 'ADDRESS_LINE_2', 
                                'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY']:
                set_clauses.append(f"{field.upper()} = %s")
                params.append(value)
        
        if not set_clauses:
            return False
        
        set_clauses.append("CUSTOMER_FULL_DETAIL = %s")
        
        cursor.execute("SELECT NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY FROM TEST_MATCHES WHERE SOURCE_PKEY = %s", (record_id,))
        current_record = cursor.fetchone()
        
        if current_record:
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
            
            embedding_sql = """
            UPDATE TEST_MATCHES 
            SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
            WHERE SOURCE_PKEY = %s
            """
            cursor.execute(embedding_sql, (record_id,))
            
            cursor.close()
            return True
        
        return False
        
    except Exception as e:
        st.error(f"Error updating record via SQL: {str(e)}")
        return False

def initialize_chat_session():
    """Initialize chat session state"""
    if 'chat_messages' not in st.session_state:
        st.session_state.chat_messages = []
    if 'thresholds' not in st.session_state:
        st.session_state.thresholds = DEFAULT_THRESHOLDS.copy()
    if 'current_query_results' not in st.session_state:
        st.session_state.current_query_results = None
    if 'current_query_info' not in st.session_state:
        st.session_state.current_query_info = None
    if 'selected_customer_for_analysis' not in st.session_state:
        st.session_state.selected_customer_for_analysis = None
    if 'current_ai_analysis' not in st.session_state:
        st.session_state.current_ai_analysis = None
    if 'edit_record_id' not in st.session_state:
        st.session_state.edit_record_id = None
    if 'last_selected_customer' not in st.session_state:
        st.session_state.last_selected_customer = None
    if 'updated_match_results' not in st.session_state:
        st.session_state.updated_match_results = None

def add_message_to_chat(role: str, content: str):
    """Add a message to the chat history"""
    st.session_state.chat_messages.append({
        "role": role,
        "content": [{"type": "text", "text": content}],
        "timestamp": time.time()
    })

def show_inline_edit_form(_conn):
    """Show an inline form for editing test customer records"""
    with st.expander("📝 Edit Test Customer Record", expanded=True):
        st.write("**Select a customer to edit:**")
        
        try:
            test_customers = load_test_matches(_conn)
            if not test_customers.empty:
                customer_options = {}
                for _, row in test_customers.iterrows():
                    display_name = f"{row['SOURCE_PKEY']} - {row['NAME']}"
                    customer_options[display_name] = row['SOURCE_PKEY']
                
                selected_display = st.selectbox(
                    "Choose customer:",
                    options=list(customer_options.keys()),
                    key="chat_customer_select"
                )
                
                if selected_display:
                    selected_id = customer_options[selected_display]
                    selected_record = test_customers[test_customers['SOURCE_PKEY'] == selected_id].iloc[0]
                    
                    with st.form("chat_edit_form"):
                        st.write(f"**Editing Customer: {selected_id}**")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            name = st.text_input("Name", value=selected_record['NAME'])
                            source_system = st.text_input("Source System", value=selected_record['SOURCE_SYSTEM'])
                            address1 = st.text_input("Address 1", value=selected_record['ADDRESS_LINE_1'] or '')
                            city = st.text_input("City", value=selected_record['CITY'] or '')
                        
                        with col2:
                            address2 = st.text_input("Address 2", value=selected_record['ADDRESS_LINE_2'] or '')
                            state = st.text_input("State", value=selected_record['STATE'] or '')
                            postal = st.text_input("Postal Code", value=selected_record['POSTAL_CODE'] or '')
                            country = st.text_input("Country", value=selected_record['COUNTRY'] or '')
                        
                        if st.form_submit_button("💾 Update Customer", use_container_width=True):
                            updates = {
                                'NAME': name,
                                'SOURCE_SYSTEM': source_system,
                                'ADDRESS_LINE_1': address1,
                                'ADDRESS_LINE_2': address2,
                                'CITY': city,
                                'STATE': state,
                                'POSTAL_CODE': postal,
                                'COUNTRY': country
                            }
                            
                            if update_test_record_via_sql(_conn, selected_id, updates):
                                st.success("✅ Customer updated successfully!")
                                add_message_to_chat("assistant", f"Successfully updated customer {selected_id}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("❌ Failed to update customer")
        except Exception as e:
            st.error(f"Error loading customers: {str(e)}")

def show_inline_edit_form_for_customer(_conn, source_pkey: str):
    """Show an inline form for editing a specific test customer record"""
    with st.expander(f"📝 Edit Customer: {source_pkey}", expanded=True):
        try:
            # Load the specific customer record
            cursor = _conn.cursor()
            query = """
            SELECT SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1,
                   ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY,
                   CUSTOMER_FULL_DETAIL
            FROM TEST_MATCHES
            WHERE SOURCE_PKEY = %s
            """
            cursor.execute(query, (source_pkey,))
            result = cursor.fetchone()
            cursor.close()
            
            if result:
                # Create record dict
                columns = ['SOURCE_PKEY', 'NAME', 'SOURCE_SYSTEM', 'ADDRESS_LINE_1',
                          'ADDRESS_LINE_2', 'CITY', 'STATE', 'POSTAL_CODE', 'COUNTRY', 'CUSTOMER_FULL_DETAIL']
                record = dict(zip(columns, result))
                
                with st.form(f"chat_edit_form_{source_pkey}"):
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
                            'COUNTRY': country
                        }
                        
                        if update_test_record_via_sql(_conn, source_pkey, updates):
                            st.success("✅ Customer updated successfully!")
                            # Clear cache BEFORE recalculating to ensure fresh data
                            st.cache_data.clear()
                            # Recalculate similarities
                            recalc_success = recalculate_all_similarities(_conn, st.session_state.thresholds)
                            if recalc_success:
                                st.success("✅ Similarities recalculated!")
                                
                                # Store updated matches in session state for display outside expander
                                updated_matches = get_updated_top_matches(_conn, source_pkey, 5, st.session_state.thresholds)
                                if not updated_matches.empty:
                                    st.session_state.updated_match_results = {
                                        'source_pkey': source_pkey,
                                        'matches': updated_matches
                                    }
                                    st.success("🔄 New similarity scores will be displayed below!")
                                
                            add_message_to_chat("assistant", f"Successfully updated customer {source_pkey} and recalculated similarities. New similarity scores are displayed below.")
                            # Clear cache again after recalculation to ensure all data is fresh
                            st.cache_data.clear()
                            # Note: Form will handle the rerun automatically
                        else:
                            st.error("❌ Failed to update customer")
            else:
                st.error(f"Customer {source_pkey} not found")
                
        except Exception as e:
            st.error(f"Error loading customer {source_pkey}: {str(e)}")

def get_ai_analysis(_conn, test_id: str, valid_id: str) -> str:
    """Get AI analysis of differences between test and valid customer records"""
    try:
        cursor = _conn.cursor()
        
        analysis_sql = """
        SELECT 
            AI_COMPLETE('llama3.3-70b',
                'Compare these customer records. Return ONLY properly formatted markdown with no extra text. Format exactly like this:
                
**Key Differences:**
- **Address Line 1**: 623 vs 620 (street number difference)
- **Postal Code**: 24972 vs 24983 (different postal codes)

**Summary:**
High similarity due to matching name and city, minor address variations explain the score.

Test Customer: ' ||
                OBJECT_CONSTRUCT(
                  'name', i.NAME,
                  'address_line_1', i.ADDRESS_LINE_1,
                  'address_line_2', i.ADDRESS_LINE_2,
                  'city', i.CITY,
                  'state', i.STATE,
                  'postal_code', i.POSTAL_CODE,
                  'country', i.COUNTRY
                )::string
                || ' Valid Customer: ' ||
                OBJECT_CONSTRUCT(
                  'name', v.NAME,
                  'address_line_1', v.ADDRESS_LINE_1,
                  'address_line_2', v.ADDRESS_LINE_2,
                  'city', v.CITY,
                  'state', v.STATE,
                  'postal_code', v.POSTAL_CODE,
                  'country', v.COUNTRY
                )::string
            ) AS ANALYSIS
        FROM MDM_CUSTOMER_MATCHING.public.VALID_CUSTOMERS v,
             MDM_CUSTOMER_MATCHING.public.TEST_MATCHES i 
        WHERE i.SOURCE_PKEY = %s
        AND v.ID = %s
        """
        
        cursor.execute(analysis_sql, (test_id, valid_id))
        result = cursor.fetchone()
        
        if result and result[0]:
            ai_response = result[0]
            
            if "Key Differences:" in ai_response:
                start_idx = ai_response.find("**Key Differences:**")
                if start_idx != -1:
                    ai_response = ai_response[start_idx:]
            
            ai_response = ai_response.replace("\\n", "\n")
            ai_response = ai_response.replace('\\"', '"')
            ai_response = ai_response.replace("**Key Differences:**", "**Key Differences:**\n")
            ai_response = ai_response.replace("**Summary:**", "\n**Summary:**\n")
            
            return ai_response
        else:
            return "AI analysis not available for this comparison."
            
    except Exception as e:
        return f"Error getting AI analysis: {str(e)}"

# Use the shared function instead of duplicating code
def recalculate_all_similarities(_conn, thresholds: Dict[str, float] = None) -> bool:
    """Wrapper to use shared recalculation function"""
    return shared_recalculate_all_similarities(_conn, thresholds)

def show_inline_top_matches(content: str, _conn):
    """Show top matches inline based on the chat content"""
    patterns = [
        r'TEST_\w+',
        r'source_pkey\s*=\s*(\w+)',
        r'customer\s*(\w+)',
        r'id\s*(\w+)'
    ]
    
    customer_id = None
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            customer_id = matches[0] if isinstance(matches[0], str) else matches[0]
            break
    
    if customer_id:
        with st.expander(f"🎯 Top 5 Matches for {customer_id}", expanded=True):
            try:
                top_matches = get_top_matches(_conn, customer_id, st.session_state.thresholds)
                
                if not top_matches.empty:
                    for idx, match in top_matches.iterrows():
                        similarity_pct = match['SIMILARITY_SCORE'] * 100
                        match_category = match['MATCH_CATEGORY']
                        
                        if match_category == 'EXACT':
                            color = "🟢"
                        elif match_category == 'VERY_CLOSE':
                            color = "🟡"
                        elif match_category == 'SOMEWHAT_CLOSE':
                            color = "🟠"
                        else:
                            color = "🔴"
                        
                        st.write(f"{color} **{similarity_pct:.2f}%** ({match_category})")
                        st.write(f"   Valid ID: {match['VALID_ID']}")
                        st.write(f"   Details: {match['VALID_CUSTOMER_FULL_DETAIL']}")
                        st.write("---")
                else:
                    st.warning(f"No matches found for customer {customer_id}")
            except Exception as e:
                st.error(f"Error getting matches: {str(e)}")
    else:
        st.info("💡 To see top matches, please specify a customer ID (e.g., 'Show top matches for TEST_001')")

def display_chat_message(message: Dict, _conn):
    """Display a chat message with appropriate styling"""
    role = message.get('role', 'user')
    content = message.get('content', [{}])[0].get('text', '')
    
    if role == 'user':
        with st.chat_message("user"):
            st.write(content)
    elif role == 'assistant':
        with st.chat_message("assistant"):
            st.write(content)
            
            # Check if this is a response that needs special handling
            if "edit" in content.lower() and "test_match" in content.lower():
                show_inline_edit_form(_conn)
            elif ("top 5" in content.lower() or "top matches" in content.lower()) and any(word in content.upper() for word in ["TEST_", "SOURCE_PKEY"]):
                show_inline_top_matches(content, _conn)

def process_chat_input(user_input: str, _conn) -> str:
    """Process user input and generate response"""
    try:
        add_message_to_chat("user", user_input)
        
        messages = st.session_state.chat_messages.copy()
        
        response = call_cortex_agent(messages, _conn)
        
        if "error" in response:
            error_msg = f"Sorry, I encountered an error: {response['error']}"
            add_message_to_chat("assistant", error_msg)
            return error_msg
        
        if "sql" in response:
            sql_query = response["sql"]
            explanation = response.get("explanation", "Here are the results:")
            
            results = execute_sql_query(_conn, sql_query)
            
            if not results.empty:
                response_text = f"{explanation}\n\nI found {len(results)} records. Here's the SQL I used:\n```sql\n{sql_query}\n```"
                add_message_to_chat("assistant", response_text)
                
                # Prepare display dataframe with the requested columns
                display_df = results.copy()
                
                # Ensure we have the key columns for display - map common column names
                column_mapping = {
                    'test_customer_id': 'SOURCE_PKEY',
                    'TEST_ID': 'SOURCE_PKEY', 
                    'test_customer_name': 'TEST_CUSTOMER_NAME',
                    'matched_valid_customer_id': 'VALID_ID',
                    'matched_customer_details': 'VALID_CUSTOMER_FULL_DETAIL',
                    'similarity_percentage': 'SIMILARITY_PERCENTAGE'
                }
                
                # Debug: Check what columns we actually have (commented out to prevent loops)
                # st.write("**Debug - Available columns:**", list(display_df.columns))
                
                # Rename columns to standardized names
                for old_name, new_name in column_mapping.items():
                    if old_name in display_df.columns:
                        display_df = display_df.rename(columns={old_name: new_name})
                
                # Select and reorder key columns for display
                display_columns = []
                available_columns = display_df.columns.tolist()
                
                # Add columns in preferred order if they exist
                preferred_order = ['SOURCE_PKEY', 'TEST_CUSTOMER_NAME', 'CUSTOMER_FULL_DETAIL', 
                                 'SIMILARITY_PERCENTAGE', 'VALID_ID', 'VALID_CUSTOMER_FULL_DETAIL', 'MATCH_CATEGORY']
                
                for col in preferred_order:
                    if col in available_columns:
                        display_columns.append(col)
                
                # Add any remaining columns
                for col in available_columns:
                    if col not in display_columns:
                        display_columns.append(col)
                
                # Create final display dataframe
                final_display_df = display_df[display_columns] if display_columns else display_df
                
                # Store results in session state for persistent display
                st.session_state.current_query_results = final_display_df
                st.session_state.current_query_info = {
                    'explanation': explanation,
                    'sql': sql_query,
                    'record_count': len(results)
                }
                
                return response_text
            else:
                response_text = "No results found for your query."
                add_message_to_chat("assistant", response_text)
                st.session_state.current_query_results = None
                st.session_state.current_query_info = None
                return response_text
        else:
            response_text = response.get("response", "I couldn't generate a proper response.")
            
            # Handle special actions
            if response.get("action") == "edit_record":
                record_id = response.get("record_id")
                if record_id:
                    # Store the record ID for editing
                    st.session_state.edit_record_id = record_id
                    edit_response = f"Opening edit form for {record_id}..."
                    add_message_to_chat("assistant", edit_response)
                    return edit_response
                else:
                    error_msg = "Could not find record ID to edit."
                    add_message_to_chat("assistant", error_msg)
                    return error_msg
            elif response.get("action") == "show_ai_analysis":
                if hasattr(st.session_state, 'selected_customer_for_analysis') and st.session_state.selected_customer_for_analysis:
                    selected_info = st.session_state.selected_customer_for_analysis
                    source_pkey = selected_info.get('source_pkey')
                    valid_id = selected_info.get('valid_id')
                    
                    if source_pkey and valid_id:
                        ai_analysis = get_ai_analysis(_conn, source_pkey, valid_id)
                        analysis_response = f"🤖 **AI Analysis for {source_pkey} vs Valid ID {valid_id}**\n\n{ai_analysis}"
                        add_message_to_chat("assistant", analysis_response)
                        
                        # Store analysis for display outside the form
                        st.session_state.current_ai_analysis = {
                            'source_pkey': source_pkey,
                            'valid_id': valid_id,
                            'analysis': ai_analysis
                        }
                        
                        return analysis_response
                    else:
                        error_msg = f"Missing customer IDs for analysis. Source: {source_pkey}, Valid: {valid_id}. Please select a row first."
                        add_message_to_chat("assistant", error_msg)
                        return error_msg
                else:
                    error_msg = "Please select a customer row first, then ask 'Why are these records different?'"
                    add_message_to_chat("assistant", error_msg)
                    return error_msg
            
            add_message_to_chat("assistant", response_text)
            return response_text
            
    except Exception as e:
        error_msg = f"Error processing your request: {str(e)}"
        add_message_to_chat("assistant", error_msg)
        return error_msg

def main():
    st.title("💬 Customer Matching Assistant")
    st.markdown("Ask questions about your customer data in natural language!")
    
    # Initialize chat session
    initialize_chat_session()
    
    # Get Snowflake connection
    conn = get_snowflake_connection()
    
    # Chat interface
    st.subheader("Chat")
    
    # Display chat history
    chat_container = st.container()
    with chat_container:
        for message in st.session_state.chat_messages:
            display_chat_message(message, conn)
    
    # Display persistent query results if available
    if st.session_state.current_query_results is not None:
        col_title, col_clear = st.columns([3, 1])
        with col_title:
            st.subheader("📊 Query Results")
        with col_clear:
            if st.button("🗑️ Clear Results", key="clear_results"):
                st.session_state.current_query_results = None
                st.session_state.current_query_info = None
                st.rerun()
        
        # Display interactive table with selection
        selected_rows = st.dataframe(
            st.session_state.current_query_results,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            height=400
        )
        
        # Handle row selection for editing
        if selected_rows['selection']['rows']:
            selected_idx = selected_rows['selection']['rows'][0]
            selected_record = st.session_state.current_query_results.iloc[selected_idx]
            
            # Extract SOURCE_PKEY and VALID_ID for editing and analysis
            source_pkey = None
            valid_id = None
            
            # Debug: Show what's in the selected record (commented out to prevent loops)
            # st.write("**Debug - Selected record:**", selected_record.to_dict())
            
            # Try multiple column names for SOURCE_PKEY
            for col in ['SOURCE_PKEY', 'test_customer_id', 'TEST_CUSTOMER_ID', 'TEST_ID']:
                if col in selected_record and selected_record[col]:
                    source_pkey = selected_record[col]
                    break
            
            # Try multiple column names for VALID_ID  
            for col in ['VALID_ID', 'matched_valid_customer_id', 'MATCHED_VALID_CUSTOMER_ID']:
                if col in selected_record and selected_record[col]:
                    valid_id = selected_record[col]
                    break
            
            # If we still don't have source_pkey, try to extract from customer details
            if not source_pkey and 'CUSTOMER_FULL_DETAIL' in selected_record:
                customer_detail = selected_record['CUSTOMER_FULL_DETAIL']
                # Try to find TEST_XXXXXX pattern in the detail
                import re
                match = re.search(r'TEST_[A-F0-9]+', str(customer_detail))
                if match:
                    source_pkey = match.group(0)
            
            if source_pkey:
                # Store selected customer info in session state for analysis
                st.session_state.selected_customer_for_analysis = {
                    'source_pkey': source_pkey,
                    'valid_id': valid_id,
                    'record': selected_record.to_dict()
                }
                
                st.info(f"🎯 Selected customer: {source_pkey} (Valid ID: {valid_id})")
                
                # Only add message if this is a new selection
                if 'last_selected_customer' not in st.session_state or st.session_state.last_selected_customer != source_pkey:
                    add_message_to_chat("assistant", f"You selected customer {source_pkey}. You can now ask 'Why are these records different?' or I can show the edit form.")
                    st.session_state.last_selected_customer = source_pkey
                
                # Show edit form for selected customer (without auto-rerun)
                show_inline_edit_form_for_customer(conn, source_pkey)
    
    # Debug info (temporary)
    with st.expander("🔧 Debug Info", expanded=False):
        st.write("**Selected Customer for Analysis:**")
        st.write(st.session_state.selected_customer_for_analysis)
        st.write("**Current AI Analysis:**")
        st.write(st.session_state.current_ai_analysis)
    
    # Display AI Analysis if available
    if st.session_state.current_ai_analysis is not None:
        analysis_data = st.session_state.current_ai_analysis
        
        col_title, col_clear = st.columns([3, 1])
        with col_title:
            st.subheader(f"🤖 AI Analysis: {analysis_data['source_pkey']} vs Valid ID {analysis_data['valid_id']}")
        with col_clear:
            if st.button("🗑️ Clear Analysis", key="clear_analysis"):
                st.session_state.current_ai_analysis = None
                st.rerun()
        
        with st.expander("📊 Record Comparison Analysis", expanded=True):
            st.markdown(analysis_data['analysis'])
    
    # Display Edit Form if requested via chat
    if st.session_state.edit_record_id is not None:
        record_id = st.session_state.edit_record_id
        
        col_title, col_clear = st.columns([3, 1])
        with col_title:
            st.subheader(f"✏️ Edit Customer: {record_id}")
        with col_clear:
            if st.button("❌ Cancel Edit", key="cancel_edit"):
                st.session_state.edit_record_id = None
                st.rerun()
        
        # Show edit form for the requested customer
        show_inline_edit_form_for_customer(conn, record_id)
    
    # Display Updated Match Results if available (outside of any expanders)
    if st.session_state.updated_match_results is not None:
        results_data = st.session_state.updated_match_results
        
        col_title, col_clear = st.columns([3, 1])
        with col_title:
            st.subheader(f"🔄 Updated Match Results for {results_data['source_pkey']}")
        with col_clear:
            if st.button("🗑️ Clear Results", key="clear_updated_results"):
                st.session_state.updated_match_results = None
                st.rerun()
        
        st.write("**New Top 5 Similarity Scores:**")
        for idx, match in results_data['matches'].iterrows():
            similarity_pct = match['SIMILARITY_SCORE'] * 100
            match_category = match['MATCH_CATEGORY']
            
            if match_category == 'EXACT':
                color = "🟢"
            elif match_category == 'VERY_CLOSE':
                color = "🟡"
            elif match_category == 'SOMEWHAT_CLOSE':
                color = "🟠"
            else:
                color = "🔴"
            
            st.write(f"{color} **{similarity_pct:.4f}%** ({match_category}) - {match['VALID_CUSTOMER_FULL_DETAIL']}")
        
        st.write("---")  # Separator
    
    # Chat input
    with st.form("chat_form", clear_on_submit=True):
        col_input, col_button = st.columns([4, 1])
        with col_input:
            user_input = st.text_input(
                "Ask a question...", 
                placeholder="e.g., Which test customers are exact matches?",
                label_visibility="collapsed"
            )
        with col_button:
            send_button = st.form_submit_button("Send", use_container_width=True)
        
        if send_button and user_input.strip():
            with st.spinner("Thinking..."):
                response = process_chat_input(user_input.strip(), conn)
            st.rerun()
    
    # Example questions
    st.subheader("💡 Example Questions")
    example_questions = [
        "Which test customers are exact matches?",
        "Which test customers match between 95-97%?", 
        "Which test customers are a very close match?",
        "Show me the test_match with source_pkey = TEST_001 and the top 5 valid matches",
        "Why are these records different?",
        "How many test customers are in each match category?"
    ]
    
    cols = st.columns(2)
    for i, question in enumerate(example_questions):
        with cols[i % 2]:
            if st.button(question, key=f"example_{i}", use_container_width=True):
                with st.spinner("Thinking..."):
                    response = process_chat_input(question, conn)
                st.rerun()
    
    # Chat controls
    st.subheader("🔧 Chat Controls")
    col_clear, col_export = st.columns([1, 1])
    with col_clear:
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()
    with col_export:
        if st.button("📥 Export Chat", use_container_width=True):
            chat_data = {
                "timestamp": time.time(),
                "messages": st.session_state.chat_messages
            }
            st.download_button(
                "Download Chat History",
                data=json.dumps(chat_data, indent=2),
                file_name=f"chat_history_{int(time.time())}.json",
                mime="application/json"
            )

if __name__ == "__main__":
    main()