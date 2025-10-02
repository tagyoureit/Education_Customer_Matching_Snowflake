# Customer Matching Streamlit Application (v2)

A streamlined Streamlit application for validating and updating customer matches using Snowflake vector similarity, with an Agent Test page wired to Cortex Agents.

## Features

### Core Functionality
- 📊 Dashboard Overview with configurable similarity thresholds
- 📋 Data tables for golden customers and incoming records
- 🧪 Side-by-side workbench with diffs-only highlighting and AI difference explanation
- 🎯 Top-N candidate matches with confidence
- 🔄 Real-time similarity recompute after edits

### Agent Test
- Interact with the Intelligence Agent (tools: text-to-SQL, update test record, AI analysis)
- Streams tool events and partial responses for debugging

## Setup

1. Install Dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Snowflake Connection:
   The app will try to connect using Snow CLI or environment variables:
   ```bash
   export SNOWFLAKE_ACCOUNT=your_account
   export SNOWFLAKE_USER=your_user
   export SNOWFLAKE_PASSWORD=your_password
   export SNOWFLAKE_WAREHOUSE=your_warehouse
   ```

3. Run the Application:
   ```bash
   streamlit run app.py
   ```

## Thresholds
- Exact ≥ 0.995
- Very Close ≥ 0.980
- Somewhat Close ≥ 0.920

## Database Schema (v2)
- `CUSTOMER` (golden)
- `INCOMING_CUSTOMER` (new arrivals)
- `CUSTOMER_IDENTIFIER` (cross-system IDs)
- `CUSTOMER_ADDRESS` (multiple addresses; roles: OFFICE/WAREHOUSE/SCHOOL)
- `CUSTOMER_MATCH_RESULTS` (precomputed similarity outcomes)

Embeddings use `SNOWFLAKE.CORTEX.EMBED_TEXT_768` and similarity uses `VECTOR_COSINE_SIMILARITY`.

## Agent Template
Use the Cortex Agent template as reference: https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents

## Notifications (later)
Email summaries via `SYSTEM$SEND_EMAIL` — see @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures

## SiS Compatibility
- Standard Streamlit components
- Snowflake connector
- No external services required