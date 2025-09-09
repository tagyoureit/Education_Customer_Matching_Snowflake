"""
Customer Matching Streamlit Application - Main Dashboard
For MDM Customer Matching validation and updates
"""

import streamlit as st
import pandas as pd
import snowflake.connector
import os
from typing import Dict
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
    """Create Snowflake connection using snow CLI config or environment variables"""
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
                    'warehouse': 'COMPUTE_WH'
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
        st.stop()

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
        
        # Get match categories breakdown
        matches_query = """
        SELECT 
            MATCH_CATEGORY,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM CUSTOMER_MATCH_RESULTS), 2) as percentage
        FROM CUSTOMER_MATCH_RESULTS
        GROUP BY MATCH_CATEGORY
        ORDER BY count DESC
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
    st.title("🔍 Customer Matching Validation System")
    st.markdown("Validate and update potential customer matches using vector similarity")
    
    # Initialize session state
    if 'thresholds' not in st.session_state:
        st.session_state.thresholds = DEFAULT_THRESHOLDS.copy()
    
    # Get Snowflake connection
    conn = get_snowflake_connection()
    
    # Sidebar for threshold configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.subheader("Similarity Thresholds")
        
        st.session_state.thresholds['exact'] = st.slider(
            "Exact Match (≥)", 
            min_value=0.90, max_value=1.0, 
            value=st.session_state.thresholds['exact'], 
            step=0.001, format="%.3f"
        )
        st.session_state.thresholds['very_close'] = st.slider(
            "Very Close (≥)", 
            min_value=0.90, max_value=0.99, 
            value=st.session_state.thresholds['very_close'], 
            step=0.001, format="%.3f"
        )
        st.session_state.thresholds['somewhat_close'] = st.slider(
            "Somewhat Close (≥)", 
            min_value=0.80, max_value=0.95, 
            value=st.session_state.thresholds['somewhat_close'], 
            step=0.001, format="%.3f"
        )
    
    # Load dashboard data
    with st.spinner("Loading dashboard data..."):
        dashboard_data = get_dashboard_data(conn)
    
    if dashboard_data:
        # Dashboard Overview
        st.header("📊 Dashboard Overview")
        
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        matches_df = dashboard_data['matches_df']
        
        with col1:
            st.metric("Total Valid Customers", dashboard_data['valid_count'])
        
        with col2:
            st.metric("Total Test Customers", dashboard_data['test_count'])
        
        if not matches_df.empty:
            exact_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'EXACT']
            very_close_matches = matches_df[matches_df['MATCH_CATEGORY'] == 'VERY_CLOSE']
            
            with col3:
                exact_count = exact_matches.iloc[0]['COUNT'] if not exact_matches.empty else 0
                exact_pct = exact_matches.iloc[0]['PERCENTAGE'] if not exact_matches.empty else 0
                st.metric("Exact Matches", exact_count, f"{exact_pct}%")
            
            with col4:
                vc_count = very_close_matches.iloc[0]['COUNT'] if not very_close_matches.empty else 0
                vc_pct = very_close_matches.iloc[0]['PERCENTAGE'] if not very_close_matches.empty else 0
                st.metric("Very Close Matches", vc_count, f"{vc_pct}%")
        
        # Match categories breakdown
        st.subheader("📈 Match Categories Breakdown")
        
        if not matches_df.empty:
            col_chart, col_table = st.columns([2, 1])
            
            with col_chart:
                chart_data = matches_df.set_index('MATCH_CATEGORY')['COUNT']
                st.bar_chart(chart_data)
            
            with col_table:
                display_df = matches_df.copy()
                display_df['MATCH_CATEGORY'] = display_df['MATCH_CATEGORY'].str.replace('_', ' ').str.title()
                st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Navigation information
    st.header("🧭 Navigation")
    st.info("""
    **Use the sidebar to navigate between pages:**
    
    📋 **Data View** - Browse customers, edit records, view top matches and AI analysis
    
    💬 **Chat View** - Ask natural language questions about your data and get AI-powered insights
    """)
    
    # Quick actions
    st.header("🚀 Quick Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📋 Go to Data View", use_container_width=True):
            st.switch_page("pages/1_📋_Data_View.py")
    
    with col2:
        if st.button("💬 Go to Chat View", use_container_width=True):
            st.switch_page("pages/2_💬_Chat_View.py")

if __name__ == "__main__":
    main()