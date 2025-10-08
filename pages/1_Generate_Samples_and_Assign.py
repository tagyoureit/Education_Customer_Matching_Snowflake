import os
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from shared_utils import process_unenriched_identifiers, connect_to_snowflake, get_session_context


st.set_page_config(
    page_title="Generate Samples & Simulate Data Pipeline",
    page_icon="🧰",
    layout="wide",
)


@st.cache_resource
def get_snowflake_connection():
    return connect_to_snowflake()


def call_generate_customer_samples(_conn):
    try:
        cur = _conn.cursor()
        cur.execute("CALL GENERATE_CUSTOMER_SAMPLES()")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        try:
            cur.close()
        except Exception:
            pass
        raise e


def fetch_recent_generated(_conn, count_hint: int = 10):
    try:
        cur = _conn.cursor()
        cur.execute(
            """
            SELECT 
              IDENTIFIER_TYPE,
              IDENTIFIER_VALUE,
              CUSTOMER_NAME,
              ADDRESS_ROLE,
              CUSTOMER_FULL_DETAIL,
              CUSTOMER_BUSINESS_ID,
              ENRICHED_INDICATOR,
              SEARCH_CONFIDENCE_SCORE,
              CONFIDENCE_SCORE,
              VERIFICATION_MESSAGE,
              EDIT_DISTANCE,
              CREATED_TIMESTAMP
            FROM CUSTOMER_IDENTIFIER
            ORDER BY CREATED_TIMESTAMP DESC
            LIMIT %s
            """,
            (int(count_hint) if count_hint else 10,)
        )
        rows = cur.fetchall() or []
        cur.close()
        if not rows:
            return None
        cols = [
            'IDENTIFIER_TYPE','IDENTIFIER_VALUE','CUSTOMER_NAME','ADDRESS_ROLE','CUSTOMER_FULL_DETAIL','CUSTOMER_BUSINESS_ID','ENRICHED_INDICATOR',
            'SEARCH_CONFIDENCE_SCORE','CONFIDENCE_SCORE','VERIFICATION_MESSAGE','EDIT_DISTANCE','CREATED_TIMESTAMP'
        ]
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        return None


def on_click_generate_samples():
    conn = get_snowflake_connection()
    st.session_state.show_generation_bullets = True
    st.session_state.generated_preview_df = None
    st.session_state.gen_status = None
    if conn is None:
        st.session_state.gen_status = (False, "Snowflake connection not available. Set credentials or connections.toml.")
        return
    try:
        inserted = call_generate_customer_samples(conn)
        st.session_state.step1_done = True
        st.session_state.gen_status = (True, f"Stored procedure completed. Inserted rows: {inserted}")
        st.session_state.generated_preview_df = fetch_recent_generated(conn, inserted or 10)
    except Exception as e:
        st.session_state.gen_status = (False, f"Error: {e}")


def main():
    st.title("🧰 Generate Samples & Assign")

    # Step status flags (UI-only)
    if 'step1_done' not in st.session_state:
        st.session_state.step1_done = False
    if 'step2_done' not in st.session_state:
        st.session_state.step2_done = False
    if 'generated_preview_df' not in st.session_state:
        st.session_state.generated_preview_df = None
    if 'show_generation_bullets' not in st.session_state:
        st.session_state.show_generation_bullets = False
    if 'gen_status' not in st.session_state:
        st.session_state.gen_status = None

    st.caption(
        f"Step 1: Generate new sample CUSTOMER_IDENTIFIER rows via stored procedure. \n "
        f"{'✅' if st.session_state.step1_done else ''}\n"
        f"- Select 8 random base rows from `CUSTOMER_IDENTIFIER` and 2 from `PUBLIC_SCHOOLS`.\n"
        f"- Generate slight/typo variations to simulate new identifiers.\n"
        f"- Insert 10 rows into `CUSTOMER_IDENTIFIER` with: `CUSTOMER_FULL_DETAIL` and its embedding computed.\n"
        f"- Leave these fields empty (to be populated later): `CUSTOMER_BUSINESS_ID`, `ENRICHED_INDICATOR`, `SEARCH_CONFIDENCE_SCORE`, `CONFIDENCE_SCORE`, `EDIT_DISTANCE`, `VERIFICATION_MESSAGE`.\n"
    )

    conn = get_snowflake_connection()
    if conn is None:
        st.error("Snowflake connection not available. Set credentials or connections.toml.")
        return

    generate_col, _ = st.columns([1, 3])

    

    with generate_col:
        st.button("Generate Samples", use_container_width=True, on_click=on_click_generate_samples)

    status_tuple = st.session_state.get('gen_status')
    if isinstance(status_tuple, tuple):
        ok, msg = status_tuple
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    # Full-width preview area (separate from button column)
    if isinstance(st.session_state.get('generated_preview_df'), pd.DataFrame) and not st.session_state.generated_preview_df.empty:
        st.subheader("Preview of newly generated rows")
        st.dataframe(st.session_state.generated_preview_df, use_container_width=True, hide_index=True)
    elif st.session_state.step1_done:
        st.caption("No newly generated rows found to preview.")

    st.divider()
    st.caption(
        f"Step 2: Automatic matching via Cortex Search (rough estimate of best match). \n"
        f"{'✅' if st.session_state.step2_done else ''}\n"
        f"- This will set the `ENRICHED_INDICATOR` to 'VALID' if the search confidence score is greater than the threshold. \n"
        f"   - Set `CUSTOMER_BUSINESS_ID` of the top match.\n"
        f"   - Compute `CONFIDENCE_SCORE`, `EDIT_DISTANCE` `CUSTOMER_FULL_DETAIL`, `VERIFICATION_MESSAGE`\n"
        f"- This will set the `ENRICHED_INDICATOR` to 'ERROR' if the search confidence score is less than or equal to the threshold. \n"
    )
    proc_cols = st.columns([1,1,2])
    with proc_cols[0]:
        threshold = st.number_input("Search threshold", value=0.80, min_value=0.0, max_value=1.0, step=0.01, format="%.2f")
    with proc_cols[1]:
        limit = st.number_input("Max rows", value=100, min_value=1, max_value=10000, step=10)
    if st.button("Attempt to match to Golden Records", use_container_width=True):
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
                st.success("Verification populated for VALID rows.")
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


