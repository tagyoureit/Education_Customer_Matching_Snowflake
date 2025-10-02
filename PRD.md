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

## Interaction summary
- Clicking a row loads it into the workbench and refreshes matches
- Submitting edits updates the row, recomputes embeddings/similarity, and refreshes the candidate list
- Threshold changes recompute categories and dashboard

## Snowflake objects (UPPERCASE)
USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;

- CUSTOMER (golden): CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, PHONE
- CUSTOMER_IDENTIFIER: CUSTOMER_BUSINESS_ID, IDENTIFIER_TYPE, IDENTIFIER_VALUE, SOURCE_SYSTEM
- CUSTOMER_ADDRESS: CUSTOMER_BUSINESS_ID, ADDRESS_ROLE (OFFICE|WAREHOUSE|SCHOOL), ADDRESS_LINE_1,
  ADDRESS_LINE_2, CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, LATITUDE,
  LONGITUDE, VERIFICATION_STATUS_CODE, VERIFICATION_MESSAGE, ENRICHED_INDICATOR
- INCOMING_CUSTOMER (new arrivals): SOURCE_PKEY, SOURCE_SYSTEM, CUSTOMER_NAME, ADDRESS_LINE_1,
  ADDRESS_LINE_2, CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, LATITUDE,
  LONGITUDE, INGESTED_AT, UPDATED_AT, CUSTOMER_FULL_DETAIL,
  CUSTOMER_FULL_DETAIL_EMBEDDING VECTOR(FLOAT, 768)
- CUSTOMER_MATCH_RESULTS: CUSTOMER_BUSINESS_ID, SOURCE_PKEY, CUSTOMER_FULL_DETAIL,
  INCOMING_FULL_DETAIL, MATCH_CONFIDENCE FLOAT, MATCH_CATEGORY, CREATED_TIMESTAMP, UPDATED_TIMESTAMP

Notes:
- Columns align with provided screenshots where derivable (COUNTY, VERIFICATION_* fields, etc.)
- No PK/FK constraints (not hybrid tables)

## Matching logic
- Embeddings: SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m')
- Similarity: VECTOR_COSINE_SIMILARITY (CUSTOMER vs INCOMING_CUSTOMER)
- Threshold routing:
  - Auto-match: MATCH_CONFIDENCE ≥ 0.980 → insert into CUSTOMER_IDENTIFIER
  - Needs review: 0.920 ≤ MATCH_CONFIDENCE < 0.980
  - Not close: < 0.920

## Batch pipeline (Streams/Tasks)
- Stream on INCOMING_CUSTOMER for new/updated rows
- Task A: compute embeddings if null → similarity search → upsert CUSTOMER_MATCH_RESULTS
- Task B: auto-associate high-confidence → insert CUSTOMER_IDENTIFIER rows
- Task C: send summary email via SYSTEM$SEND_EMAIL (last)

## Agent (Cortex Agents)
- Template: https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents
- Tools:
  - cortex_analyst_text_to_sql over semantic model for CUSTOMER/INCOMING_CUSTOMER/CUSTOMER_MATCH_RESULTS
  - Update_Test_Record: `MDM_CUSTOMER_MATCHING.PUBLIC.UPDATE_TEST_RECORD`
  - Get_AI_Analysis: `MDM_CUSTOMER_MATCHING.PUBLIC.GET_AI_ANALYSIS`
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

## Non-goals
- No complex geospatial/business-rule scoring beyond similarity
- No writes back to source systems (demo only)
