import os
import toml
import streamlit as st
import snowflake.connector
from shared_utils import process_unenriched_identifiers


st.set_page_config(
    page_title="Generate Samples & Assign",
    page_icon="🧰",
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


def call_generate_customer_samples(_conn):
    try:
        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE WAREHOUSE COMPUTE_WH")
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        cur.execute("CALL MDM_CUSTOMER_MATCHING.PUBLIC.GENERATE_CUSTOMER_SAMPLES()")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        try:
            cur.close()
        except Exception:
            pass
        raise e


def main():
    st.title("🧰 Generate Samples & Assign")

    # Step status flags (UI-only)
    if 'step1_done' not in st.session_state:
        st.session_state.step1_done = False
    if 'step2_done' not in st.session_state:
        st.session_state.step2_done = False

    st.caption(
        f"Step 1: Generate new sample CUSTOMER_IDENTIFIER rows via stored procedure. "
        f"{'✅' if st.session_state.step1_done else ''}"
    )

    conn = get_snowflake_connection()
    if conn is None:
        st.error("Snowflake connection not available. Set credentials or connections.toml.")
        return

    generate_col, _ = st.columns([1, 3])
    with generate_col:
        if st.button("Generate Samples", use_container_width=True):
            with st.spinner("Generating sample CUSTOMER_IDENTIFIER rows and computing embeddings..."):
                try:
                    result = call_generate_customer_samples(conn)
                    st.success(f"Stored procedure completed. Inserted rows: {result}")
                    st.session_state.step1_done = True
                except Exception as e:
                    st.error(f"Error: {e}")

    

    st.divider()
    st.caption(
        f"Step 2: Automatic matching via Cortex Search (uses search confidence score). "
        f"{'✅' if st.session_state.step2_done else ''}"
    )
    proc_cols = st.columns([1,1,2])
    with proc_cols[0]:
        threshold = st.number_input("Search threshold", value=0.80, min_value=0.0, max_value=1.0, step=0.01, format="%.2f")
    with proc_cols[1]:
        limit = st.number_input("Max rows", value=100, min_value=1, max_value=10000, step=10)
    if st.button("Process All Unenriched", use_container_width=True):
        # Show only one live status at a time using a placeholder
        status_placeholder = st.empty()
        current = { 'status': None }

        def _set_status(label: str, state: str = "running", expanded: bool = True):
            status_placeholder.empty()
            with status_placeholder.container():
                current['status'] = st.status(label, expanded=expanded)
            if state != "running":
                current['status'].update(label=label, state=state)

        def _update(label: str, state: str = "running"):
            if current['status'] is not None:
                current['status'].update(label=label, state=state)
            else:
                _set_status(label, state)

        def _progress(stage, **kwargs):
            if stage == 'fetch_start':
                _set_status("Fetching unenriched identifiers...", state="running", expanded=True)
            elif stage == 'fetch_end':
                cnt = kwargs.get('count', 0)
                _update(f"Fetched {cnt} unenriched identifiers.", state="complete")
                if cnt > 0:
                    _set_status("Processing rows: searching and assigning...", state="running", expanded=True)
            elif stage == 'row_start':
                i, t = kwargs.get('index', 0), kwargs.get('total', 0)
                _update(f"Processing {i}/{t}...", state="running")
            elif stage == 'row_end':
                i, t = kwargs.get('index', 0), kwargs.get('total', 0)
                if i == t:
                    _update(f"Processed {t} rows.", state="complete")
                    _set_status("Populating verification for VALID rows...", state="running", expanded=True)
            elif stage == 'verify_start':
                _set_status("Populating verification for VALID rows...", state="running", expanded=True)
            elif stage == 'verify_end':
                _update("Verification population complete.", state="complete")

        try:
            summary = process_unenriched_identifiers(conn, threshold=threshold, limit=int(limit), progress=_progress)
            st.success(f"Processed {summary.get('count',0)} rows.")
            if summary.get('verification_ran'):
                st.success("Verification populated for VALID rows via POPULATE_VERIFICATION_MESSAGE.sql")
            else:
                st.caption("No VALID rows in this run; verification not executed.")
            st.session_state.step2_done = True
            results = summary.get('results', [])
            if results:
                st.dataframe(results, use_container_width=True, hide_index=True)
                # Show reproducible SQL template for the processed keys
                key_filters = []
                for r in summary.get('processed_rows', []):
                    idt, idv = r
                    key_filters.append(
                        f"(ci.IDENTIFIER_TYPE = '{idt.replace("'","''")}' AND ci.IDENTIFIER_VALUE = '{idv.replace("'","''")}')"
                    )
                where_clause = " OR\n  ".join(key_filters) if key_filters else "1=0"
                sql_text = (
                    "SELECT ci.ENRICHED_INDICATOR, ci.CUSTOMER_NAME, ci.CUSTOMER_BUSINESS_ID, ci.IDENTIFIER_TYPE, ci.CUSTOMER_FULL_DETAIL, ci.CONFIDENCE_SCORE, ci.CREATED_TIMESTAMP\n"
                    "FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci\n"
                    f"WHERE {where_clause}"
                )
                st.code(sql_text, language="sql")
            else:
                st.info("No rows were processed.")
        except Exception as e:
            st.error(f"Error: {e}")


if __name__ == "__main__":
    main()


