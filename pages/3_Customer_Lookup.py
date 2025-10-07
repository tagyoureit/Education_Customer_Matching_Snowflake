import os
import json
import toml
import time
import pandas as pd
import streamlit as st
import snowflake.connector


st.set_page_config(
    page_title="Customer Lookup",
    page_icon="🔎",
    layout="wide",
)


@st.cache_resource
def get_snowflake_connection():
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
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def cortex_search_top3(_conn, name_query: str):
    try:
        if _conn is None or not (name_query or '').strip():
            return []
        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE MDM_CUSTOMER_MATCHING_ROLE")
        except Exception:
            pass
        cur.execute("USE WAREHOUSE COMPUTE_WH")
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")

        payload = {
            "query": name_query,
            "columns": [
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
            "limit": 3,
        }
        payload_str = json.dumps(payload)
        payload_sql_literal = payload_str.replace("'", "''")

        # Reference: @Snowflake Docs
        sql = (
            "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(\n"
            "  'MDM_CUSTOMER_NAME_LOOKUP',\n"
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

        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            for key in ['results','matches','data','documents','rows','items']:
                if isinstance(result.get(key), list):
                    items = result.get(key)
                    break
            if not items and isinstance(result.get('result'), list):
                items = result.get('result')

        normalized = []
        for item in items:
            doc = item
            if isinstance(item, dict) and isinstance(item.get('document'), dict):
                doc = item['document']
            # Format display as "Customer name - Customer_full_detail"; compute when not indexed
            name = (doc.get('customer_name') if isinstance(doc, dict) else '') or ''
            full = (doc.get('customer_full_detail') if isinstance(doc, dict) else '') or ''
            if not full:
                parts = [
                    (doc.get('address_line_1') if isinstance(doc, dict) else '') or '',
                    (doc.get('address_line_2') if isinstance(doc, dict) else '') or '',
                    (doc.get('city') if isinstance(doc, dict) else '') or '',
                    (doc.get('state') if isinstance(doc, dict) else '') or '',
                    (doc.get('postal_code') if isinstance(doc, dict) else '') or '',
                    (doc.get('country') if isinstance(doc, dict) else '') or '',
                ]
                full = ", ".join([p for p in parts if p]).strip(', ')
            display = f"{name} - {full}".strip(' -')
            normalized.append({
                'CUSTOMER_BUSINESS_ID': (doc.get('customer_business_id') if isinstance(doc, dict) else '') or '',
                'CUSTOMER_NAME': name,
                'ADDRESS_LINE_1': (doc.get('address_line_1') if isinstance(doc, dict) else '') or '',
                'ADDRESS_LINE_2': (doc.get('address_line_2') if isinstance(doc, dict) else '') or '',
                'CITY': (doc.get('city') if isinstance(doc, dict) else '') or '',
                'COUNTY': (doc.get('county') if isinstance(doc, dict) else '') or '',
                'STATE': (doc.get('state') if isinstance(doc, dict) else '') or '',
                'POSTAL_CODE': (doc.get('postal_code') if isinstance(doc, dict) else '') or '',
                'POSTALCODE_EXTENSION': (doc.get('postalcode_extension') if isinstance(doc, dict) else '') or '',
                'COUNTRY': (doc.get('country') if isinstance(doc, dict) else '') or '',
                'CUSTOMER_FULL_DETAIL': full,
                'DISPLAY': display,
            })
        return normalized[:3]
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def fetch_customer_address_by_id(_conn, customer_business_id: str) -> dict:
    try:
        if _conn is None or not customer_business_id:
            return {}
        cur = _conn.cursor()
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        cur.execute(
            """
            SELECT CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
                   POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE, CUSTOMER_FULL_DETAIL
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS
            WHERE CUSTOMER_BUSINESS_ID = %s
            LIMIT 1
            """,
            (customer_business_id,)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return {}
        cols = [
            'CUSTOMER_BUSINESS_ID','CUSTOMER_NAME','ADDRESS_LINE_1','ADDRESS_LINE_2','CITY','COUNTY','STATE',
            'POSTAL_CODE','POSTALCODE_EXTENSION','COUNTRY','PHONE','CUSTOMER_FULL_DETAIL'
        ]
        return dict(zip(cols, row))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def fetch_identifier_rows_for_name(_conn, name_like: str) -> pd.DataFrame:
    try:
        if _conn is None or not (name_like or '').strip():
            return pd.DataFrame()
        cur = _conn.cursor()
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        like_val = f"%{name_like}%"
        cur.execute(
            """
            SELECT 
                   ca.CUSTOMER_NAME,
                   ca.CUSTOMER_BUSINESS_ID,
                   ci.IDENTIFIER_TYPE,
                   ci.IDENTIFIER_VALUE,
                   ci.ADDRESS_ROLE,
                   ci.CUSTOMER_FULL_DETAIL,
                   ci.CONFIDENCE_SCORE,
                   ci.CREATED_TIMESTAMP
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            INNER JOIN MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
              ON ca.CUSTOMER_BUSINESS_ID = ci.CUSTOMER_BUSINESS_ID
            WHERE ca.CUSTOMER_NAME ILIKE %s
            ORDER BY ci.CREATED_TIMESTAMP DESC
            LIMIT 500
            """,
            (like_val,)
        )
        rows = cur.fetchall() or []
        cur.close()
        cols = ['CUSTOMER_NAME','CUSTOMER_BUSINESS_ID','IDENTIFIER_TYPE','IDENTIFIER_VALUE','ADDRESS_ROLE','CUSTOMER_FULL_DETAIL','CONFIDENCE_SCORE','CREATED_TIMESTAMP']
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        return pd.DataFrame()


def render_address_topbar(data: dict):
    data = data or {}
    cbid = data.get('CUSTOMER_BUSINESS_ID', '')
    name = data.get('CUSTOMER_NAME', '')
    line1 = data.get('ADDRESS_LINE_1', '')
    line2 = data.get('ADDRESS_LINE_2', '')
    city = data.get('CITY', '')
    state = data.get('STATE', '')
    postal = data.get('POSTAL_CODE', '')
    country = data.get('COUNTRY', '')
    county = data.get('COUNTY', '')
    phone = data.get('PHONE', '')

    parts = [p for p in [line1, line2] if p]
    addr_left = ", ".join(parts)
    city_state_zip = ", ".join([p for p in [city, state, postal] if p])

    c1, c2, c3 = st.columns([2, 3, 2])
    with c1:
        st.markdown(f"**CBID:** {cbid}<br/>**Name:** {name}", unsafe_allow_html=True)
    with c2:
        st.markdown(f"**Address:** {addr_left}<br/>**City/State/Zip:** {city_state_zip}", unsafe_allow_html=True)
    with c3:
        st.markdown(f"**Country:** {country}<br/>**County:** {county}<br/>**Phone:** {phone}", unsafe_allow_html=True)


def main():
    st.title("🔎 Customer Lookup")
    st.caption("Search by name using Cortex Search and view address and related identifiers.")

    conn = get_snowflake_connection()
    if conn is None:
        st.error("Snowflake connection not available. Configure credentials or connections.toml.")
        return

    # Search input row
    search_col, _ = st.columns([2, 3])
    with search_col:
        query = st.text_input("Customer Name", value=st.session_state.get("lookup_query", ""), key="lookup_query", placeholder="Type a customer (e.g., Segerstrom)")
        if (query or "").strip():
            captured = query
            prev = st.session_state.get("debounce_query")
            if captured != prev:
                st.session_state["debounce_query"] = captured
                with st.spinner("Searching..."):
                    time.sleep(1.0)
                # Only search if input remained unchanged during debounce window
                if st.session_state.get("debounce_query") == captured:
                    st.session_state["lookup_results"] = cortex_search_top3(conn, captured)
                    st.session_state["lookup_selected_idx"] = 0

    results = st.session_state.get("lookup_results", [])
    if results:
        options = [r.get('DISPLAY') for r in results]
        st.selectbox(
            "Top matches",
            options,
            index=min(st.session_state.get("lookup_selected_idx", 0), max(len(options)-1, 0)),
            key="lookup_selected_display",
            on_change=lambda: st.session_state.update({
                "lookup_selected_idx": max(0, options.index(st.session_state.get("lookup_selected_display", options[0])))
            }),
        )

        selected = results[st.session_state.get("lookup_selected_idx", 0)] if results else None

        # Address across the top as text
        st.subheader("Customer Address")
        if selected and selected.get('CUSTOMER_BUSINESS_ID'):
            addr = fetch_customer_address_by_id(conn, selected['CUSTOMER_BUSINESS_ID'])
        else:
            addr = selected
        render_address_topbar(addr or {})

        st.subheader("Related Identifiers")
        name_for_filter = selected.get('CUSTOMER_NAME') if isinstance(selected, dict) else None
        df = fetch_identifier_rows_for_name(conn, name_for_filter) if name_for_filter else pd.DataFrame()
        if not df.empty:
            # Build Source Link column with dynamic text "{IDENTIFIER_TYPE} Link" and active URL
            df = df.copy()
            # Format confidence as percentage text (e.g., 0.82%)
            df['CONFIDENCE_SCORE'] = df['CONFIDENCE_SCORE'].apply(lambda v: "" if pd.isna(v) else f"{float(v):.2f}%")
            df['SOURCE_LINK'] = df.apply(
                lambda r: f"<a href=\"http://source-system/{r['IDENTIFIER_VALUE']}\" target=\"_blank\">{r['IDENTIFIER_TYPE']} Link</a>",
                axis=1
            )
            # Reorder to requested columns per request
            display_cols = ['CUSTOMER_FULL_DETAIL','ADDRESS_ROLE','SOURCE_LINK','CONFIDENCE_SCORE']
            show_df = df[display_cols]

            # Render as full-width HTML table to ensure clickable links with custom text
            html_table = show_df.to_html(escape=False, index=False)
            st.markdown("""
                <style>
                .fullwidth-table table { width: 100%; }
                .fullwidth-table td, .fullwidth-table th { padding: 8px 10px; }
                </style>
            """, unsafe_allow_html=True)
            st.markdown(f"<div class='fullwidth-table'>{html_table}</div>", unsafe_allow_html=True)
        else:
            st.info("No related identifiers found for this name.")
    else:
        st.info("Enter a name and click Search to see results.")


if __name__ == "__main__":
    main()


