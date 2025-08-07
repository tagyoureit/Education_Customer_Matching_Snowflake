"""
Streamlit Customer Matching Application
For MDM Customer Matching validation and updates
"""

import streamlit as st
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas, pd_writer
import os
import uuid
from typing import Dict, List, Tuple, Optional
import toml

# Page configuration
st.set_page_config(
    page_title="Customer Matching Validation",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Constants
DEFAULT_THRESHOLDS = {
    'exact': 0.995,
    'very_close': 0.980,
    'somewhat_close': 0.920
}

@st.cache_resource
def get_snowflake_connection():
    """
    Create Snowflake connection using snow CLI config or environment variables
    """
    try:
        # Try to read from snow CLI connections.toml first
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
                    'warehouse': 'COMPUTE_WH'  # Default warehouse
                }
        else:
            # Fallback to environment variables
            connection_params = {
                'account': os.getenv('SNOWFLAKE_ACCOUNT'),
                'user': os.getenv('SNOWFLAKE_USER'),
                'password': os.getenv('SNOWFLAKE_PASSWORD'),
                'database': 'MDM_CUSTOMER_MATCHING',
                'schema': 'PUBLIC',
                'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH')
            }
            
        # Remove None values
        connection_params = {k: v for k, v in connection_params.items() if v is not None}
        
        return snowflake.connector.connect(**connection_params)
        
    except Exception as e:
        st.error(f"Failed to connect to Snowflake: {str(e)}")
        st.info("Please ensure your snow CLI is configured or set environment variables:")
        st.code("""
        export SNOWFLAKE_ACCOUNT=your_account
        export SNOWFLAKE_USER=your_user  
        export SNOWFLAKE_PASSWORD=your_password
        export SNOWFLAKE_WAREHOUSE=your_warehouse
        """)
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

def create_precomputed_table(_conn):
    """Create the precomputed results table if it doesn't exist"""
    try:
        cursor = _conn.cursor()
        create_sql = """
        CREATE TABLE IF NOT EXISTS CUSTOMER_MATCH_RESULTS (
            VALID_ID VARCHAR(50),
            VALID_CUSTOMER_FULL_DETAIL VARCHAR(1000),
            TEST_ID VARCHAR(50),
            TEST_CUSTOMER_FULL_DETAIL VARCHAR(1000),
            SIMILARITY_SCORE FLOAT,
            MATCH_CATEGORY VARCHAR(20),
            CREATED_TIMESTAMP TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
            UPDATED_TIMESTAMP TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
            PRIMARY KEY (VALID_ID, TEST_ID)
        );
        """
        cursor.execute(create_sql)
        cursor.close()
        return True
    except Exception as e:
        st.error(f"Error creating precomputed table: {str(e)}")
        return False

def compute_similarities(_conn, thresholds: Dict[str, float]) -> pd.DataFrame:
    """Compute or retrieve similarity results with duplicate prevention"""
    try:
        cursor = _conn.cursor()
        
        # Check if precomputed table exists and has data
        check_sql = """
        SELECT COUNT(*) as count FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'PUBLIC' AND TABLE_NAME = 'CUSTOMER_MATCH_RESULTS'
        """
        cursor.execute(check_sql)
        table_exists = cursor.fetchone()[0] > 0
        
        if not table_exists:
            create_precomputed_table(_conn)
            
        # Check if we have the expected amount of data (501 test customers, 1 record each)
        cursor.execute("SELECT COUNT(*) FROM CUSTOMER_MATCH_RESULTS")
        data_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM TEST_MATCHES")
        test_count = cursor.fetchone()[0]
        expected_count = test_count
        
        # Only repopulate if we don't have the right amount of data
        if data_count != expected_count:
            cursor.execute("DELETE FROM CUSTOMER_MATCH_RESULTS")
            # Re-populate with clean data
            populate_sql = """
        INSERT INTO CUSTOMER_MATCH_RESULTS 
        (VALID_ID, VALID_CUSTOMER_FULL_DETAIL, TEST_ID, TEST_CUSTOMER_FULL_DETAIL, SIMILARITY_SCORE, MATCH_CATEGORY)
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
        WHERE v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR IS NOT NULL
        AND t.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY t.SOURCE_PKEY ORDER BY SIMILARITY_SCORE DESC) = 1;
            """
            cursor.execute(populate_sql, (thresholds['exact'], thresholds['very_close'], thresholds['somewhat_close']))

        
        # Load and return results
        results_sql = """
        SELECT * FROM CUSTOMER_MATCH_RESULTS
        ORDER BY SIMILARITY_SCORE DESC
        """
        results = pd.read_sql(results_sql, _conn)
        cursor.close()
        return results
        
    except Exception as e:
        st.error(f"Error computing similarities: {str(e)}")
        return pd.DataFrame()

def get_dashboard_metrics(similarities_df: pd.DataFrame, total_test_customers: int) -> Dict:
    """Calculate dashboard metrics from similarities"""
    if similarities_df.empty:
        return {}
        
    metrics = {}
    
    for category in ['EXACT', 'VERY_CLOSE', 'SOMEWHAT_CLOSE', 'NOT_CLOSE']:
        # Count records in this category
        category_count = len(similarities_df[similarities_df['MATCH_CATEGORY'] == category])
        
        # Calculate percentage: (category matches / total test customers)
        # This shows what % of test customers fall into this match category
        percentage_of_test = (category_count / total_test_customers) * 100 if total_test_customers > 0 else 0
        
        metrics[category] = {
            'count': category_count, 
            'percentage': percentage_of_test
        }
    
    return metrics

def get_top_matches(_conn, test_id: str, thresholds: Dict[str, float], limit: int = 5) -> pd.DataFrame:
    """Get top 5 matching records for a specific test ID using direct query"""
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
        
        # Execute query with thresholds and test_id
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
            # Clean up the AI response
            ai_response = result[0]
            
            # Remove any unwanted prefixes or suffixes
            if "Key Differences:" in ai_response:
                # Find the start of our formatted content
                start_idx = ai_response.find("**Key Differences:**")
                if start_idx != -1:
                    ai_response = ai_response[start_idx:]
            
            # Clean up common AI artifacts
            ai_response = ai_response.replace("\\n", "\n")
            ai_response = ai_response.replace('\\"', '"')
            
            # Ensure proper line breaks for markdown
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
        
        # Create full detail string
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

def create_test_record(_conn, record_data: Dict) -> str:
    """Create new test record with UUID"""
    try:
        cursor = _conn.cursor()
        
        # Generate new UUID
        new_id = f"TEST_{str(uuid.uuid4()).replace('-', '').upper()[:12]}"
        
        insert_sql = """
        INSERT INTO TEST_MATCHES 
        (SOURCE_PKEY, NAME, SOURCE_SYSTEM, ADDRESS_LINE_1, ADDRESS_LINE_2, 
         CITY, STATE, POSTAL_CODE, COUNTRY, CUSTOMER_FULL_DETAIL)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # Create full detail string
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
        
        # Update embedding
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

def recalculate_similarities_for_record(_conn, test_id: str, thresholds: Dict[str, float]):
    """Recalculate similarities for a specific test record"""
    try:
        cursor = _conn.cursor()
        
        # Delete existing similarities for this test record
        delete_sql = "DELETE FROM CUSTOMER_MATCH_RESULTS WHERE TEST_ID = %s"
        cursor.execute(delete_sql, (test_id,))
        
        # Recalculate similarities
        insert_sql = """
        INSERT INTO CUSTOMER_MATCH_RESULTS 
        (VALID_ID, VALID_CUSTOMER_FULL_DETAIL, TEST_ID, TEST_CUSTOMER_FULL_DETAIL, SIMILARITY_SCORE, MATCH_CATEGORY)
        SELECT 
            v.ID as VALID_ID,
            v.CUSTOMER_FULL_DETAIL as VALID_CUSTOMER_FULL_DETAIL,
            t.SOURCE_PKEY as TEST_ID,
            t.CUSTOMER_FULL_DETAIL as TEST_CUSTOMER_FULL_DETAIL,
            VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) as SIMILARITY_SCORE,
            CASE 
                WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= %s THEN 'EXACT'
                WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= %s THEN 'VERY_CLOSE'
                WHEN VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING, t.CUSTOMER_FULL_DETAIL_EMBEDDING) >= %s THEN 'SOMEWHAT_CLOSE'
                ELSE 'NOT_CLOSE'
            END as MATCH_CATEGORY
        FROM VALID_CUSTOMERS v
        CROSS JOIN TEST_MATCHES t
        WHERE t.SOURCE_PKEY = %s
        AND v.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL 
        AND t.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL
        """
        
        cursor.execute(insert_sql, (
            thresholds['exact'],
            thresholds['very_close'], 
            thresholds['somewhat_close'],
            test_id
        ))
        
        cursor.close()
        return True
        
    except Exception as e:
        st.error(f"Error recalculating similarities: {str(e)}")
        return False

def main():
    st.title("🔍 Customer Matching Validation System")
    st.markdown("Validate and update potential customer matches using vector similarity")
    
    # Initialize session state
    if 'thresholds' not in st.session_state:
        st.session_state.thresholds = DEFAULT_THRESHOLDS.copy()
    if 'selected_test_record' not in st.session_state:
        st.session_state.selected_test_record = None
    if 'form_data' not in st.session_state:
        st.session_state.form_data = {}
    
    # Get Snowflake connection
    conn = get_snowflake_connection()
    
    # Sidebar for threshold configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.subheader("Similarity Thresholds")
        
        new_thresholds = {}
        new_thresholds['exact'] = st.slider(
            "Exact Match (≥)", 
            min_value=0.90, max_value=1.0, 
            value=st.session_state.thresholds['exact'], 
            step=0.001, format="%.3f"
        )
        new_thresholds['very_close'] = st.slider(
            "Very Close (≥)", 
            min_value=0.90, max_value=0.99, 
            value=st.session_state.thresholds['very_close'], 
            step=0.001, format="%.3f"
        )
        new_thresholds['somewhat_close'] = st.slider(
            "Somewhat Close (≥)", 
            min_value=0.80, max_value=0.95, 
            value=st.session_state.thresholds['somewhat_close'], 
            step=0.001, format="%.3f"
        )
        
        # Auto-update thresholds when changed
        if new_thresholds != st.session_state.thresholds:
            st.session_state.thresholds = new_thresholds
            st.rerun()
    
    # Load data
    with st.spinner("Loading data..."):
        valid_customers = load_valid_customers(conn)
        test_matches = load_test_matches(conn)
        similarities = compute_similarities(conn, st.session_state.thresholds)
    
    # Dashboard Overview
    st.header("📊 Dashboard Overview")
    
    if not similarities.empty:
        metrics = get_dashboard_metrics(similarities, len(test_matches))
        
        # Create columns for the layout
        col_totals, col_spacer, col_matches = st.columns([2, 0.2, 4])
        
        # Total customers box (subtle border)
        with col_totals:
            st.markdown(f"""
            <div style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; background-color: #fafafa;">
                <div style="display: flex; justify-content: space-around;">
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Total Valid Customers</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{len(valid_customers)}</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Total Test Customers</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{len(test_matches)}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Match categories box (subtle border)
        with col_matches:
            st.markdown(f"""
            <div style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; background-color: #fafafa;">
                <div style="display: flex; justify-content: space-around;">
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Exact Matches</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{metrics['EXACT']['count']}</div>
                        <div style="font-size: 12px; color: #09ab3b;">{metrics['EXACT']['percentage']:.1f}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Very Close</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{metrics['VERY_CLOSE']['count']}</div>
                        <div style="font-size: 12px; color: #ffa500;">{metrics['VERY_CLOSE']['percentage']:.1f}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Somewhat Close</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{metrics['SOMEWHAT_CLOSE']['count']}</div>
                        <div style="font-size: 12px; color: #ffde21;">{metrics['SOMEWHAT_CLOSE']['percentage']:.1f}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 14px; color: #666; margin-bottom: 4px;">Not Close</div>
                        <div style="font-size: 28px; font-weight: bold; color: #1f1f1f;">{metrics['NOT_CLOSE']['count']}</div>
                        <div style="font-size: 12px; color: #ff0000;">{metrics['NOT_CLOSE']['percentage']:.1f}%</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    

    
    # Main content area
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        # Table Views
        st.header("📋 Customer Data")
        
        tab1, tab2 = st.tabs(["Valid Customers", "Test Customers"])
        
        with tab1:
            st.subheader("Valid Customers")
            if not valid_customers.empty:
                # Show only customer_full_detail and id columns in that order
                display_valid = valid_customers[['CUSTOMER_FULL_DETAIL', 'ID']].copy()
                st.dataframe(
                    display_valid,
                    height=300,
                    use_container_width=True
                )
        
        with tab2:
            # Filter Controls (define first for logic, display later)
            selected_categories = st.multiselect(
                "🔍 Filter by Match Category:",
                options=["EXACT", "VERY_CLOSE", "SOMEWHAT_CLOSE", "NOT_CLOSE"],
                default=["EXACT", "VERY_CLOSE", "SOMEWHAT_CLOSE", "NOT_CLOSE"],
                help="Select which match categories to show in the Test Customers table",
                key="category_filter"
            )
            
            if not test_matches.empty:
                # Calculate current display count for header
                if selected_categories and not similarities.empty:
                    test_with_categories = test_matches.merge(
                        similarities[['TEST_ID', 'MATCH_CATEGORY', 'VALID_ID']], 
                        left_on='SOURCE_PKEY', 
                        right_on='TEST_ID', 
                        how='left'
                    )
                    filtered_count = len(test_with_categories[
                        test_with_categories['MATCH_CATEGORY'].isin(selected_categories)
                    ])
                else:
                    filtered_count = len(test_matches)
                
                st.subheader(f"Test Customers ({filtered_count} of {len(test_matches)})")
            else:
                st.subheader("Test Customers (0)")
            st.markdown("Click on the check box next to a row to edit it.")
            if not test_matches.empty:
                # Filter test_matches based on selected categories (reuse the merge from header calculation)
                if selected_categories and not similarities.empty:
                    # Filter based on selected categories
                    filtered_test_matches = test_with_categories[
                        test_with_categories['MATCH_CATEGORY'].isin(selected_categories)
                    ]
                    # Create display with valid customer ID appended
                    display_df = filtered_test_matches[['CUSTOMER_FULL_DETAIL', 'SOURCE_PKEY']].copy()
                    # Add valid customer ID to the end of the customer detail string
                    if 'VALID_ID' in test_with_categories.columns:
                        display_df['CUSTOMER_FULL_DETAIL'] = (
                            filtered_test_matches['CUSTOMER_FULL_DETAIL'].astype(str) 
                        )
                    # Keep the filtered dataframe for row selection
                    current_test_matches = filtered_test_matches
                else:
                    # No filter or no similarities - show all
                    display_df = test_matches[['CUSTOMER_FULL_DETAIL']].copy()
                    current_test_matches = test_matches
                

                
                selected_rows = st.dataframe(
                    display_df,
                    height=300,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="single-row"
                )
                
                # Handle row selection
                if selected_rows['selection']['rows']:
                    selected_idx = selected_rows['selection']['rows'][0]
                    selected_record = current_test_matches.iloc[selected_idx]
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
                else:
                    # No row selected - clear the form and current record
                    st.session_state.selected_test_record = None
                    st.session_state.form_data = {}
        
        # Top 5 Matches Display (when a record is selected)
        if st.session_state.get('selected_test_record') is not None:
            record = st.session_state.selected_test_record
            st.header("🎯 Top 5 Matches")
            top_matches = get_top_matches(conn, record['SOURCE_PKEY'], st.session_state.thresholds)
            
            if not top_matches.empty:
                # Display all matches first for immediate feedback
                for idx, match in top_matches.iterrows():
                    similarity_pct = match['SIMILARITY_SCORE'] * 100
                    match_category = match['MATCH_CATEGORY']
                    # Color code based on match category
                    if match_category == 'EXACT':
                        color = "🟢"
                    elif match_category == 'VERY_CLOSE':
                        color = "🟡"
                    elif match_category == 'SOMEWHAT_CLOSE':
                        color = "🟠"
                    else:
                        color = "🔴"
                    
                    st.write(f"{color} **{similarity_pct:.2f}%** ({match_category}) - {match['VALID_CUSTOMER_FULL_DETAIL']} | Valid ID: {match['VALID_ID']}")
                
                # Add AI analysis for the top match after showing all matches
                st.subheader("🤖 AI Analysis - Top Match")
                top_match = top_matches.iloc[0]
                
                # Create a placeholder for the AI analysis
                analysis_placeholder = st.empty()
                analysis_placeholder.info("🔄 Loading AI analysis...")
                
                # Get AI analysis and update placeholder
                ai_analysis = get_ai_analysis(conn, record['SOURCE_PKEY'], top_match['VALID_ID'])
                
                # Clear placeholder and show results
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
            
            # Helper function to build customer details string
            def build_customer_details(name_val, source_val, addr1_val, addr2_val, city_val, state_val, postal_val, country_val):
                """Build customer full details string like COALESCE insert statement"""
                # Use current form values or fall back to form_data, then empty string
                details_parts = []
                if name_val or form_data.get('NAME', ''): 
                    details_parts.append(f"Name: {name_val or form_data.get('NAME', '')}")
                if source_val or form_data.get('SOURCE_SYSTEM', ''): 
                    details_parts.append(f"Source: {source_val or form_data.get('SOURCE_SYSTEM', '')}")
                if addr1_val or form_data.get('ADDRESS_LINE_1', ''): 
                    details_parts.append(f"Address1: {addr1_val or form_data.get('ADDRESS_LINE_1', '')}")
                if addr2_val or form_data.get('ADDRESS_LINE_2', ''): 
                    details_parts.append(f"Address2: {addr2_val or form_data.get('ADDRESS_LINE_2', '')}")
                if city_val or form_data.get('CITY', ''): 
                    details_parts.append(f"City: {city_val or form_data.get('CITY', '')}")
                if state_val or form_data.get('STATE', ''): 
                    details_parts.append(f"State: {state_val or form_data.get('STATE', '')}")
                if postal_val or form_data.get('POSTAL_CODE', ''): 
                    details_parts.append(f"Postal: {postal_val or form_data.get('POSTAL_CODE', '')}")
                if country_val or form_data.get('COUNTRY', ''): 
                    details_parts.append(f"Country: {country_val or form_data.get('COUNTRY', '')}")
                return " | ".join(details_parts)
            
            # Current record display (if editing)
            if st.session_state.get('selected_test_record') is not None:
                current_details = st.session_state.selected_test_record.get('CUSTOMER_FULL_DETAIL', '')
                st.text_input("📋 Current Full Customer Details (from DB)", value=current_details, disabled=True)

            
            # Row 1: ID and Name
            col1a, col1b = st.columns([1, 2])
            with col1a:
                id_value = st.text_input("ID", value=form_data.get('SOURCE_PKEY', ''), disabled=True)
            with col1b:
                name = st.text_input("Name", value=form_data.get('NAME', ''))
            
            # Row 2: Source System and Address Line 1
            col2a, col2b = st.columns([1, 2])
            with col2a:
                source_system = st.text_input("Source", value=form_data.get('SOURCE_SYSTEM', ''))
            with col2b:
                address1 = st.text_input("Address 1", value=form_data.get('ADDRESS_LINE_1', ''))
            
            # Row 3: Address Line 2
            address2 = st.text_input("Address 2", value=form_data.get('ADDRESS_LINE_2', ''))
            
            # Row 4: City, State, Postal Code
            col4a, col4b, col4c = st.columns([2, 1, 1])
            with col4a:
                city = st.text_input("City", value=form_data.get('CITY', ''))
            with col4b:
                state = st.text_input("State", value=form_data.get('STATE', ''))
            with col4c:
                postal_code = st.text_input("Postal", value=form_data.get('POSTAL_CODE', ''))
            
            # Row 5: Country
            country = st.text_input("Country", value=form_data.get('COUNTRY', ''))
            
            # New customer details preview (reactive to form changes)
            new_details = build_customer_details(
                name or '', source_system or '', address1 or '', address2 or '', 
                city or '', state or '', postal_code or '', country or ''
            )
                        
            # Buttons
            col5b, col5c = st.columns([1, 1])
            with col5b:
                submitted = st.form_submit_button("💾 Save to Test Customers Table", use_container_width=True)
            with col5c:
                new_record = st.form_submit_button("🆕 Clear Form", use_container_width=True)
            
            if submitted:
                # Validate required fields
                if not (name or '').strip():
                    st.error("❌ Name is required")
                elif not (source_system or '').strip():
                    st.error("❌ Source System is required")
                else:
                    # Prepare record data (safely handle None values)
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
                    if id_value:  # Update existing record
                        success = update_test_record(conn, record_data)
                        if success:
                            st.success("✅ Record updated successfully!")
                            # Recalculate similarities for this record
                            if recalculate_similarities_for_record(conn, id_value, st.session_state.thresholds):
                                st.success("🔄 Similarities recalculated")
                            # Clear caches to refresh data
                            st.cache_data.clear()
                    else:  # Create new record
                        new_id = create_test_record(conn, record_data)
                        if new_id:
                            st.success(f"✅ New record created with ID: {new_id}")
                            # Update form to show new ID
                            st.session_state.form_data['SOURCE_PKEY'] = new_id
                            # Recalculate similarities for new record
                            if recalculate_similarities_for_record(conn, new_id, st.session_state.thresholds):
                                st.success("🔄 Similarities calculated for new record")
                            # Clear caches to refresh data
                            st.cache_data.clear()
                            success = True
                    
                    if success:
                        st.rerun()
                
            if new_record:
                # Clear form
                st.session_state.form_data = {}
                st.session_state.selected_test_record = None
                st.rerun()
        


if __name__ == "__main__":
    main()