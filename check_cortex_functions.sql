-- Check Cortex Functions Available in Your Snowflake Environment
-- Run this first to see what's available

USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- 1. Check all Cortex-related functions
SHOW FUNCTIONS LIKE '%CORTEX%';

-- 2. Check if Cortex Agent functions exist
SHOW FUNCTIONS LIKE '%AGENT%';

-- 3. Check available Cortex features
SELECT 'Checking Cortex Features' AS step;

-- 4. Try to see if Cortex Agents are supported
SHOW CORTEX AGENTS;

-- 5. Check current account region and edition
SELECT 
    CURRENT_ACCOUNT() AS account,
    CURRENT_REGION() AS region,
    SYSTEM$GET_SNOWFLAKE_PLATFORM_INFO() AS platform_info;

-- 6. Check if semantic model file exists
LIST @SEMANTIC_MODELS;

-- Instructions:
-- Run each section and check the results
-- If SHOW CORTEX AGENTS works, agents are supported
-- If you see agent-related functions, note the exact names
-- Use this info to update the creation script