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

# Import shared utilities
from shared_utils import recalculate_all_similarities, DEFAULT_THRESHOLDS

@st.cache_data
def get_dashboard_data(_conn):
    """Load summary data for dashboard"""
    try:
        # First check if CUSTOMER_MATCH_RESULTS has any data
        check_query = "SELECT COUNT(*) FROM CUSTOMER_MATCH_RESULTS"
        result_count = pd.read_sql(check_query, _conn).iloc[0, 0]
        
        # If no results exist, recalculate everything using the shared function
        if result_count == 0:
            st.info("🔄 No similarity results found. Running initial calculation...")
            if recalculate_all_similarities(_conn, DEFAULT_THRESHOLDS):
                st.success("✅ Similarity calculation completed!")
            else:
                st.error("❌ Failed to calculate similarities")
                return None
        
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
            st.header("📊 Key Performance Indicators")
            
            # Key metrics - now with 6 columns for all categories
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            
            matches_df = dashboard_data['matches_df']
            
            with col1:
                st.metric("Total Valid Customers", dashboard_data['valid_count'])
                st.markdown("<br>", unsafe_allow_html=True)  # Add blank space
            
            with col2:
                st.metric("Total Test Customers", dashboard_data['test_count'])
                st.markdown("<br>", unsafe_allow_html=True)  # Add blank space
        
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
                 # Match categories breakdown

         
            if not matches_df.empty:
                # Create columns to align chart with colored KPIs (skip first 2 columns)
                chart_col1, chart_col2 = st.columns([1, 2])
                
                with chart_col2:  # Chart goes in right column to align with colored KPIs
                    # Show the Plotly chart aligned with KPIs above
                    import plotly.graph_objects as go
                    import plotly.express as px
                    

                    # Clean up category names for display
                    display_matches_df = matches_df.copy()
                    display_matches_df['DISPLAY_CATEGORY'] = display_matches_df['MATCH_CATEGORY'].str.replace('_', ' ').str.title()
                    
                    # Create bar chart with labels and custom colors
                    # Green=Exact, Orange=Very Close, Yellow=Somewhat Close, Red=Not Close
                    color_map = {
                        'Exact': '#28a745',           # Green
                        'Very Close': '#fd7e14',      # Orange  
                        'Somewhat Close': '#ffc107',  # Yellow
                        'Not Close': '#dc3545'        # Red
                    }
                    
                    fig = px.bar(
                        display_matches_df, 
                        x='DISPLAY_CATEGORY', 
                        y='COUNT',
                        text='PERCENTAGE',
                        title="Match Categories Distribution",
                        color='DISPLAY_CATEGORY',
                        color_discrete_map=color_map
                    )
                    
                    # Update text template to show percentage
                    fig.update_traces(texttemplate='%{text}%', textposition='outside')
                    
                    # Ensure proper ordering on x-axis
                    fig.update_xaxes(categoryorder='array', categoryarray=['Exact', 'Very Close', 'Somewhat Close', 'Not Close'])
                    
                    # Update layout
                    fig.update_layout(
                        showlegend=False,
                        xaxis_title="Match Category",
                        yaxis_title="Count",
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
        
        # Navigation information
        st.header("🧭 Navigation")
        st.info("""
        **Use the sidebar to navigate to:**
        
        📋 **Data View** - Browse customers, edit records, view top matches and AI analysis
        """)
        
        # Quick actions
        st.header("🚀 Quick Actions")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📋 Go to Data View", use_container_width=True):
                st.switch_page("pages/1_📋_Data_View.py")
        
        # Chat View is not included in this package

if __name__ == "__main__":
    main()