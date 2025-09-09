# Customer Matching Streamlit Application

A Streamlit application for validating and updating customer matching results using Snowflake vector similarity, now with AI-powered chatbot assistance.

## Features

### Core Functionality
- 📊 **Dashboard Overview**: Real-time metrics with configurable similarity thresholds
- 📋 **Data Tables**: Browse valid customers and test matches
- ✏️ **Form Interface**: Edit existing records or create new ones
- 🎯 **Match Analysis**: View top 5 matches with similarity scores
- 🔄 **Real-time Updates**: Automatic similarity recalculation after changes

### 🤖 NEW: AI Chatbot Assistant
- 💬 **Natural Language Queries**: Ask questions about your data in plain English
- 📝 **Inline Editing**: Edit customer records directly from chat
- 🎯 **Smart Match Display**: Get top matches for specific customers
- 🔍 **AI Analysis**: Understand why records are different
- 📊 **Data Insights**: Get summaries and breakdowns via conversation

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Snowflake Connection**:
   The app will try to connect using:
   - Snow CLI configuration (`~/.snowflake/connections.toml`)
   - Or environment variables:
     ```bash
     export SNOWFLAKE_ACCOUNT=your_account
     export SNOWFLAKE_USER=your_user
     export SNOWFLAKE_PASSWORD=your_password
     export SNOWFLAKE_WAREHOUSE=your_warehouse
     ```

3. **Configure Secrets (PAT and Account)**:
   Create `.streamlit/secrets.toml` with your Snowflake account and PAT. The PAT is used via Bearer auth for the Cortex Agents REST API.
   ```toml
   [snowflake]
   account = "<ACCOUNT_NAME>"   # e.g. SFSENORTHAMERICA-RGOLDIN-AWS1
   password = "<PROGRAMMATIC_ACCESS_TOKEN>"  # PAT value
   ```
   Notes:
   - We read `account` to derive the host by default: `<account>.snowflakecomputing.com`.
   - We read `password` as PAT. You can also set `CORTEX_AGENT_DEMO_PAT` in the environment.

4. **Run the Application**:
   ```bash
   streamlit run app.py
   ```

## Usage

### Configurable Thresholds
- Use the sidebar to adjust similarity thresholds
- Click "Recompute Results" to update match categories
- Default thresholds based on analysis:
  - Exact: ≥0.995
  - Very Close: ≥0.980  
  - Somewhat Close: ≥0.920

### Customer Management
- Click rows in the "Test Customers" table to load into the form
- Edit fields and click "Submit" to update existing records
- Click "New" to clear the form for creating new records
- New records automatically get a UUID-based ID

### Match Analysis
- Select a test customer to see similarity score
- View top 5 matching valid customers with percentages
- Real-time updates after editing customer data

### 🤖 Chatbot Assistant
- Navigate to the "💬 Chat View" tab
- Ask questions like:
  - "Which test customers are exact matches?"
  - "Show me top 5 matches for TEST_001"
  - "Let me edit a test_match record"
  - "Why are these records different?"
- Use example questions to get started
- Edit records inline with chat forms
- Export chat history for reference

### 🧪 Agent Test (Cortex Agents REST)
- Navigate to the "🧪 Agent Test" tab.
- Set Host and confirm PAT is loaded from secrets. Default Agent is `SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT`.
- Threads: a thread is auto-created (<=16 byte origin) and its `thread_id` is shown. Reset as needed.
- Streaming: both assistant text and "Thinking" stream in real-time. "Thinking" appears above the final response.
- Tools: the agent triggers server-side tools; tool events are visible under "ℹ️ Request Debug".
- Charts/Tables: if the agent emits `response.chart`/`response.table`, these render inline under the answer.

For detailed chatbot usage, see [Chatbot_User_Guide.md](Chatbot_User_Guide.md)

## Database Schema

The application uses these Snowflake tables:
- `VALID_CUSTOMERS`: Reference customer data
- `TEST_MATCHES`: Incoming customer data to validate
- `CUSTOMER_MATCH_RESULTS`: Precomputed similarity results

### New: Chatbot Infrastructure
- `SEMANTIC_MODELS` stage: Stores Cortex Analyst semantic model files
- `customer_matching_semantic_model.yaml`: Semantic model defining data relationships for AI queries

## Streamlit in Snowflake (SiS) Compatibility

The application is designed to be compatible with Streamlit in Snowflake:
- Uses standard Streamlit components
- Snowflake connector integration
- No external dependencies beyond Snowflake ecosystem