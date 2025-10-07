#!/usr/bin/env bash
set -euo pipefail

# Setup MDM demo schema, objects, and services in target account using Snow CLI default profile
# Requirements:
# - snow CLI installed and authenticated (default profile)
# - Warehouse COMPUTE_WH available or override via MDM_WH env var

WH=${MDM_WH:-COMPUTE_WH}

echo "==> Setting up MDM Customer Matching environment..."

# 0. Create database, role, and grant permissions (requires ACCOUNTADMIN)
echo "==> Creating database and role with ACCOUNTADMIN privileges..."
snow sql -f SQL/00_CREATE_ROLE_AND_DATABASE.sql

# Switch to MDM role for remaining operations
echo "==> Switching to MDM_CUSTOMER_MATCHING_ROLE..."
snow sql -q "USE ROLE MDM_CUSTOMER_MATCHING_ROLE;"

# Ensure stage and file format exist (for data reloads)
echo "==> Creating stage and file format..."
snow sql -q "USE ROLE MDM_CUSTOMER_MATCHING_ROLE; USE DATABASE MDM_CUSTOMER_MATCHING; USE SCHEMA PUBLIC; USE WAREHOUSE ${WH}; CREATE STAGE IF NOT EXISTS MDM_DEMO_STAGE; CREATE FILE FORMAT IF NOT EXISTS MDM_JSONL_FF TYPE=JSON COMPRESSION=GZIP;"

# 1. Create sequence, UDFs, tables, and Cortex Search services
echo "==> Running 01_MDM_CUSTOMER_MATCHING_ALL.sql (tables, sequence, UDFs, Cortex Search)..."
snow sql -f SQL/01_MDM_CUSTOMER_MATCHING_ALL.sql

# 2. Create stored procedures for agent operations (must run before agent creation)
echo "==> Running 03_CREATE_ASSIGNMENT_SPS.sql (stored procedures)..."
snow sql -f SQL/03_CREATE_ASSIGNMENT_SPS.sql

echo "==> Running 04_CREATE_GENERATE_CUSTOMER_SAMPLES_SP.sql (sample generator)..."
snow sql -f SQL/04_CREATE_GENERATE_CUSTOMER_SAMPLES_SP.sql

echo "==> Running 05_CREATE_POPULATE_VERIFICATION_MESSAGE_SP.sql (verification message SP)..."
snow sql -f SQL/05_CREATE_POPULATE_VERIFICATION_MESSAGE_SP.sql

# 3. Rebuild canonical text/embeddings and confidence field logic (safe to run any time)
echo "==> Running 06_UPDATE_CUSTOMER_FULL_DETAIL.sql (embeddings and confidence scores)..."
snow sql -f SQL/06_UPDATE_CUSTOMER_FULL_DETAIL.sql

# 4. Create the MDM Matching Agent (depends on stored procedures from steps above)
echo "==> Running 07_MDM_Matching_Agent.sql (agent creation)..."
snow sql -f SQL/07_MDM_Matching_Agent.sql

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. If you have snapshot data on @MDM_DEMO_STAGE/exports/, run:"
echo "     snow sql -f SQL/02_LOAD_DATA.sql"
echo ""
echo "  2. Install Python dependencies and run the Streamlit app:"
echo "     python -m venv venv"
echo "     source venv/bin/activate  # or venv\\Scripts\\activate on Windows"
echo "     pip install -r requirements.txt"
echo "     streamlit run app.py"
echo ""


