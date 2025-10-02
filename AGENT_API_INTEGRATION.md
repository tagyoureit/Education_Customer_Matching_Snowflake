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

## Email (later)
Send batch summaries via `SYSTEM$SEND_EMAIL`. See @https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures
