"""
Data View Page - Browse and manage customer data
"""

import streamlit as st
import pandas as pd
import snowflake.connector
import os
import uuid
from typing import Dict, List, Tuple, Optional
import toml
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from shared_utils import (
    recalculate_all_similarities as shared_recalculate_all_similarities,
    recalculate_similarity_for_test_id,
    DEFAULT_THRESHOLDS,
)

# Page configuration
st.set_page_config(
    page_title="Data View",
    page_icon="📋",
    layout="wide"
)

# Constants from main app
DEFAULT_THRESHOLDS = {
    'exact': 0.995,
    'very_close': 0.980,
    'somewhat_close': 0.920
}

@st.cache_resource
def get_snowflake_connection():
    """Create Snowflake connection using snow CLI config or environment variables"""
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

@st.cache_data
def load_valid_customers(_conn) -> pd.DataFrame:
    """Load valid customers from Snowflake"""
    try:
        query = """
        SELECT ID, SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1, 
               ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY,
               CUSTOMER_FULL_DETAIL
        FROM VALID_CUSTOMERS
        ORDER BY ID
        """
        return pd.read_sql(query, _conn)
    except Exception as e:
        st.error(f"Error loading valid customers: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def load_test_matches(_conn) -> pd.DataFrame:
    """Load test matches from Snowflake"""
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

@st.cache_data
def compute_similarities(_conn, thresholds: Dict[str, float]) -> pd.DataFrame:
    """Load similarity results from Snowflake"""
    try:
        results_sql = """
        SELECT * FROM CUSTOMER_MATCH_RESULTS
        ORDER BY SIMILARITY_SCORE DESC
        """
        return pd.read_sql(results_sql, _conn)
    except Exception as e:
        st.error(f"Error loading similarities: {str(e)}")
        return pd.DataFrame()

def get_top_matches(_conn, test_id: str, thresholds: Dict[str, float], limit: int = 5) -> pd.DataFrame:
    """Get top 5 matching records for a specific test ID"""
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

def update_test_record(_conn, record_data: Dict) -> bool:
    """Update existing test record"""
    try:
        cursor = _conn.cursor()
        
        update_sql = """
        UPDATE TEST_MATCHES 
        SET NAME = %s, SOURCE_SYSTEM = %s, ADDRESS_LINE_1 = %s, 
            ADDRESS_LINE_2 = %s, CITY = %s, STATE = %s, 
            POSTAL_CODE = %s, COUNTRY = %s,
            CUSTOMER_FULL_DETAIL = %s
        WHERE SOURCE_PKEY = %s
        """
        
        full_detail = f"{record_data['NAME']} {record_data['ADDRESS_LINE_1']} {record_data['ADDRESS_LINE_2']} {record_data['CITY']} {record_data['STATE']} {record_data['POSTAL_CODE']} {record_data['COUNTRY']}".strip()
        
        cursor.execute(update_sql, (
            record_data['NAME'],
            record_data['SOURCE_SYSTEM'], 
            record_data['ADDRESS_LINE_1'],
            record_data['ADDRESS_LINE_2'],
            record_data['CITY'],
            record_data['STATE'],
            record_data['POSTAL_CODE'],
            record_data['COUNTRY'],
            full_detail,
            record_data['SOURCE_PKEY']
        ))
        
        cursor.close()
        return True
        
    except Exception as e:
        st.error(f"Error updating record: {str(e)}")
        return False

# Use the shared function instead of duplicating code
def recalculate_all_similarities(_conn, thresholds: Dict[str, float] = None) -> bool:
    """Wrapper to use shared recalculation function"""
    return shared_recalculate_all_similarities(_conn, thresholds)

def create_test_record(_conn, record_data: Dict) -> str:
    """Create new test record with UUID"""
    try:
        cursor = _conn.cursor()
        
        new_id = f"TEST_{str(uuid.uuid4()).replace('-', '').upper()[:12]}"
        
        insert_sql = """
        INSERT INTO TEST_MATCHES 
        (SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1, ADDRESS_LINE_2, 
         CITY, STATE, POSTAL_CODE, COUNTRY, CUSTOMER_FULL_DETAIL)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        full_detail = f"{record_data['NAME']} {record_data['ADDRESS_LINE_1']} {record_data['ADDRESS_LINE_2']} {record_data['CITY']} {record_data['STATE']} {record_data['POSTAL_CODE']} {record_data['COUNTRY']}".strip()
        
        cursor.execute(insert_sql, (
            new_id,
            record_data['NAME'],
            record_data['SOURCE_SYSTEM'],
            record_data['ADDRESS_LINE_1'], 
            record_data['ADDRESS_LINE_2'],
            record_data['CITY'],
            record_data['STATE'],
            record_data['POSTAL_CODE'],
            record_data['COUNTRY'],
            full_detail
        ))
        
        embedding_sql = """
        UPDATE TEST_MATCHES 
        SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
        WHERE SOURCE_PKEY = %s
        """
        cursor.execute(embedding_sql, (new_id,))
        
        cursor.close()
        return new_id
        
    except Exception as e:
        st.error(f"Error creating record: {str(e)}")
        return None

@st.cache_data
def get_dashboard_data(_conn):
    """Load summary data for dashboard"""
    try:
        # Get test matches count
        test_count_query = "SELECT COUNT(*) FROM TEST_MATCHES"
        test_count = pd.read_sql(test_count_query, _conn).iloc[0, 0]
        
        # Get valid customers count  
        valid_count_query = "SELECT COUNT(*) FROM VALID_CUSTOMERS"
        valid_count = pd.read_sql(valid_count_query, _conn).iloc[0, 0]
        
        # Get match categories breakdown with proper ordering
        matches_query = """
        SELECT 
            MATCH_CATEGORY,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM CUSTOMER_MATCH_RESULTS), 2) as percentage
        FROM CUSTOMER_MATCH_RESULTS
        GROUP BY MATCH_CATEGORY
        ORDER BY 
            CASE MATCH_CATEGORY 
                WHEN 'EXACT' THEN 1
                WHEN 'VERY_CLOSE' THEN 2
                WHEN 'SOMEWHAT_CLOSE' THEN 3
                WHEN 'NOT_CLOSE' THEN 4
                ELSE 5
            END
        """
        matches_df = pd.read_sql(matches_query, _conn)
        
        return {
            'test_count': test_count,
            'valid_count': valid_count,
            'matches_df': matches_df
        }
    except Exception as e:
        st.error(f"Error loading dashboard data: {str(e)}")
        return None

def main():
    st.title("📋 Customer Data Management")
    st.markdown("Browse customers, edit records, and analyze matches")
    
    # Initialize session state
    if 'thresholds' not in st.session_state:
        st.session_state.thresholds = DEFAULT_THRESHOLDS.copy()
    if 'selected_test_record' not in st.session_state:
        st.session_state.selected_test_record = None
    if 'form_data' not in st.session_state:
        st.session_state.form_data = {}
    
    # Get Snowflake connection
    conn = get_snowflake_connection()
    
    # Load dashboard data first
    with st.spinner("Loading dashboard data..."):
        dashboard_data = get_dashboard_data(conn)
    
    # Display KPIs at the top
    if dashboard_data:
        st.header("📊 Key Performance Indicators")
        
        # Key metrics - now with 6 columns for all categories
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        matches_df = dashboard_data['matches_df']
        
        with col1:
            st.metric("Total Valid Customers", dashboard_data['valid_count'])
        
        with col2:
            st.metric("Total Test Customers", dashboard_data['test_count'])
        
        if not matches_df.empty:
            # Get all match categories in the right order
            exact_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'EXACT']
            very_close_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'VERY_CLOSE']
            somewhat_close_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'SOMEWHAT_CLOSE']
            not_close_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'NOT_CLOSE']
            
            with col3:
                exact_count = exact_matches.iloc[0]['COUNT'] if not exact_matches.empty else 0
                exact_pct = exact_matches.iloc[0]['PERCENTAGE'] if not exact_matches.empty else 0
                # --- UPDATED: Using markdown for custom color ---
                st.markdown(f"""
                <div style="line-height: 1.2;">
                    <p style="font-size: 14px; color: rgba(49, 51, 63, 0.6); margin: 0;">Exact Matches</p>
                    <p style="font-size: 2.25rem; font-weight: 600; margin: 0;">{exact_count}</p>
                    <p style="color: #28A745; font-size: 1rem; margin: 0;">{exact_pct:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                vc_count = very_close_matches.iloc[0]['COUNT'] if not very_close_matches.empty else 0
                vc_pct = very_close_matches.iloc[0]['PERCENTAGE'] if not very_close_matches.empty else 0
                # --- UPDATED: Using markdown for custom color ---
                st.markdown(f"""
                <div style="line-height: 1.2;">
                    <p style="font-size: 14px; color: rgba(49, 51, 63, 0.6); margin: 0;">Very Close Matches</p>
                    <p style="font-size: 2.25rem; font-weight: 600; margin: 0;">{vc_count}</p>
                    <p style="color: #20C997; font-size: 1rem; margin: 0;">{vc_pct:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
            
            with col5:
                sc_count = somewhat_close_matches.iloc[0]['COUNT'] if not somewhat_close_matches.empty else 0
                sc_pct = somewhat_close_matches.iloc[0]['PERCENTAGE'] if not somewhat_close_matches.empty else 0
                st.markdown(f"""
                <div style="line-height: 1.2;">
                    <p style="font-size: 14px; color: rgba(49, 51, 63, 0.6); margin: 0;">Somewhat Close Matches</p>
                    <p style="font-size: 2.25rem; font-weight: 600; margin: 0;">{sc_count}</p>
                    <p style="color: #D4AC0D; font-size: 1rem; margin: 0;">{sc_pct:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col6:
                nc_count = not_close_matches.iloc[0]['COUNT'] if not not_close_matches.empty else 0
                nc_pct = not_close_matches.iloc[0]['PERCENTAGE'] if not not_close_matches.empty else 0
                # --- UPDATED: Using markdown for custom color ---
                st.markdown(f"""
                <div style="line-height: 1.2;">
                    <p style="font-size: 14px; color: rgba(49, 51, 63, 0.6); margin: 0;">Not Close Matches</p>
                    <p style="font-size: 2.25rem; font-weight: 600; margin: 0;">{nc_count}</p>
                    <p style="color: #DC3545; font-size: 1rem; margin: 0;">{nc_pct:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
        
        # Divider
        st.divider()
    
    # Load detailed data
    with st.spinner("Loading detailed data..."):
        valid_customers = load_valid_customers(conn)
        test_matches = load_test_matches(conn)
        similarities = compute_similarities(conn, st.session_state.thresholds)
    
    # Main content area
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        # Table Views
        st.header("📋 Customer Data")
        
        tab1, tab2 = st.tabs(["Valid Customers", "Test Customers"])
        
        with tab1:
            st.subheader("Valid Customers")
            if not valid_customers.empty:
                display_valid = valid_customers[['CUSTOMER_FULL_DETAIL', 'ID']].copy()
                st.dataframe(
                    display_valid,
                    height=300,
                    use_container_width=True
                )
        
        with tab2:
            st.subheader("Test Customers")
            
            # Filter by Match Category
            st.markdown("🔍 **Filter by Match Category:**")
            if not similarities.empty:
                available_categories = similarities['MATCH_CATEGORY'].unique().tolist()
                selected_categories = st.multiselect(
                    "Select categories to display:",
                    options=available_categories,
                    default=available_categories,
                    key="category_filter"
                )
                
                # Filter test matches based on selected categories
                if selected_categories:
                    filtered_test_ids = similarities[
                        similarities['MATCH_CATEGORY'].isin(selected_categories)
                    ]['TEST_ID'].unique()
                    filtered_test_matches = test_matches[
                        test_matches['SOURCE_PKEY'].isin(filtered_test_ids)
                    ]
                else:
                    filtered_test_matches = pd.DataFrame()
            else:
                filtered_test_matches = test_matches
                
            st.markdown("Click on a row to edit it.")
            if not filtered_test_matches.empty:
                selected_rows = st.dataframe(
                    filtered_test_matches[['CUSTOMER_FULL_DETAIL', 'SOURCE_PKEY']],
                    height=300,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="single-row"
                )
                
                # Handle row selection
                if selected_rows['selection']['rows']:
                    selected_idx = selected_rows['selection']['rows'][0]
                    selected_record = filtered_test_matches.iloc[selected_idx]
                    st.session_state.selected_test_record = selected_record
                    
                    # Load into form
                    st.session_state.form_data = {
                        'SOURCE_PKEY': selected_record['SOURCE_PKEY'],
                        'NAME': selected_record['NAME'],
                        'SOURCE_SYSTEM': selected_record['SOURCE_SYSTEM'],
                        'ADDRESS_LINE_1': selected_record['ADDRESS_LINE_1'],
                        'ADDRESS_LINE_2': selected_record['ADDRESS_LINE_2'],
                        'CITY': selected_record['CITY'],
                        'STATE': selected_record['STATE'],
                        'POSTAL_CODE': selected_record['POSTAL_CODE'],
                        'COUNTRY': selected_record['COUNTRY']
                    }
        
        # Top 5 Matches Display
        if st.session_state.get('selected_test_record') is not None:
            record = st.session_state.selected_test_record
            st.header("🎯 Top 5 Matches")
            top_matches = get_top_matches(conn, record['SOURCE_PKEY'], st.session_state.thresholds)
            
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
                    
                    st.write(f"{color} **{similarity_pct:.2f}%** ({match_category}) - {match['VALID_CUSTOMER_FULL_DETAIL']} | Valid ID: {match['VALID_ID']}")
                
                # AI analysis for top match
                st.subheader("🤖 AI Analysis - Top Match")
                top_match = top_matches.iloc[0]
                
                analysis_placeholder = st.empty()
                analysis_placeholder.info("🔄 Loading AI analysis...")
                
                ai_analysis = get_ai_analysis(conn, record['SOURCE_PKEY'], top_match['VALID_ID'])
                
                analysis_placeholder.empty()
                with st.container():
                    st.markdown(ai_analysis)
            else:
                st.warning("No matches found for this record")
    
    with col_right:
        # Customer Form
        st.header("✏️ Test Customer Form (add/update)")
        st.markdown("Fill out the form to add a new customer, or select a row in 'Test Customers' to edit.")
        
        with st.form("customer_form", clear_on_submit=False):
            form_data = st.session_state.form_data
            
            # Current record display
            if st.session_state.get('selected_test_record') is not None:
                current_details = st.session_state.selected_test_record.get('CUSTOMER_FULL_DETAIL', '')
                st.text_input("📋 Current Full Customer Details", value=current_details, disabled=True)
            
            # Form fields
            col1a, col1b = st.columns([1, 2])
            with col1a:
                id_value = st.text_input("ID", value=form_data.get('SOURCE_PKEY', ''), disabled=True)
            with col1b:
                name = st.text_input("Name", value=form_data.get('NAME', ''))
            
            col2a, col2b = st.columns([1, 2])
            with col2a:
                source_system = st.text_input("Source", value=form_data.get('SOURCE_SYSTEM', ''))
            with col2b:
                address1 = st.text_input("Address 1", value=form_data.get('ADDRESS_LINE_1', ''))
            
            address2 = st.text_input("Address 2", value=form_data.get('ADDRESS_LINE_2', ''))
            
            col4a, col4b, col4c = st.columns([2, 1, 1])
            with col4a:
                city = st.text_input("City", value=form_data.get('CITY', ''))
            with col4b:
                state = st.text_input("State", value=form_data.get('STATE', ''))
            with col4c:
                postal_code = st.text_input("Postal", value=form_data.get('POSTAL_CODE', ''))
            
            country = st.text_input("Country", value=form_data.get('COUNTRY', ''))
            
            # Buttons
            col5b, col5c = st.columns([1, 1])
            with col5b:
                submitted = st.form_submit_button("💾 Save to Test Customers Table", use_container_width=True)
            with col5c:
                new_record = st.form_submit_button("🆕 Clear Form", use_container_width=True)
            
            if submitted:
                if not (name or '').strip():
                    st.error("❌ Name is required")
                elif not (source_system or '').strip():
                    st.error("❌ Source System is required")
                else:
                    record_data = {
                        'SOURCE_PKEY': id_value,
                        'NAME': (name or '').strip(),
                        'SOURCE_SYSTEM': (source_system or '').strip(),
                        'ADDRESS_LINE_1': (address1 or '').strip(),
                        'ADDRESS_LINE_2': (address2 or '').strip(),
                        'CITY': (city or '').strip(),
                        'STATE': (state or '').strip(),
                        'POSTAL_CODE': (postal_code or '').strip(),
                        'COUNTRY': (country or '').strip()
                    }
                    
                    success = False
                    if id_value:  # Update existing
                        success = update_test_record(conn, record_data)
                        if success:
                            st.success("✅ Record updated successfully!")
                            # Clear cache BEFORE recalculating to ensure fresh data
                            st.cache_data.clear()
                            # Recalculate similarities for this record
                            with st.spinner("🔄 Recalculating similarity for this record..."):
                                recalc_success = recalculate_similarity_for_test_id(
                                    conn, id_value, st.session_state.thresholds
                                )
                                if recalc_success:
                                    st.success("✅ Similarities recalculated!")
                                    # Clear cache again after recalculation and force rerun
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Record updated but similarity recalculation failed")
                    else:  # Create new
                        new_id = create_test_record(conn, record_data)
                        if new_id:
                            st.success(f"✅ New record created with ID: {new_id}")
                            # Clear cache BEFORE calculating to ensure fresh data
                            st.cache_data.clear()
                            # Recalculate similarities for new record
                            with st.spinner("🔄 Calculating similarity for new record..."):
                                recalc_success = recalculate_similarity_for_test_id(
                                    conn, new_id, st.session_state.thresholds
                                )
                                if recalc_success:
                                    st.success("✅ Similarities calculated!")
                                    # Clear cache again after calculation and force rerun
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Record created but similarity calculation failed")
                            st.session_state.form_data['SOURCE_PKEY'] = new_id
                            success = True
                    
                    # Rerun is now handled inside each success branch
                
            if new_record:
                st.session_state.form_data = {}
                st.session_state.selected_test_record = None
                st.rerun()

if __name__ == "__main__":
    main()