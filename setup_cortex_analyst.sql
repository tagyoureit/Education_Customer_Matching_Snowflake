-- Setup script for Cortex Analyst infrastructure
-- Run these commands in your Snowflake worksheet

USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- Create stage for storing semantic models
CREATE STAGE IF NOT EXISTS SEMANTIC_MODELS 
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Stage for storing Cortex Analyst semantic model YAML files';

-- Grant necessary privileges (if needed)
-- GRANT READ ON STAGE SEMANTIC_MODELS TO ROLE PUBLIC;

-- Check that the stage was created successfully
LIST @SEMANTIC_MODELS;

-- After running this SQL, you need to upload the customer_matching_semantic_model.yaml file
-- to this stage. You can do this through Snowsight UI:
-- 1. Go to Data > Databases > MDM_CUSTOMER_MATCHING > PUBLIC > Stages > SEMANTIC_MODELS
-- 2. Click "Upload Files" 
-- 3. Select the customer_matching_semantic_model.yaml file

-- OR use the Snowflake CLI:
-- snow stage copy file://./customer_matching_semantic_model.yaml @MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS

-- Verify the file was uploaded:
-- LIST @SEMANTIC_MODELS;

-- Test that you can read the semantic model file:
-- SELECT $1 FROM @SEMANTIC_MODELS/customer_matching_semantic_model.yaml;