# Customer Matching Demo — PRD (v2 consolidated)

Goal:
Create a streamlined demo that processes new incoming customers in Snowflake, auto-matches high-confidence cases, queues medium-confidence cases for side-by-side review in Streamlit, and exposes a Cortex Agent interface for querying and simple updates. This PRD supersedes prior V1/V2 markdowns.

## Scope
- Batch-first flow: detect new records, compute similarities, auto-associate above threshold, summarize results.
- Reviewer UX: side-by-side A/B compare (left=incoming, right=golden) with differences highlighted and AI explanation; Save and Save & Next.
- Agent: Snowflake Cortex Agent APIs for text-to-SQL and tools to update a test record and run AI analysis.
- Notifications: email summary using SYSTEM$SEND_EMAIL (implement last). Reference: @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures

## UI
### Threshold configuration
- Exact ≥ 0.995
- Very Close ≥ 0.980
- Somewhat Close ≥ 0.920
- Recompute button updates match buckets and results

### Dashboard overview
- Counts and percentages by bucket (Exact/Very Close/Somewhat/Not Close)
- Totals for golden and incoming records

### Tables
- Golden customers (scrollable)
- Incoming customers (scrollable)

### Workbench
- Left: INCOMING_CUSTOMER; Right: best CUSTOMER
- Highlight only fields that differ; show AI explanation per field
- Show Top-N candidates with confidence; quick switch
- Actions: Save, Save & Next

### Review New Records
- Purpose: Review unassigned identifier records and link them to existing customer addresses or create new customer IDs.

- Layout (two columns):
  - Left: Customer Address Form (read-only), populated from `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS`.
  - Right: Customer Identifier Form (read-only), populated from `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER`.

- Initial Load (Right column):
  - Load the first record where `CUSTOMER_BUSINESS_ID IS NULL`, ordered by `CREATED_TIMESTAMP DESC` (newest first).
  - Always run CLI examples with:
    ```sql
    USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs
    ```

- Cortex Search and Candidates:
  - Build the search query using the CI record's `CUSTOMER_FULL_DETAIL`.
  - Retrieve the top 3 candidates with Cortex Search; store results in UI state. Reference: @Snowflake Docs.
    ```sql
    USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs

    SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
      'MDM_CUSTOMER_ADDRESS_SEARCH',
      '{
        "query": "<CI.CUSTOMER_FULL_DETAIL>",
        "columns": ["customer_full_detail", "customer_business_id", "customer_name", "address_line_1", "address_line_2", "city", "county", "state", "postal_code", "postalcode_extension", "country"],
        "limit": 3
      }'
    ));
    ```
  - Populate the Left form from the candidate with the highest Cortex similarity score (as returned by `SEARCH_PREVIEW`). Provide a small selector to switch among the top 3 candidates.

- Navigation:
  - Previous: go to the previous unassigned CI record (`CUSTOMER_BUSINESS_ID IS NULL`) in reverse `CREATED_TIMESTAMP` order; disabled on first.
  - Next: go to the next unassigned CI record; disabled on last.

- Actions:
  - Assign
    - Set the current CI's `CUSTOMER_BUSINESS_ID` to the selected Left candidate's `CUSTOMER_BUSINESS_ID`.
    - Recompute fields for only the current CI row. Reference: @Snowflake Docs.
      ```sql
      USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs

      -- Recompute confidence_score for current CI
      UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
      SET confidence_score = VECTOR_COSINE_SIMILARITY(ca.customer_full_detail_embedding, ci.customer_full_detail_embedding)
      FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
      WHERE ci.customer_business_id = ca.customer_business_id
        AND /* filter to current CI row */ ci.identifier_type = :IDENTIFIER_TYPE AND ci.identifier_value = :IDENTIFIER_VALUE;

      -- Set enriched_indicator for current CI
      UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
      SET enriched_indicator = (CASE WHEN confidence_score > 0.90 THEN 'VALID' ELSE 'ERROR' END)
      WHERE confidence_score IS NOT NULL
        AND /* filter to current CI row */ identifier_type = :IDENTIFIER_TYPE AND identifier_value = :IDENTIFIER_VALUE;
      ```
    - Run verification message update for just this `CUSTOMER_BUSINESS_ID` using the logic from `SQL/POPULATE_VERIFICATION_MESSAGE.sql` (constrain execution to the current row). References: @Snowflake Docs for `AI_COMPLETE`, `OBJECT_CONSTRUCT`.

  - Create New ID
    - Insert a new row into `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS`, copying fields from the current CI (Right form). Generate a new id using `GENERATE_CUSTOMER_BUSINESS_ID()` (available per `CREATE_GENERATE_CUSTOMER_SAMPLES_SP.sql`).
    - Assign the new ID to the current CI, then run the same recompute and verification steps as Assign.
    - Example outline:
      ```sql
      USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs

      -- Create new address from CI fields (read-only in UI; copy values)
      INSERT INTO MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS (
        CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
        POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE
      )
      SELECT
        GENERATE_CUSTOMER_BUSINESS_ID(), CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
        POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE
      FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
      WHERE /* filter to current CI row */ identifier_type = :IDENTIFIER_TYPE AND identifier_value = :IDENTIFIER_VALUE;

      -- Assign the newly created ID to the CI row (lookup by latest insert or deterministic match)
      UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
      SET customer_business_id = ca.customer_business_id
      FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
      WHERE /* deterministic join to the new address */ ca.customer_name = ci.customer_name
        AND ca.address_line_1 = ci.address_line_1
        AND ca.city = ci.city
        AND ca.state = ci.state
        AND ca.postal_code = ci.postal_code
        AND /* filter to current CI row */ ci.identifier_type = :IDENTIFIER_TYPE AND ci.identifier_value = :IDENTIFIER_VALUE;
      ```

- Data and Fields
  - Forms show: `CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE, CUSTOMER_FULL_DETAIL`.
  - All object and column names are UPPERCASE in SQL.

- Non-Functional
  - Clear disabled states and status messages (success/error) in UI.
  - Operations performed via Snowflake; CLI examples always include `USE DATABASE` and `USE SCHEMA`.
  - References: @Snowflake Docs for `SEARCH_PREVIEW`, `VECTOR_COSINE_SIMILARITY`, `AI_COMPLETE`, `OBJECT_CONSTRUCT`.

## Interaction summary
- Clicking a row loads it into the workbench and refreshes matches
- Submitting edits updates the row, recomputes embeddings/similarity, and refreshes the candidate list
- Threshold changes recompute categories and dashboard

## Snowflake objects (UPPERCASE)
USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;

Table - "CUSTOMER_ADDRESS" - These are the "golden" records.  
Fields - 
CUSTOMER_BUSINESS_ID, 
CUSTOMER_NAME, 
ADDRESS_LINE_1, 
ADDRESS_LINE_2, 
CITY, 
COUNTY, 
STATE, 
POSTAL_CODE - compatible with US and international formats
POSTALCODE_EXTENSION, 
COUNTRY,
PHONE

Table - "CUSTOMER_IDENTIFIER" table.  This will have the records that come in from different systems.
Fields - 
IDENTIFIER_TYPE - One of ("NWEA SFDC ID", "NCES ID", "SAP Customer Number", "HMH ID", "HMH Ref ID", "HMH SFDC ID", "AgileEd ID")
IDENTIFIER_VALUE - internal ID for each different IDENTIFIER_TYPE
CUSTOMER_BUSINESS_ID (will be blank until a match is made)
CUSTOMER_NAME,
ADDRESS_ROLE (OFFICE|WAREHOUSE|SCHOOL)
ADDRESS_LINE_1, 
ADDRESS_LINE_2, 
CITY, 
COUNTY, 
STATE, 
POSTAL_CODE - compatible with US and international formats
POSTALCODE_EXTENSION, 
COUNTRY,
PHONE
VERIFICATION_STATUS_CODE, 
VERIFICATION_MESSAGE, 
ENRICHED_INDICATOR,
CONFIDENCE_SCORE,
CUSTOMER_FULL_DETAIL,
CUSTOMER_FULL_DETAIL_EMBEDDING VECTOR(FLOAT, 768) - 
CREATED_TIMESTAMP, 
UPDATED_TIMESTAMP


Notes:
- Columns align with provided screenshots where derivable (COUNTY, VERIFICATION_* fields, etc.)
- No PK/FK constraints (not hybrid tables)

## Matching logic
- Embeddings: AI_EMBED('snowflake-arctic-embed-m-v1.5')
- Similarity: VECTOR_COSINE_SIMILARITY (CUSTOMER vs INCOMING_CUSTOMER)
- Threshold routing:
  - Auto-match: MATCH_CONFIDENCE ≥ 0.980 → insert into CUSTOMER_IDENTIFIER
  - Needs review: 0.920 ≤ MATCH_CONFIDENCE < 0.980
  - Not close: < 0.920

## Batch pipeline (Streams/Tasks)
- Stream on incoming identifiers or staged loads for new/updated rows
- Task A: compute embeddings if null → perform similarity (Cortex Search) for assignments
- Task B: auto-associate high-confidence → update CUSTOMER_IDENTIFIER rows
- Task C: send summary email via SYSTEM$SEND_EMAIL (last)

## Agent (Cortex Agents)
- Template: https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents
- Tools:
  - cortex_analyst_text_to_sql over semantic model `@customer_matching_semantic_model.yaml`
  - Assign_Identifier_To_Business_Id, CREATE_AND_ASSIGN_NEW_CUSTOMER_ADDRESS_FROM_CI,
    GENERATE_CUSTOMER_SAMPLES, POPULATE_VERIFICATION_MESSAGE_SQL,
    PROCESS_IDENTIFIER_ASSIGN_OR_ERROR, SEARCH_ADDRESS_CANDIDATES_SP
- Resources: warehouse execution, semantic model stage path, stored program identifiers

## Semantic model
- `customer_matching_semantic_model.yaml` describing tables and relationships for Analyst

## Technical requirements
- Connection via Snow CLI/env vars
- SiS-compatible Streamlit app
- Toast notifications for DB operations

## Deliverables
- PRD.md (this file)
- SQL (DDL, Streams/Tasks, stored function/procedure skeletons)
- Streamlit updates (side-by-side, diff highlighting, Save & Next, filters)
- Agent setup/spec aligned with template repo
- README and runbook updates

## Tools
### `TOOLS/generate_customer_identifiers.py`
Generates 3–7 identifier/address rows in `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER` for each customer in `MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS` with approximately 60% exact copies, 30% slight variations, and 10% spelling errors per customer. All overlapping columns are copied by name; additional fields are set as follows:
- `IDENTIFIER_TYPE`: random choice of {"NWEA SFDC ID", "NCES ID", "SAP Customer Number", "HMH ID", "HMH Ref ID", "HMH SFDC ID", "AgileEd ID"}
- `IDENTIFIER_VALUE`: random opaque value (no prefixes)
- `ADDRESS_ROLE`: random {OFFICE|WAREHOUSE|SCHOOL}
- `CREATED_TIMESTAMP`, `UPDATED_TIMESTAMP`: `CURRENT_TIMESTAMP()`

Usage:

```bash
python TOOLS/generate_customer_identifiers.py \
  --seed 42 \
  --min-per-customer 3 \
  --max-per-customer 7 \
  --batch-size 5000
```

Options:
- `--seed`: reproducible randomness
- `--dry-run`: preview first few rows without inserting
- `--limit`: process only the first N customers (for testing)
- `--exact-ratio`, `--slight-ratio`, `--typo-ratio`: override 0.6/0.3/0.1 if needed

Validation (Snow SQL CLI):

```sql
USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;  -- Reference: @Snowflake Docs

-- Count generated rows
SELECT COUNT(*) FROM CUSTOMER_IDENTIFIER;

-- Expect roughly 3–7x CUSTOMER_ADDRESS rows
SELECT COUNT(*) AS addr_cnt FROM CUSTOMER_ADDRESS;

-- Spot-check a few customers
SELECT * FROM CUSTOMER_IDENTIFIER WHERE CUSTOMER_BUSINESS_ID IN (
  SELECT CUSTOMER_BUSINESS_ID FROM CUSTOMER_ADDRESS LIMIT 3
) ORDER BY CUSTOMER_BUSINESS_ID, CREATED_TIMESTAMP DESC;
```

Reference inspiration for approach: [generate_test_matches.py](https://github.com/tagyoureit/Education_Customer_Matching_Snowflake/blob/main/generate_test_matches.py)

## Non-goals
- No complex geospatial/business-rule scoring beyond similarity
- No writes back to source systems (demo only)

# Agent API Integration (v2)

Use the Cortex Agents quickstart as a template: https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents

## Steps
1. Upload semantic model `customer_matching_semantic_model.yaml` to a stage; grant usage to the agent role.
2. Create or update `SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT` with tools:
   - `cortex_analyst_text_to_sql` (semantic model path on stage)
   - `Update_Test_Record` (procedure: `MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD`)
   - `Get_AI_Analysis` (function/procedure: `MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS`)
3. Configure host and PAT in `pages/3_🧪_Agent_Test.py` and call the REST API as per the template models.
4. Validate: ask for matches between 80–85%, then run update and re-run analysis.

### Streamlit Page: MDM Matching Agent
- A dedicated Streamlit page is available at `pages/6_MDM_Matching_Agent.py`.
- It targets the agent `SNOWFLAKE_INTELLIGENCE.AGENTS.MDM_MATCHING_AGENT` and streams results using the `models/` classes.
- Auth: reuses the existing Snowflake connector session (no separate PAT required). The page resolves the host and sends the session token in the `Authorization: Snowflake Token="..."` header.
- Usage:
  - Launch the app as usual; open the sidebar page "MDM Matching Agent".
  - Type a question (e.g., "Show me customers with very close similarity scores").
  - The UI will stream text, thinking, tool use, tool results, tables, and charts.
  - Agent scope: `DATABASE=SNOWFLAKE_INTELLIGENCE`, `SCHEMA=AGENTS`, `AGENT=MDM_MATCHING_AGENT`.

## Email (later)
Send batch summaries via `SYSTEM$SEND_EMAIL`. See @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures
