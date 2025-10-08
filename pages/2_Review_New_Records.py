"""
Review New Records Page - Scaffold
- Two columns: Left (Customer Address - read-only), Right (Customer Identifier - read-only)
- Placeholder buttons (Previous, Assign, Create New ID, Next)
- No database calls yet; wiring will be added in subsequent steps
"""

import streamlit as st
import os
from shared_utils import connect_to_snowflake
import json
 

# Page configuration
st.set_page_config(
    page_title="Review New Records",
    page_icon="🗂️",
    layout="wide",
)

custom_css = """
<style>
    .custom {
        -webkit-text-fill-color: red; /* Set the text color for webkit browsers */
        color: red; /* Set the text color for other browsers */
    }
</style>
"""

# Inject the CSS into the app
st.markdown(custom_css, unsafe_allow_html=True)

@st.cache_resource
def get_snowflake_connection():
    return connect_to_snowflake()

 


def get_top3_candidates_for_ci(_conn, ci_row: dict):
    """Fetch top-3 CUSTOMER_ADDRESS candidates via Cortex SEARCH_PREVIEW using CI.CUSTOMER_FULL_DETAIL.

    Returns a list of dicts with uppercase keys and an optional _SCORE field. Sorted by score desc.
    Reference: @Snowflake Docs
    """
    try:
        if _conn is None or not ci_row or not ci_row.get('CUSTOMER_FULL_DETAIL'):
            return []
        cur = _conn.cursor()

        # Build query from the canonical full-detail text
        query_str = (ci_row.get('CUSTOMER_FULL_DETAIL') or '').strip()

        payload = {
            "query": query_str,
            "columns": [
                "customer_full_detail",
                "customer_business_id",
                "customer_name",
                "address_line_1",
                "address_line_2",
                "city",
                "county",
                "state",
                "postal_code",
                "postalcode_extension",
                "country"
            ],
            "limit": 3
        }
        payload_str = json.dumps(payload)
        # Embed JSON as SQL single-quoted string (escape single quotes)
        payload_sql_literal = payload_str.replace("'", "''")

        sql = (
            "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(\n"
            "  'MDM_CUSTOMER_ADDRESS_SEARCH',\n"
            f"  '{payload_sql_literal}'\n"
            ")) AS RESULT"
        )
        cur.execute(sql)
        row = cur.fetchone()
        cur.close()
        if not row:
            return []

        result = row[0]
        try:
            if isinstance(result, str):
                result = json.loads(result)
        except Exception:
            result = None

        # Normalize to a list of result items
        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            # Common container keys
            for key in [
                'results', 'matches', 'data', 'documents', 'rows', 'items'
            ]:
                if isinstance(result.get(key), list):
                    items = result.get(key)
                    break
            if not items:
                # Some shapes wrap list under "result" or similar
                inner = result.get('result')
                if isinstance(inner, list):
                    items = inner

        candidates = []
        for item in items:
            doc = item
            if isinstance(item, dict) and isinstance(item.get('document'), dict):
                doc = item['document']
            score_val = None
            if isinstance(item, dict):
                # Prefer the same metric as shared utilities: @scores.cosine_similarity
                scores_block = item.get('@scores') or item.get('scores')
                if isinstance(scores_block, dict) and scores_block.get('cosine_similarity') is not None:
                    score_val = scores_block.get('cosine_similarity')
                if score_val is None:
                    score_val = item.get('score') if 'score' in item else item.get('similarity')
            cand = {
                'CUSTOMER_BUSINESS_ID': (doc.get('customer_business_id') if isinstance(doc, dict) else '') or '',
                'CUSTOMER_NAME': (doc.get('customer_name') if isinstance(doc, dict) else '') or '',
                'ADDRESS_LINE_1': (doc.get('address_line_1') if isinstance(doc, dict) else '') or '',
                'ADDRESS_LINE_2': (doc.get('address_line_2') if isinstance(doc, dict) else '') or '',
                'CITY': (doc.get('city') if isinstance(doc, dict) else '') or '',
                'COUNTY': (doc.get('county') if isinstance(doc, dict) else '') or '',
                'STATE': (doc.get('state') if isinstance(doc, dict) else '') or '',
                'POSTAL_CODE': (doc.get('postal_code') if isinstance(doc, dict) else '') or '',
                'POSTALCODE_EXTENSION': (doc.get('postalcode_extension') if isinstance(doc, dict) else '') or '',
                'COUNTRY': (doc.get('country') if isinstance(doc, dict) else '') or '',
                'PHONE': (doc.get('phone') if isinstance(doc, dict) else '') or '',
                '_SCORE': float(score_val) if score_val is not None else None,
            }
            candidates.append(cand)

        candidates.sort(key=lambda x: (x.get('_SCORE') is not None, x.get('_SCORE') or 0.0), reverse=True)
        return candidates
    except Exception:
        return []


def get_unassigned_ci_keys(_conn):
    """Return a list of (IDENTIFIER_TYPE, IDENTIFIER_VALUE) for unassigned CI rows ordered by CREATED_TIMESTAMP DESC."""
    try:
        if _conn is None:
            return []
        cur = _conn.cursor()
        cur = _conn.cursor()
        rows = []
        cur.execute(
            """
            SELECT IDENTIFIER_TYPE, IDENTIFIER_VALUE
            FROM CUSTOMER_IDENTIFIER
            WHERE CUSTOMER_BUSINESS_ID IS NULL
            ORDER BY CREATED_TIMESTAMP DESC
            """
        )
        fetched = cur.fetchall() or []
        for r in fetched:
            rows.append((r[0], r[1]))
        cur.close()
        return rows
    except Exception:
        return []


def get_ci_by_key(_conn, identifier_type: str, identifier_value: str):
    """Fetch a CI row by IDENTIFIER_TYPE and IDENTIFIER_VALUE."""
    try:
        if _conn is None or not identifier_type or not identifier_value:
            return None
        cur = _conn.cursor()
        cur = _conn.cursor()
        cur.execute(
            """
            SELECT 
                IDENTIFIER_TYPE,
                IDENTIFIER_VALUE,
                CUSTOMER_NAME,
                ADDRESS_LINE_1,
                ADDRESS_LINE_2,
                CITY,
                COUNTY,
                STATE,
                POSTAL_CODE,
                POSTALCODE_EXTENSION,
                COUNTRY,
                PHONE,
                CUSTOMER_FULL_DETAIL,
                CREATED_TIMESTAMP
            FROM CUSTOMER_IDENTIFIER
            WHERE IDENTIFIER_TYPE = %s AND IDENTIFIER_VALUE = %s
            LIMIT 1
            """,
            (identifier_type, identifier_value)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        columns = [
            'IDENTIFIER_TYPE', 'IDENTIFIER_VALUE', 'CUSTOMER_NAME', 'ADDRESS_LINE_1',
            'ADDRESS_LINE_2', 'CITY', 'COUNTY', 'STATE', 'POSTAL_CODE',
            'POSTALCODE_EXTENSION', 'COUNTRY', 'PHONE', 'CUSTOMER_FULL_DETAIL',
            'CREATED_TIMESTAMP'
        ]
        return dict(zip(columns, row))
    except Exception:
        return None

def assign_ci_to_business_id(_conn, identifier_type: str, identifier_value: str, customer_business_id: str) -> bool:
    """Assign CI row to the given CUSTOMER_BUSINESS_ID, recompute confidence and enriched indicator, and populate verification message for that row.

    Reference: @Snowflake Docs for VECTOR_COSINE_SIMILARITY and AI_COMPLETE.
    """
    try:
        if _conn is None or not identifier_type or not identifier_value or not customer_business_id:
            return False
        cur = _conn.cursor()
        # Context
        cur = _conn.cursor()

        # 1) Assign BUSINESS ID
        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
            SET CUSTOMER_BUSINESS_ID = %s
            WHERE IDENTIFIER_TYPE = %s AND IDENTIFIER_VALUE = %s
            """,
            (customer_business_id, identifier_type, identifier_value)
        )

        # 2) Recompute vector cosine similarity for this CI row
        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
            SET CONFIDENCE_SCORE = VECTOR_COSINE_SIMILARITY(ca.CUSTOMER_FULL_DETAIL_EMBEDDING, ci.CUSTOMER_FULL_DETAIL_EMBEDDING)
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
              AND ci.IDENTIFIER_TYPE = %s AND ci.IDENTIFIER_VALUE = %s
            """,
            (identifier_type, identifier_value)
        )

        # 3) Compute EDIT_DISTANCE for this CI row
        try:
            cur.execute(
                """
                UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
                SET EDIT_DISTANCE = EDITDISTANCE(ci.CUSTOMER_FULL_DETAIL, ca.CUSTOMER_FULL_DETAIL)
                FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
                WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
                  AND ci.IDENTIFIER_TYPE = %s AND ci.IDENTIFIER_VALUE = %s
                """,
                (identifier_type, identifier_value)
            )
        except Exception:
            pass

        # 4) Populate verification message for this specific row
        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
            SET VERIFICATION_MESSAGE =
              CASE
                WHEN ci.CONFIDENCE_SCORE = 1 THEN
                  OBJECT_CONSTRUCT(
                    'reason','Identical match',
                    'name',TRUE,'address_line_1',TRUE,'address_line_2',TRUE,
                    'city',TRUE,'county',TRUE,'state',TRUE,'postal_code',TRUE,
                    'postalcode_extension',TRUE,'country',TRUE,'phone',TRUE
                  )
                ELSE
                  PARSE_JSON(
                    AI_COMPLETE(
                      'mistral-large2',
                      CONCAT_WS(
                        '',
                        'You are given two customer records (A and B). Compare the fields case-insensitively, trimming whitespace and treating NULL as empty. ',
                        'Return a JSON object matching the exact schema with booleans set to TRUE when the fields MATCH and FALSE when they DO NOT MATCH. ',
                        'If all fields match, set reason to "Identical match". ',
                        'Fields: name, address_line_1, address_line_2, city, county, state, postal_code, postalcode_extension, country, phone. ',
                        'Record A => ',
                        'Name: ', NVL(ci.CUSTOMER_NAME,''), '; ',
                        'Address Line 1: ', NVL(ci.ADDRESS_LINE_1,''), '; ',
                        'Address Line 2: ', NVL(ci.ADDRESS_LINE_2,''), '; ',
                        'City: ', NVL(ci.CITY,''), '; ',
                        'County: ', NVL(ci.COUNTY,''), '; ',
                        'State: ', NVL(ci.STATE,''), '; ',
                        'Postal Code: ', NVL(ci.POSTAL_CODE,''), '; ',
                        'PostalCode Extension: ', NVL(ci.POSTALCODE_EXTENSION,''), '; ',
                        'Country: ', NVL(ci.COUNTRY,''), '; ',
                        'Phone: ', NVL(ci.PHONE,''),
                        '. Record B => ',
                        'Name: ', NVL(ca.CUSTOMER_NAME,''), '; ',
                        'Address Line 1: ', NVL(ca.ADDRESS_LINE_1,''), '; ',
                        'Address Line 2: ', NVL(ca.ADDRESS_LINE_2,''), '; ',
                        'City: ', NVL(ca.CITY,''), '; ',
                        'County: ', NVL(ca.COUNTY,''), '; ',
                        'State: ', NVL(ca.STATE,''), '; ',
                        'Postal Code: ', NVL(ca.POSTAL_CODE,''), '; ',
                        'PostalCode Extension: ', NVL(ca.POSTALCODE_EXTENSION,''), '; ',
                        'Country: ', NVL(ca.COUNTRY,''), '; ',
                        'Phone: ', NVL(ca.PHONE,''),
                        '.'
                      ),
                      { 'temperature': 0, 'max_tokens': 512 },
                      {
                        'type': 'json',
                        'schema': {
                          'type': 'object',
                          'properties': {
                            'reason': { 'type': 'string' },
                            'name': { 'type': 'boolean' },
                            'address_line_1': { 'type': 'boolean' },
                            'address_line_2': { 'type': 'boolean' },
                            'city': { 'type': 'boolean' },
                            'county': { 'type': 'boolean' },
                            'state': { 'type': 'boolean' },
                            'postal_code': { 'type': 'boolean' },
                            'postalcode_extension': { 'type': 'boolean' },
                            'country': { 'type': 'boolean' },
                            'phone': { 'type': 'boolean' }
                          },
                          'required': ['reason','name','address_line_1','address_line_2','city','county','state','postal_code','postalcode_extension','country','phone']
                        }
                      }
                    )
                  )
              END
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
              AND ci.IDENTIFIER_TYPE = %s AND ci.IDENTIFIER_VALUE = %s
            """,
            (identifier_type, identifier_value)
        )

        cur.close()
        return True
    except Exception:
        return False


def create_new_id_and_assign(_conn, ci_row: dict):
    """Create a new CUSTOMER_ADDRESS from CI fields, generate a new ID, assign to CI, recompute fields, and populate verification message.
    """
    try:
        if _conn is None or not ci_row:
            return False, "Missing connection or CI row"
        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        try:
            cur.execute("USE WAREHOUSE COMPUTE_WH")
        except Exception:
            pass

        # Generate a new id in-app and reuse across statements
        cur.execute(
            "SELECT GENERATE_CUSTOMER_BUSINESS_ID(CUSTOMER_BUSINESS_ID_SEQ.NEXTVAL)"
        )
        row_id = cur.fetchone()
        if not row_id or not row_id[0]:
            cur.close()
            return False, "Failed to generate CUSTOMER_BUSINESS_ID"
        new_id = row_id[0]

        # Build CUSTOMER_FULL_DETAIL as "NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE"
        computed_detail = ", ".join([
            str(ci_row.get('CUSTOMER_NAME') or '').strip(),
            str(ci_row.get('ADDRESS_LINE_1') or '').strip(),
            str(ci_row.get('ADDRESS_LINE_2') or '').strip(),
            str(ci_row.get('CITY') or '').strip(),
            str(ci_row.get('STATE') or '').strip(),
            str(ci_row.get('POSTAL_CODE') or '').strip(),
        ]).strip(', ').strip()

        # Insert new address row from CI, attempting to set CUSTOMER_FULL_DETAIL at insert time
        inserted_with_detail = False
        try:
            cur.execute(
                """
                INSERT INTO CUSTOMER_ADDRESS (
                  CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
                  POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE, CUSTOMER_FULL_DETAIL
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_id,
                    ci_row.get('CUSTOMER_NAME'), ci_row.get('ADDRESS_LINE_1'), ci_row.get('ADDRESS_LINE_2'),
                    ci_row.get('CITY'), ci_row.get('COUNTY'), ci_row.get('STATE'),
                    ci_row.get('POSTAL_CODE'), ci_row.get('POSTALCODE_EXTENSION'), ci_row.get('COUNTRY'), ci_row.get('PHONE'),
                    computed_detail,
                )
            )
            inserted_with_detail = True
        except Exception:
            # Fallback: insert without the column, then update it
            cur.execute(
                """
                INSERT INTO CUSTOMER_ADDRESS (
                  CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
                  POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_id,
                    ci_row.get('CUSTOMER_NAME'), ci_row.get('ADDRESS_LINE_1'), ci_row.get('ADDRESS_LINE_2'),
                    ci_row.get('CITY'), ci_row.get('COUNTY'), ci_row.get('STATE'),
                    ci_row.get('POSTAL_CODE'), ci_row.get('POSTALCODE_EXTENSION'), ci_row.get('COUNTRY'), ci_row.get('PHONE')
                )
            )
            try:
                cur.execute(
                    """
                    UPDATE CUSTOMER_ADDRESS
                    SET CUSTOMER_FULL_DETAIL = %s
                    WHERE CUSTOMER_BUSINESS_ID = %s
                    """,
                    (computed_detail, new_id)
                )
            except Exception:
                pass

        # Optionally compute embedding if column exists
        try:
            cur.execute(
                """
                UPDATE CUSTOMER_ADDRESS
                SET CUSTOMER_FULL_DETAIL_EMBEDDING = AI_EMBED('snowflake-arctic-embed-m-v1.5', CUSTOMER_FULL_DETAIL)
                WHERE CUSTOMER_BUSINESS_ID = %s
                """,
                (new_id,)
            )
        except Exception:
            pass

        # Reuse assign flow
        ok = assign_ci_to_business_id(
            _conn,
            ci_row.get('IDENTIFIER_TYPE'),
            ci_row.get('IDENTIFIER_VALUE'),
            new_id,
        )

        cur.close()
        return (True, None, new_id) if ok else (False, "Assign step failed", None)
    except Exception as e:
        try:
            cur.close()
        except Exception:
            pass
        return False, str(e), None

def get_conn():
    """Helper to avoid calling get_snowflake_connection() repeatedly."""
    return get_snowflake_connection()

def go_to_next_item():
    """Callback function to advance to the next record."""
    idx = st.session_state.unassigned_idx
    keys = st.session_state.unassigned_ci_keys

    # If current record was activated (assigned or created), remove it first
    if bool(st.session_state.get('current_activated', False)):
        if 0 <= idx < len(keys):
            del keys[idx]
        st.session_state.current_activated = False
        st.session_state['buttons_disabled'] = False

        if not keys:
            st.session_state.current_ci = None
            st.session_state.top3_candidates = []
            st.session_state.selected_candidate_idx = 0
            return

        # After deletion, keep the same index (now pointing to the next item);
        # if we deleted the last item, step back to the new last index
        if idx >= len(keys):
            idx = len(keys) - 1
        st.session_state.unassigned_idx = idx
        itype, ivalue = keys[idx]
        st.session_state.current_ci = get_ci_by_key(get_conn(), itype, ivalue)
        st.session_state.top3_candidates = []
        st.session_state.selected_candidate_idx = 0
        return

    # Normal next navigation (no deletion)
    if idx < len(keys) - 1:
        st.session_state['buttons_disabled'] = False
        st.session_state.unassigned_idx += 1
        itype, ivalue = keys[st.session_state.unassigned_idx]
        st.session_state.current_ci = get_ci_by_key(get_conn(), itype, ivalue)
        st.session_state.top3_candidates = []
        st.session_state.selected_candidate_idx = 0

def go_to_previous_item():
    """Callback function to go to the previous record."""
    idx = st.session_state.unassigned_idx
    keys = st.session_state.unassigned_ci_keys

    # If current record was activated (assigned or created), remove it first
    if bool(st.session_state.get('current_activated', False)):
        if 0 <= idx < len(keys):
            del keys[idx]
        st.session_state.current_activated = False
        st.session_state['buttons_disabled'] = False

        if not keys:
            st.session_state.current_ci = None
            st.session_state.top3_candidates = []
            st.session_state.selected_candidate_idx = 0
            return

        # For previous, step back one position after deletion
        idx = idx - 1
        if idx < 0:
            idx = 0
        st.session_state.unassigned_idx = idx
        itype, ivalue = keys[idx]
        st.session_state.current_ci = get_ci_by_key(get_conn(), itype, ivalue)
        st.session_state.top3_candidates = []
        st.session_state.selected_candidate_idx = 0
        return

    # Normal previous navigation (no deletion)
    if idx > 0:
        st.session_state['buttons_disabled'] = False
        st.session_state.unassigned_idx -= 1
        itype, ivalue = keys[st.session_state.unassigned_idx]
        st.session_state.current_ci = get_ci_by_key(get_conn(), itype, ivalue)
        st.session_state.top3_candidates = []
        st.session_state.selected_candidate_idx = 0

# --- Button Callbacks ---
def on_assign_click():
    st.session_state['buttons_disabled'] = True
    conn = get_snowflake_connection()
    sel_idx = st.session_state.selected_candidate_idx if st.session_state.top3_candidates else 0
    chosen = st.session_state.top3_candidates[sel_idx] if st.session_state.top3_candidates else None
    if conn is None or chosen is None:
        st.error("Cannot assign: connection or candidate missing.")
        return
    success = assign_ci_to_business_id(
        conn,
        st.session_state.current_ci.get('IDENTIFIER_TYPE'),
        st.session_state.current_ci.get('IDENTIFIER_VALUE'),
        chosen.get('CUSTOMER_BUSINESS_ID')
    )
    if success:
        st.success("Assigned and updated verification message.")
        # Mark as activated; removal will occur on next/prev navigation
        st.session_state.current_activated = True



def on_create_new_id_click():

    st.session_state['buttons_disabled'] = True
    conn = get_snowflake_connection()
    if conn is None:
        st.error("Cannot create ID: missing Snowflake connection.")
        return
    success, err, new_id = create_new_id_and_assign(conn, st.session_state.current_ci)
    if success:
        st.success(f"Created new ID {new_id}, assigned, and updated verification message.")
        # Mark as activated; removal will occur on next/prev navigation
        st.session_state.current_activated = True
        # Verify with SELECT as requested
        try:
            cur = conn.cursor()
            like_val = f"%{(st.session_state.current_ci.get('CUSTOMER_NAME') or '').title()}%"
            cur.execute(
                "SELECT CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, CITY, STATE, POSTAL_CODE\n"
                "FROM CUSTOMER_ADDRESS\n"
                "WHERE CUSTOMER_NAME ILIKE %s\n"
                "LIMIT 10",
                (like_val,)
            )
            rows = cur.fetchall() or []
            cur.close()
        except Exception as _v_err:
            st.warning(f"Verification SELECT error: {_v_err}")
        # Hard refresh to avoid any shadow/duplicate UI artifacts
        try:
            st.cache_data.clear()
        except Exception:
            pass


# --- CRITICAL: Ensure this function uses unique keys! ---
def render_readonly_form(prefix, data, collapse_labels: bool = False):
    """
    Renders a block of disabled text inputs.
    The 'prefix' is ESSENTIAL to ensure widget keys are unique.
    Set collapse_labels=True to hide input labels (labels rendered in separate column).
    """
    data = data or {}
    label_vis = "collapsed" if collapse_labels else "visible"
    st.text_input("Customer Name", value=data.get('CUSTOMER_NAME', ''), key=f"{prefix}_name", disabled=True, label_visibility=label_vis)
    st.text_input("Address Line 1", value=data.get('ADDRESS_LINE_1', ''), key=f"{prefix}_addr1", disabled=True, label_visibility=label_vis)
    st.text_input("Address Line 2", value=data.get('ADDRESS_LINE_2', ''), key=f"{prefix}_addr2", disabled=True, label_visibility=label_vis)
    st.text_input("City", value=data.get('CITY', ''), key=f"{prefix}_city", disabled=True, label_visibility=label_vis)
    st.text_input("State", value=data.get('STATE', ''), key=f"{prefix}_state", disabled=True, label_visibility=label_vis)
    st.text_input("Postal Code", value=data.get('POSTAL_CODE', ''), key=f"{prefix}_zip", disabled=True, label_visibility=label_vis)


def render_labels_only(prefix: str = "LBL"):
    """Render the left-most labels column aligned with the form fields as plain small text."""
    labels = [
        "Customer Name",
        "Address Line 1",
        "Address Line 2",
        "City",
        "State",
        "Postal Code",
    ]
    
    for i, label in enumerate(labels):
        st.markdown(
            f"<div style='font-size:12px; color:#6b7280; line-height:38px;'>" \
            f"{label}</div>",
            unsafe_allow_html=True,
        )

def on_candidate_select_change():
    """
    Parses the selected option string to update the selected_candidate_idx.
    Example: "1. Clifford O..." -> index 0
    """
    selected_option = st.session_state.candidate_select
    try:
        # Get the number before the first period and convert to a 0-based index
        new_index = int(selected_option.split('.')[0]) - 1
        st.session_state.selected_candidate_idx = new_index
    except (ValueError, IndexError):
        # If parsing fails (e.g., for "No candidates"), default to 0
        st.session_state.selected_candidate_idx = 0
# --- 2. MAIN APP FUNCTION ---
def main():
    # --- Data Loading & Initialization ---
    # This part is similar to before, ensuring data exists before rendering.
    
    if 'current_ci' not in st.session_state:
        conn = get_conn()
        st.session_state.unassigned_ci_keys = get_unassigned_ci_keys(conn)
        st.session_state.unassigned_idx = 0
        if st.session_state.unassigned_ci_keys:
            itype, ivalue = st.session_state.unassigned_ci_keys[0]
            st.session_state.current_ci = get_ci_by_key(conn, itype, ivalue)
            st.session_state.top3_candidates = []
            st.session_state.selected_candidate_idx = 0
        else:
            st.session_state.current_ci = None

    # Render title with (x/y) new, where x is current index (1-based) and y is total
    total_items = len(st.session_state.get('unassigned_ci_keys', []))
    current_pos = (st.session_state.get('unassigned_idx', 0) + 1) if total_items > 0 else 0
    st.title(f"🗂️ Review New Records ({current_pos}/{total_items})")
    st.caption("Use Cortex Search to review and assign identifiers to golden addresses.")

    if st.session_state.current_ci and 'top3_candidates' in st.session_state and not st.session_state.top3_candidates:
         with st.spinner("Loading top matches from Cortex Search..."):
            st.session_state.top3_candidates = get_top3_candidates_for_ci(get_conn(), st.session_state.current_ci)
            st.session_state.selected_candidate_idx = 0

    if not st.session_state.current_ci:
        st.warning("No unassigned records found to review.")
        return

    # --- UI Rendering ---
    # Row-oriented layout: each field is rendered as Label | Golden | New

    # Header row
    hdr_l, hdr_c, hdr_r = st.columns([1, 2, 2])
    with hdr_c:
        st.subheader("Golden Record")
    with hdr_r:
        sel_score = None
        try:
            if st.session_state.top3_candidates:
                sel = st.session_state.top3_candidates[st.session_state.selected_candidate_idx]
                sel_score = sel.get('_SCORE')
        except Exception:
            sel_score = None
        if isinstance(sel_score, (int, float)):
            st.subheader("New Record - " + f"{sel_score * 100:.3f}%")
        else:
            st.subheader("New Record")

    candidate = {}
    if st.session_state.top3_candidates:
        candidate = st.session_state.top3_candidates[st.session_state.selected_candidate_idx]

    def _label(text: str):
        st.markdown(
            f"<div style='font-size:12px; color:#6b7280; line-height:38px;'>{text}</div>",
            unsafe_allow_html=True,
        )

    fields = [
        ("Customer Name", "CUSTOMER_NAME"),
        ("Address Line 1", "ADDRESS_LINE_1"),
        ("Address Line 2", "ADDRESS_LINE_2"),
        ("City", "CITY"),
        ("State", "STATE"),
        ("Postal Code", "POSTAL_CODE"),
    ]

    for label, key_name in fields:
        # Get the values from your candidate and new record dictionaries
        golden_value = candidate.get(key_name, "")
        new_record_value = st.session_state.current_ci.get(key_name, "")

        # Create the columns for the row
        r_l, r_c, r_r = st.columns([1, 2, 2])
        
        with r_l:
            _label(label)  # Your function to display the label
        
        with r_c:
            # Display the golden record value in a styled div
            st.markdown(
                f'<div class="text-field">{golden_value}</div>',
                unsafe_allow_html=True
            )
        
        with r_r:
            # Check if the values are different
            if golden_value != new_record_value:
                # If they don't match, add the "mismatch" class for highlighting
                st.markdown(
                    f'<div class="custom">{new_record_value}</div>',
                    unsafe_allow_html=True
                )
            else:
                # If they match, use the standard style
                st.markdown(
                    f'<div class="text-field">{new_record_value}</div>',
                    unsafe_allow_html=True
                )

    # Identifier Type row (label + right value)
    id_l, id_c, id_r = st.columns([1, 2, 2])
    with id_c:
        options = [f"{i+1}. {c.get('CUSTOMER_NAME', '')} | {c.get('CITY', '')}" for i, c in enumerate(st.session_state.top3_candidates)]
        if options:
            if "candidate_select" not in st.session_state:
                st.session_state.candidate_select = options[0]
            st.selectbox(
                "Top Candidates",
                options,
                key="candidate_select",
                label_visibility="visible",
                on_change=on_candidate_select_change,
            )
        else:
            st.selectbox(
                "Top Candidates",
                ["No candidates"],
                index=0,
                key="candidate_select",
                disabled=True,
                label_visibility="visible",
            )

    with id_r:
        st.markdown(
            f'<div class="text-field" style="margin-top: 10px;"><span style="color: gray">Identifier Type: </span><br/>{st.session_state.current_ci.get('IDENTIFIER_TYPE', '')}</div>',
            unsafe_allow_html=True
        )
    but_l, but_c, but_r = st.columns([1, 2, 2])
    with but_r:
        # Action buttons using the on_click callbacks
        bcol1, bcol2, bcol3, bcol4 = st.columns(4)
        with bcol1:
            st.button("Previous", on_click=go_to_previous_item, use_container_width=True, disabled=(st.session_state.unassigned_idx <= 0))
        with bcol2:
            can_assign = bool(st.session_state.top3_candidates)
            btns_disabled = bool(st.session_state.get('buttons_disabled', False))
            st.button("Assign", on_click=on_assign_click, use_container_width=True, disabled=(btns_disabled or (not can_assign)))
        with bcol3:
            can_create = bool(st.session_state.current_ci)
            btns_disabled = bool(st.session_state.get('buttons_disabled', False))
            st.button("New ID", on_click=on_create_new_id_click, use_container_width=True, disabled=(btns_disabled or (not can_create)))
        with bcol4:
            is_last = st.session_state.unassigned_idx >= len(st.session_state.unassigned_ci_keys) - 1
            st.button("Next", on_click=go_to_next_item, use_container_width=True, disabled=is_last)


if __name__ == "__main__":
    main()


