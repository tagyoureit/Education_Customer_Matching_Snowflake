# MDM Customer Matching — Quick Start (Replication)

This guide helps others replicate the working demo in their own Snowflake account using the Snow CLI default profile.

## Prerequisites

### Snowflake Requirements
- Snow CLI installed and authenticated (default profile)
- Warehouse: `COMPUTE_WH` (or set env var `MDM_WH`)
- **ACCOUNTADMIN role** (for initial database and role setup)
- The setup script will create:
  - Database: `MDM_CUSTOMER_MATCHING`
  - Role: `MDM_CUSTOMER_MATCHING_ROLE` with all necessary privileges
  - Database: `SNOWFLAKE_INTELLIGENCE` (for Cortex Agents)

### Python Requirements
- Python 3.8 or higher
- pip (Python package manager)

---

## 1) One-Time Setup in Target Account

### Automated Setup (Recommended)

Run the setup script from the repo root:

```bash
bash scripts/setup.sh
```

This script executes SQL files in the correct order:
0. `00_CREATE_ROLE_AND_DATABASE.sql` — Creates database, role, and grants (uses ACCOUNTADMIN)
1. `01_MDM_CUSTOMER_MATCHING_ALL.sql` — Creates sequence, UDFs, tables, and Cortex Search services
2. `03_CREATE_ASSIGNMENT_SPS.sql` — Creates stored procedures for identifier assignment
3. `04_CREATE_GENERATE_CUSTOMER_SAMPLES_SP.sql` — Creates sample data generator procedure
4. `05_CREATE_POPULATE_VERIFICATION_MESSAGE_SP.sql` — Creates verification message procedure
5. `06_UPDATE_CUSTOMER_FULL_DETAIL.sql` — Rebuilds canonical text, embeddings, and confidence scores
6. `07_MDM_Matching_Agent.sql` — Creates the MDM Matching Agent

### Manual Setup (Alternative)

If you prefer to run SQL files manually or troubleshoot issues, execute them in this order:

```bash
# 0. Create database and role (requires ACCOUNTADMIN)
snow sql -f SQL/00_CREATE_ROLE_AND_DATABASE.sql

# 1. Core objects (sequence, UDFs, tables, Cortex Search)
snow sql -f SQL/01_MDM_CUSTOMER_MATCHING_ALL.sql

# 2. Stored procedures (required before agent creation)
snow sql -f SQL/03_CREATE_ASSIGNMENT_SPS.sql
snow sql -f SQL/04_CREATE_GENERATE_CUSTOMER_SAMPLES_SP.sql
snow sql -f SQL/05_CREATE_POPULATE_VERIFICATION_MESSAGE_SP.sql

# 3. Update embeddings and confidence scores
snow sql -f SQL/06_UPDATE_CUSTOMER_FULL_DETAIL.sql

# 4. Create the agent
snow sql -f SQL/07_MDM_Matching_Agent.sql
```

---

## 2) Load Snapshot Data (Optional)

If you have snapshot files staged on `@MDM_DEMO_STAGE/exports/`, load them:

```bash
snow sql -f SQL/02_LOAD_DATA.sql
```

This loads `CUSTOMER_ADDRESS` and `CUSTOMER_IDENTIFIER` tables from staged JSON exports.

**Note:** After loading, you should re-run step 3 from the manual setup to regenerate embeddings:

```bash
snow sql -f SQL/06_UPDATE_CUSTOMER_FULL_DETAIL.sql
```

---

## 3) Install Python Dependencies

Create a virtual environment and install required packages:

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate       # macOS/Linux
# OR
venv\Scripts\activate          # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 4) Run the Streamlit App

```bash
streamlit run app.py
```

The app will open in your browser with the following pages:
- **Generate Samples & Assign** — Create test data and auto-assign matches
- **Review New Records** — Manually review and match unprocessed identifiers
- **Customer Lookup** — Search for existing customer records
- **MDM Matching Agent** — Interact with the AI agent for MDM operations

---

## Maintenance Scripts

### `SQL/POPULATE_VERIFICATION_MESSAGE.sql`
This is an ad-hoc maintenance script for regenerating verification messages using deterministic field-by-field comparison (without AI). Run it manually when needed:

```bash
snow sql -f SQL/POPULATE_VERIFICATION_MESSAGE.sql
```

---

## Notes

- **Snowflake Context:** Always include database/schema context in ad-hoc SQL:
  ```sql
  USE DATABASE MDM_CUSTOMER_MATCHING;
  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs
  ```

- **Sequence Alignment (CUSTOMER_BUSINESS_ID):** At the end of `SQL/02_LOAD_DATA.sql`, a Snowflake Scripting block computes the maximum numeric portion of `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS.CUSTOMER_BUSINESS_ID` and recreates `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_BUSINESS_ID_SEQ` starting at the next value. This ensures newly generated IDs continue after the loaded dataset.  -- @Snowflake Docs

- **Data Exports:** Exports are produced with `COPY INTO @MDM_DEMO_STAGE/exports/...` from `OBJECT_CONSTRUCT(...)` selections. Vector embeddings are excluded from exports and recomputed on the target using `SQL/03_UPDATE_CUSTOMER_FULL_DETAIL.sql`.

- **Warehouse Override:** To use a different warehouse, set the `MDM_WH` environment variable before running `setup.sh`:
  ```bash
  export MDM_WH=MY_WAREHOUSE
  bash scripts/setup.sh
  ```

---

## Troubleshooting

- **Permission Errors:** Ensure your role has sufficient privileges for all object types (see Prerequisites)
- **Agent Creation Fails:** Verify that all stored procedures (steps 05-07) were created successfully before running step 04
- **Missing Embeddings:** Run `SQL/03_UPDATE_CUSTOMER_FULL_DETAIL.sql` to regenerate embeddings and confidence scores
- **Python Dependencies:** If you encounter package conflicts, try creating a fresh virtual environment
