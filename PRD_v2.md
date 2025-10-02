# Customer Matching Demo — PRD v2

Goal:
Create a streamlined demo that processes new incoming customers in Snowflake, auto-matches high-confidence cases, queues medium-confidence cases for side-by-side review in Streamlit, and exposes a Cortex Agent interface for querying and simple updates. This PRD supersedes all V1 docs.

## Scope
- Batch-first flow: detect new records, compute similarities, auto-associate above threshold, summarize results.
- Reviewer UX: side-by-side A/B compare (left=incoming, right=golden) with differences highlighted and AI explanation; Save and Save & Next.
- Agent: current Snowflake Cortex Agent APIs for text-to-SQL and tools to update a test record and run AI analysis.
- Notifications: email summary using SYSTEM$SEND_EMAIL (implemented last). Reference: @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures

## Snowflake objects (UPPERCASE)
USE DATABASE MDM_CUSTOMER_MATCHING;  USE SCHEMA PUBLIC;

- CUSTOMER: authoritative customer ("golden")
  - CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, PHONE
- CUSTOMER_IDENTIFIER: cross-system IDs
  - CUSTOMER_BUSINESS_ID, IDENTIFIER_TYPE, IDENTIFIER_VALUE, SOURCE_SYSTEM
- CUSTOMER_ADDRESS: multiple addresses per customer
  - CUSTOMER_BUSINESS_ID, ADDRESS_ROLE (OFFICE|WAREHOUSE|SCHOOL), ADDRESS_LINE_1, ADDRESS_LINE_2,
    CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, LATITUDE, LONGITUDE,
    VERIFICATION_STATUS_CODE, VERIFICATION_MESSAGE, ENRICHED_INDICATOR
- INCOMING_CUSTOMER: newly arrived records to evaluate
  - SOURCE_PKEY, SOURCE_SYSTEM, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
    POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, LATITUDE, LONGITUDE, INGESTED_AT, UPDATED_AT,
    CUSTOMER_FULL_DETAIL, CUSTOMER_FULL_DETAIL_EMBEDDING VECTOR(FLOAT, 768)
- CUSTOMER_MATCH_RESULTS: precomputed similarity outcomes (one top candidate per incoming)
  - CUSTOMER_BUSINESS_ID, SOURCE_PKEY, CUSTOMER_FULL_DETAIL, INCOMING_FULL_DETAIL,
    MATCH_CONFIDENCE FLOAT, MATCH_CATEGORY, CREATED_TIMESTAMP, UPDATED_TIMESTAMP

Notes:
- Columns align with provided screenshots where derivable (COUNTY, VERIFICATION_* fields, etc.).
- No PK/FK constraints (not hybrid tables).

## Matching logic
- Embeddings: SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m').
- Similarity: VECTOR_COSINE_SIMILARITY over CUSTOMER vs INCOMING_CUSTOMER.
- Confidence thresholds (configurable in UI):
  - Auto-match: MATCH_CONFIDENCE ≥ 0.980
  - Needs review: 0.920 ≤ MATCH_CONFIDENCE < 0.980
  - Not close: < 0.920
- Auto-match action: insert mapping into CUSTOMER_IDENTIFIER with SOURCE_SYSTEM/SOURCE_PKEY; record decision in CUSTOMER_MATCH_RESULTS.

## Batch pipeline (Streams/Tasks)
- Stream on INCOMING_CUSTOMER detects new/updated rows.
- Task computes embeddings if null → similarity search → upsert CUSTOMER_MATCH_RESULTS.
- Task 2 performs auto-association for high-confidence cases (insert CUSTOMER_IDENTIFIER rows).
- Task 3 sends summary email via SYSTEM$SEND_EMAIL (last step to implement).

## Streamlit UI (SiS-compatible)
- Dashboard: counts by bucket, filters (New Only, bucket, ADDRESS_ROLE).
- Record workbench: left INCOMING_CUSTOMER, right best CUSTOMER; highlight only fields that differ. Use AI analysis to explain differences field-by-field.
- Top candidates list under workbench with confidence and quick switch.
- Actions: Save changes to INCOMING_CUSTOMER; Save & Next to advance queue.

## Agent (Cortex Agents) — template reference
- Use the Snowflake-Labs quickstart as the API template: @https://github.com/Snowflake-Labs/sfguide-getting-started-with-cortex-agents
- Tools:
  - cortex_analyst_text_to_sql over semantic model for the three tables above
  - generic tool: UPDATE_TEST_RECORD (update INCOMING_CUSTOMER by SOURCE_PKEY)
  - generic tool: GET_AI_ANALYSIS(P_TEST_ID, P_VALID_ID) to produce field-by-field explanation
- Resource wiring: warehouse execution, semantic model file path, stored program identifiers.

## Semantic model
- Provide `customer_matching_semantic_model.yaml` with CUSTOMER, INCOMING_CUSTOMER, CUSTOMER_MATCH_RESULTS and business descriptions matching UI semantics.

## Email notifications (last)
- Create NOTIFICATION INTEGRATION, validate recipients, send summary via SYSTEM$SEND_EMAIL. Reference: @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures

## Deliverables
- PRD_v2.md (this file)
- SQL: DDL + Streams/Tasks + stored function/procedure skeletons
- Streamlit updates (side-by-side, diffs highlighting, Save & Next, filters)
- Agent setup SQL JSON/spec aligning with the template repo above
- README updates and runbook

## Non-goals (v2)
- No complex geospatial or business-rule scoring beyond similarity
- No bi-directional updates to source systems (demo only)
