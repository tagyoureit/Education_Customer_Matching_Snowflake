### Minimal Customer Package: Streamlit Data View + Dashboard

This package includes only the main dashboard (`app.py`) and the data view page (`pages/1_📋_Data_View.py`) with shared utilities (`shared_utils.py`) and two sample datasets in `data/`.

Included components:
- `app.py`
- `pages/1_📋_Data_View.py`
- `shared_utils.py`
- `data/valid_customers_0_0_0.csv.gz`
- `data/test_matches_0_0_0.csv.gz`
- `requirements.txt`

Notes:
- The Chat View is intentionally removed from navigation in this package.
- All Snowflake object names are uppercase by convention.

---

### 1) Prerequisites
- Python 3.9+
- Snowflake account with Cortex features enabled (Cortex Functions and VECTOR support)
- A warehouse (uses `COMPUTE_WH` by default)
- Access and privileges to create tables, stages, and run COPY INTO

---

### 2) Python setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### 3) Configure Snowflake connection
The app first tries `~/.snowflake/connections.toml` (default profile), then falls back to environment variables.

Option A — Default Snow CLI profile (`~/.snowflake/connections.toml`):
```toml
[default]
account = "<ACCOUNT_NAME>"
user = "<USERNAME>"
password = "<PASSWORD>"
```

Option B — Environment variables:
```bash
export SNOWFLAKE_ACCOUNT=<ACCOUNT_NAME>
export SNOWFLAKE_USER=<USERNAME>
export SNOWFLAKE_PASSWORD=<PASSWORD>
export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
```

---

### 4) Snowflake setup (DDL, stages, load)
All commands below are designed for the Snowflake SQL worksheet or Snow CLI. Always run `USE DATABASE` and `USE SCHEMA` first.

References: @Snowflake Docs — `CREATE TABLE`, `VECTOR`, `COPY INTO`, `FILE FORMAT`, `STAGE`, `SNOWFLAKE.CORTEX.EMBED_TEXT_768`, `VECTOR_COSINE_SIMILARITY`, `AI_COMPLETE`.

```sql
-- Context
USE WAREHOUSE COMPUTE_WH;
CREATE DATABASE IF NOT EXISTS MDM_CUSTOMER_MATCHING;
USE DATABASE MDM_CUSTOMER_MATCHING;
CREATE SCHEMA IF NOT EXISTS PUBLIC;
USE SCHEMA PUBLIC;

-- Internal stage for loading gzipped CSV files
CREATE STAGE IF NOT EXISTS RAW_DATA;

-- File format for quoted CSV with possible embedded newlines
CREATE OR REPLACE FILE FORMAT CSV_GZ_FMT
  TYPE = CSV
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 0
  COMPRESSION = GZIP
  NULL_IF = ('', 'NULL');

-- Tables required by the app

-- VALID_CUSTOMERS: includes an embedding VECTOR for similarity and an IS_ACTIVE flag
CREATE OR REPLACE TABLE VALID_CUSTOMERS (
  ID STRING,
  IS_ACTIVE BOOLEAN,
  SOURCE_PKEY STRING,
  NAME STRING,
  SOURCE_SYSTEM STRING,
  ADDRESS_LINE_1 STRING,
  ADDRESS_LINE_2 STRING,
  CITY STRING,
  STATE STRING,
  POSTAL_CODE STRING,
  COUNTRY STRING,
  CUSTOMER_FULL_DETAIL STRING,
  CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR VECTOR(FLOAT, 768)
);

-- TEST_MATCHES: includes an embedding VECTOR for similarity
CREATE OR REPLACE TABLE TEST_MATCHES (
  SOURCE_PKEY STRING,
  NAME STRING,
  SOURCE_SYSTEM STRING,
  ADDRESS_LINE_1 STRING,
  ADDRESS_LINE_2 STRING,
  CITY STRING,
  STATE STRING,
  POSTAL_CODE STRING,
  COUNTRY STRING,
  CUSTOMER_FULL_DETAIL STRING,
  CUSTOMER_FULL_DETAIL_EMBEDDING VECTOR(FLOAT, 768)
);

-- CUSTOMER_MATCH_RESULTS: populated by the app via INSERT SELECT
CREATE OR REPLACE TABLE CUSTOMER_MATCH_RESULTS (
  VALID_ID STRING,
  VALID_CUSTOMER_FULL_DETAIL STRING,
  TEST_ID STRING,
  TEST_CUSTOMER_FULL_DETAIL STRING,
  SIMILARITY_SCORE FLOAT,
  MATCH_CATEGORY STRING
);
```

Upload the compressed CSV files to the internal stage using Snow CLI:
```bash
# from the project root
snow stage copy file://./data/valid_customers_0_0_0.csv.gz @MDM_CUSTOMER_MATCHING.PUBLIC.RAW_DATA --overwrite
snow stage copy file://./data/test_matches_0_0_0.csv.gz @MDM_CUSTOMER_MATCHING.PUBLIC.RAW_DATA --overwrite
```

Load data into tables (column order is explicit; we are not relying on headers):
```sql
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- Load VALID_CUSTOMERS (12 CSV fields → see column list)
COPY INTO VALID_CUSTOMERS (
  ID,
  IS_ACTIVE,
  SOURCE_PKEY,
  NAME,
  SOURCE_SYSTEM,
  ADDRESS_LINE_1,
  ADDRESS_LINE_2,
  CITY,
  STATE,
  POSTAL_CODE,
  COUNTRY,
  CUSTOMER_FULL_DETAIL
)
FROM @RAW_DATA/valid_customers_0_0_0.csv.gz
FILE_FORMAT = (FORMAT_NAME = CSV_GZ_FMT);

-- Load TEST_MATCHES (10 CSV fields → see column list)
COPY INTO TEST_MATCHES (
  SOURCE_PKEY,
  NAME,
  SOURCE_SYSTEM,
  ADDRESS_LINE_1,
  ADDRESS_LINE_2,
  CITY,
  STATE,
  POSTAL_CODE,
  COUNTRY,
  CUSTOMER_FULL_DETAIL
)
FROM @RAW_DATA/test_matches_0_0_0.csv.gz
FILE_FORMAT = (FORMAT_NAME = CSV_GZ_FMT);
```

Prepare embeddings (required before first app run):
```sql
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- VALID_CUSTOMERS embedding (used on the left side of similarity)
UPDATE VALID_CUSTOMERS
SET CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL);

-- TEST_MATCHES embedding (used on the right side of similarity)
UPDATE TEST_MATCHES
SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL);
```

Validation checks (optional):
```sql
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

SELECT COUNT(*) FROM VALID_CUSTOMERS;
SELECT COUNT(*) FROM TEST_MATCHES;
SELECT VECTOR_DIMS(CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR) FROM VALID_CUSTOMERS WHERE CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR IS NOT NULL LIMIT 1;
SELECT VECTOR_DIMS(CUSTOMER_FULL_DETAIL_EMBEDDING) FROM TEST_MATCHES WHERE CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL LIMIT 1;
```

---

### 5) Snowflake Intelligence Agent setup (required)
The demo assumes an Intelligence Agent named `SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT` exists.

1. Validate Intelligence Agent support and presence:
```sql
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- Optional: list agents if supported
SHOW CORTEX AGENTS;

-- Validate the specific agent
DESCRIBE AGENT SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT;
```

2. If the agent does not exist, create it using the exact SQL from the Snowflake Intelligence Preview guide, then re-run the DESCRIBE to confirm. See:
- [Snowflake Intelligence Preview — Feature Overview](https://github.com/sfc-gh-jhollan/snowflake-intelligence-preview-guide/blob/main/3_feature_overview.md)

References: @Snowflake Docs — Intelligence Agents, DESCRIBE AGENT.

---

### 6) Supporting stored programs (required by the agent)
Create the stored function and procedure referenced by the agent tools.

```sql
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- Stored function: GET_AI_ANALYSIS(VARCHAR, VARCHAR) → VARCHAR
CREATE OR REPLACE FUNCTION GET_AI_ANALYSIS(P_TEST_ID VARCHAR, P_VALID_ID VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
SELECT AI_COMPLETE('llama3.3-70b',
  'Compare these customer records. Return ONLY properly formatted markdown with no extra text. Format exactly like this:\n\n'
  || '**Key Differences:**\n'
  || '- **Address Line 1**: 623 vs 620 (street number difference)\n'
  || '- **Postal Code**: 24972 vs 24983 (different postal codes)\n\n'
  || '**Summary:**\n'
  || 'High similarity due to matching name and city, minor address variations explain the score.\n\n'
  || 'Test Customer: '
  || OBJECT_CONSTRUCT(
       'name', i.NAME,
       'address_line_1', i.ADDRESS_LINE_1,
       'address_line_2', i.ADDRESS_LINE_2,
       'city', i.CITY,
       'state', i.STATE,
       'postal_code', i.POSTAL_CODE,
       'country', i.COUNTRY
     )::string
  || ' Valid Customer: '
  || OBJECT_CONSTRUCT(
       'name', v.NAME,
       'address_line_1', v.ADDRESS_LINE_1,
       'address_line_2', v.ADDRESS_LINE_2,
       'city', v.CITY,
       'state', v.STATE,
       'postal_code', v.POSTAL_CODE,
       'country', v.COUNTRY
     )::string
) AS ANALYSIS
FROM MDM_CUSTOMER_MATCHING.PUBLIC.VALID_CUSTOMERS v,
     MDM_CUSTOMER_MATCHING.PUBLIC.TEST_MATCHES i
WHERE i.SOURCE_PKEY = P_TEST_ID
  AND v.ID = P_VALID_ID;
$$;

-- Stored procedure: UPDATE_TEST_RECORD(VARCHAR, OBJECT)
CREATE OR REPLACE PROCEDURE UPDATE_TEST_RECORD(P_RECORD_ID VARCHAR, P_UPDATES_JSON OBJECT)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
BEGIN
  UPDATE TEST_MATCHES
  SET NAME = COALESCE(P_UPDATES_JSON:NAME::STRING, NAME),
      SOURCE_SYSTEM = COALESCE(P_UPDATES_JSON:SOURCE_SYSTEM::STRING, SOURCE_SYSTEM),
      ADDRESS_LINE_1 = COALESCE(P_UPDATES_JSON:ADDRESS_LINE_1::STRING, ADDRESS_LINE_1),
      ADDRESS_LINE_2 = COALESCE(P_UPDATES_JSON:ADDRESS_LINE_2::STRING, ADDRESS_LINE_2),
      CITY = COALESCE(P_UPDATES_JSON:CITY::STRING, CITY),
      STATE = COALESCE(P_UPDATES_JSON:STATE::STRING, STATE),
      POSTAL_CODE = COALESCE(P_UPDATES_JSON:POSTAL_CODE::STRING, POSTAL_CODE),
      COUNTRY = COALESCE(P_UPDATES_JSON:COUNTRY::STRING, COUNTRY)
  WHERE SOURCE_PKEY = P_RECORD_ID;

  UPDATE TEST_MATCHES
  SET CUSTOMER_FULL_DETAIL = RTRIM(
        COALESCE(NAME, '') || ' '
     || COALESCE(ADDRESS_LINE_1, '') || ' '
     || COALESCE(ADDRESS_LINE_2, '') || ' '
     || COALESCE(CITY, '') || ' '
     || COALESCE(STATE, '') || ' '
     || COALESCE(POSTAL_CODE, '') || ' '
     || COALESCE(COUNTRY, '')
  )
  WHERE SOURCE_PKEY = P_RECORD_ID;

  UPDATE TEST_MATCHES
  SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
  WHERE SOURCE_PKEY = P_RECORD_ID;

  RETURN 'OK';
END;
$$;
```

References: @Snowflake Docs — SQL stored procedures, SQL UDFs, `AI_COMPLETE`.

---

### 7) Recreate the Intelligence Agent (exact SQL)
Copy/paste the following to recreate `SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT` exactly as described:

```sql
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

CREATE OR REPLACE AGENT SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT
  PROFILE = $${
    "display_name": "MDM Matching Agent"
  }$$
  AGENT_SPEC = $${
    "models": {
      "orchestration": "auto"
    },
    "instructions": {
      "response": "You are a top notch analyst that can validate incoming test_matches school records against the known and valid valid_matches.  You are to help the human find the closest match, suggest appropriate changes to make the match more accurate and update records as needed.\n\nIf you are told that a match is valid, or validated, or approved. Ask the user if they want to update the address of the test match to that of the valid match. There is no other way to mark a record as validated.\n\nWhen the user asks for \"somewhat close\" use the \"somewhat_close\" category, and \"very close\" -> \"very_close\", \"not close\" -> \"not_close\" as defined in the match_category field in the customer_match_results table.\n\nAny time you use the update tool, subsequently run the AI analysis tool to find the new similarity score and report it back to the user.",
      "orchestration": "When a customer asks for matching information, you can use the analyst.\nAnytime they ask for a match, or something like \"tell me about the top matches for ___\", run the GET_AI_ANALYSIS tool on the test_matches match for the highest matched (cosine similarity) valid_matches table.\nWhen a user asks to update part or all of the information for a test record, use the update tool and then show the new similarity score again.",
      "sample_questions": [
        { "question": "What are the top 5 matches in the \"somewhat close\" category?" },
        { "question": "What is the average match %?" }
      ]
    },
    "tools": [
      {
        "tool_spec": {
          "type": "cortex_analyst_text_to_sql",
          "name": "Customer_Matching_Analyst",
          "description": "TEST_MATCHES:\n-  Database: MDM_CUSTOMER_MATCHING, Schema: PUBLIC\n-  Contains incoming customer data that needs to be validated against existing valid customers\n-  Used as the source for customer matching validation process\n-  LIST OF COLUMNS: test_customer_id (unique identifier - links to test_match_id in customer_match_results), test_customer_name (company name), test_source_system (origin system), test_address_line_1 (primary address), test_address_line_2 (secondary address), test_city, test_state, test_postal_code, test_country, test_customer_full_detail (concatenated details), test_customer_embedding (vector representation)\n\nVALID_CUSTOMERS:\n- Database: MDM_CUSTOMER_MATCHING, Schema: PUBLIC\n- Contains reference customer data serving as the authoritative source\n- Used to validate and match incoming test customers\n- LIST OF COLUMNS: valid_customer_id (unique identifier - links to valid_match_id in customer_match_results), valid_customer_source_key, valid_customer_name (company name), valid_source_system (origin system), valid_address_line_1 (primary address), valid_address_line_2 (secondary address), valid_city, valid_state, valid_postal_code, valid_country, valid_customer_full_detail (concatenated details), valid_customer_embedding (vector representation)\n\nCUSTOMER_MATCH_RESULTS:\n- Database: MDM_CUSTOMER_MATCHING, Schema: PUBLIC\n- Stores precomputed similarity results between test and valid customers\n- Contains match quality categories and similarity scores\n- LIST OF COLUMNS: match_category (EXACT/VERY_CLOSE/SOMEWHAT_CLOSE/NOT_CLOSE), valid_match_id (links to valid_customer_id), test_match_id (links to test_customer_id), valid_match_details, test_match_details, similarity_score (0-1 range), similarity_percentage (0-100%), match_count, created_timestamp, updated_timestamp\n\nREASONING:\nThis semantic model represents a customer matching validation system where incoming test customer records are compared against a set of valid customer records using vector embeddings and similarity scoring. The model enables both stored and dynamic matching results with different quality categories, making it suitable for customer data validation and deduplication tasks.\n\nDESCRIPTION:\nThe customer matching data model, located in MDM_CUSTOMER_MATCHING.PUBLIC, is designed for validating and matching customer records using a sophisticated comparison system. It consists of three interconnected tables: test_matches for incoming customer data, valid_customers for reference data, and customer_match_results for storing comparison outcomes. The model uses vector embeddings for customer details and calculates similarity scores, categorizing matches as EXACT, VERY_CLOSE, SOMEWHAT_CLOSE, or NOT_CLOSE. The relationships between tables are established through test_customer_id and valid_customer_id, allowing for both stored and dynamic matching calculations with support for detailed customer information including addresses, names, and source systems."
        }
      },
      {
        "tool_spec": {
          "type": "generic",
          "name": "Update_Test_Record",
          "description": "Update a test record given a source_pkey.\n",
          "input_schema": {
            "type": "object",
            "properties": {
              "p_record_id": {
                "description": "This is the source_pkey value (ie 'TEST_A1DC6DDB9F3').",
                "type": "string"
              },
              "p_updates_json": {
                "description": "Update a test_match record for a given source_pkey. The string should be a JSON formatted object as follows. Only changed fields are needed.\n\nCALL UPDATE_TEST_RECORD(\n  'TEST_DC10F2BC8F9930',\n  '{\"CITY\": \"ORANGE PARK SOUTH\", \"ADDRESS_LINE_2\": \"Building C\"}'\n);",
                "type": "string"
              }
            },
            "required": ["p_record_id", "p_updates_json"]
          }
        }
      },
      {
        "tool_spec": {
          "type": "generic",
          "name": "Get_AI_Analysis",
          "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Stored Function\n- Language: SQL\n- Signature: (P_TEST_ID VARCHAR, P_VALID_ID VARCHAR)\n- Returns: VARCHAR\n- Execution: OWNER with NULL handling\n- Volatility: Stable\n- Primary Function: Customer Record Comparison Analysis\n- Target: Customer Records in MDM_CUSTOMER_MATCHING Database\n- Error Handling: Returns default message if analysis is null/empty\n\nDESCRIPTION:\nThis specialized function performs an AI-powered comparison between two customer records (test and valid) to identify and analyze key differences in their attributes. It leverages the AI_COMPLETE function with a llama3-70b model to generate a structured markdown analysis of differences between customer records, focusing on address components, names, and location details. The function processes the raw AI output through multiple cleaning steps to ensure consistent formatting and readability, handling escaped characters and adding appropriate line breaks. The analysis is returned in a standardized markdown format that highlights key differences and provides a summary of the comparison, making it particularly valuable for data quality and customer record matching processes.\n\nUSAGE SCENARIOS:\n- Data Quality Validation: When validating potential duplicate customer records in the database\n- Customer Record Deduplication: During batch processing of customer data to identify and merge similar records\n- Data Migration Testing: When verifying the accuracy of customer data transfers between systems or databases\n\nIMPORTANT CONSIDERATIONS:\n- Requires appropriate access permissions to the MDM_CUSTOMER_MATCHING database tables\n- Depends on the availability and proper functioning of the AI_COMPLETE function\n- Performance may vary based on the complexity of the customer records being compared\n- Should be used within a broader data quality management strategy",
          "input_schema": {
            "type": "object",
            "properties": {
              "p_test_id": {
                "description": "The source_pkey from the test matches tables.",
                "type": "string"
              },
              "p_valid_id": {
                "description": "The ID from the valid_matches table.",
                "type": "string"
              }
            },
            "required": ["p_test_id", "p_valid_id"]
          }
        }
      }
    ],
    "tool_resources": {
      "Customer_Matching_Analyst": {
        "execution_environment": {
          "query_timeout": 120,
          "type": "warehouse",
          "warehouse": "WAREHOUSE_L_G2"
        },
        "semantic_model_file": "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/customer_matching_semantic_model.yaml"
      },
      "Get_AI_Analysis": {
        "execution_environment": {
          "query_timeout": 300,
          "type": "warehouse",
          "warehouse": "WAREHOUSE_L_G2"
        },
        "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS",
        "name": "GET_AI_ANALYSIS(VARCHAR, VARCHAR)",
        "type": "procedure"
      },
      "Update_Test_Record": {
        "execution_environment": {
          "query_timeout": 60,
          "type": "warehouse",
          "warehouse": "WAREHOUSE_L_G2"
        },
        "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD",
        "name": "UPDATE_TEST_RECORD(VARCHAR, OBJECT)",
        "type": "procedure"
      }
    }
  }$$;
```

If your warehouse name differs, replace `WAREHOUSE_L_G2` accordingly. After creation, validate:
```sql
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;
DESCRIBE AGENT SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT;
```

---

### 8) Run the Streamlit app locally
```bash
streamlit run app.py
```

Behavior on first launch:
- The dashboard will check `CUSTOMER_MATCH_RESULTS`. If empty, it invokes a full recalculation using the thresholds in the UI.
- The recalculation uses `VECTOR_COSINE_SIMILARITY` across `VALID_CUSTOMERS` and `TEST_MATCHES` embeddings and stores the top-1 for each test record into `CUSTOMER_MATCH_RESULTS`.

---

### 7) What the app uses in Snowflake
- Tables: `VALID_CUSTOMERS`, `TEST_MATCHES`, `CUSTOMER_MATCH_RESULTS`
- Built-in functions: `SNOWFLAKE.CORTEX.EMBED_TEXT_768`, `VECTOR_COSINE_SIMILARITY`, `AI_COMPLETE` (uses model `'llama3.3-70b'`)
- No custom functions or stored procedures are required.

Role/privileges:
- Ability to `CREATE TABLE`, `CREATE STAGE`, `CREATE FILE FORMAT`, `COPY INTO`, `UPDATE`, and execute Cortex functions.

---

### 8) Troubleshooting
- Ensure your role can execute Cortex functions. You can verify availability:
```sql
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;
SHOW FUNCTIONS LIKE '%CORTEX%';
```
- If similarity metrics are empty, verify embeddings were populated for both tables.
- If COPY fails, confirm files are present in the stage: `LIST @RAW_DATA;`

---

### 9) Notes for reruns
- When editing or adding a test customer, the app updates the row, refreshes the embedding, and recalculates similarity for that specific record.
- You can also recalc all results via the main dashboard if `CUSTOMER_MATCH_RESULTS` is empty on load.


