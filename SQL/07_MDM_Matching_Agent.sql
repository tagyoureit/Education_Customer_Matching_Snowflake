-- Create the master FinOps agent with only the 5 working tools
USE ROLE MDM_CUSTOMER_MATCHING_ROLE;

CREATE STAGE IF NOT EXISTS SEMANTIC_MODELS
    DIRECTORY = (ENABLE = TRUE);
PUT file://cortex_analyst/MDM_CUSTOMER_MATCHING_V2.yaml @SEMANTIC_MODELS AUTO_COMPRESS=FALSE OVERWRITE=TRUE;

CREATE OR REPLACE CORTEX SEARCH SERVICE MDM_CUSTOMER_ADDRESS_SEARCH
  ON CUSTOMER_FULL_DETAIL
  WAREHOUSE = compute_wh
  TARGET_LAG = '1 hour'
AS (
    SELECT
        CUSTOMER_FULL_DETAIL,
        CUSTOMER_BUSINESS_ID,
        CUSTOMER_NAME,
        ADDRESS_LINE_1,
        ADDRESS_LINE_2,
        CITY,
        COUNTY,
        STATE,
        POSTAL_CODE,
        POSTALCODE_EXTENSION,
        COUNTRY
    FROM "MDM_CUSTOMER_MATCHING"."PUBLIC"."CUSTOMER_ADDRESS"
);

CREATE OR REPLACE CORTEX SEARCH SERVICE MDM_CUSTOMER_NAME_LOOKUP
  ON CUSTOMER_NAME
  WAREHOUSE = compute_wh
  TARGET_LAG = '1 hour'
AS (
    SELECT
        CUSTOMER_NAME,
        STATE,
        ADDRESS_LINE_1,
        ADDRESS_LINE_2,
        CITY,
        COUNTY,
        POSTAL_CODE,
        POSTALCODE_EXTENSION,
        COUNTRY,
        CUSTOMER_BUSINESS_ID
    FROM "MDM_CUSTOMER_MATCHING"."PUBLIC"."CUSTOMER_ADDRESS"
);



CREATE OR REPLACE AGENT snowflake_intelligence.agents.MDM_MATCHING_AGENT WITH PROFILE = '{"display_name":"MDM Matching Agent"}' COMMENT = $$ Master Data Management Matching Agent.
$$
FROM SPECIFICATION $$
{
    "models": {
        "orchestration": "auto"
    },
    "orchestration": {},
    "instructions": {
        "orchestration": "System Role and Goal\n\nYou are an AI assistant designed to manage a Master Data Management (MDM) system. Your primary goal is to help users process, match, and look up customer records.\n\nCore Concepts\n\ncustomer_address table: This table contains the master or \"golden\" records. Each record has a unique customer_business_id.\n\ncustomer_identifier table: This table contains associated records from various source systems. New, unprocessed records are added here and will have a NULL value for customer_business_id.\n\nConfidence Score: This is a cosine similarity score used to determine the quality of a match between a new record and an existing \"golden\" record.\n\nWorkflows\n1. Generate Sample Identifiers\nThis workflow generates and auto-processes a batch of sample records.\n\na) When the user asks to generate sample data, call the GENERATE_CUSTOMER_SAMPLES tool.\nb) Search for matches using SEARCH_ADDRESS_CANDIDATES.\nc) Process using PROCESS_IDENTIFIER_ASSIGN_OR_ERROR with the best match and score.  Assign a status of VALID (for scores > 0.80) or ERROR (for scores <= 0.80).  Show the user these search_confidence_scores when reporting results.\n\nReport the results to the user in the following format:\n\nVALID Matches\n\nFor each valid match, show the matched \"golden\" record next to the new identifier record's details, including the search_confidence_score and confidence_score (cosine similarity).\n\nERROR Records\n\nFor each record marked as an error, display the following fields from the customer_identifier table: customer_name, customer_full_detail, identifier_type, identifier_value, address_role, search_confidence_score.\n\n2. Review and Process Unprocessed Records\nThis workflow allows a user to manually review new records and match them to \"golden\" records.\n\nImportant Rules for this Workflow:\n\nThe system is designed to handle NULL values for customer_business_id in unprocessed records.\n\nIf you encounter database errors related to NULL values or primary keys when querying for unprocessed records, IGNORE THE ERRORS and proceed with the query.\n\nFollow these steps exactly. Do not modify the process.\n\nStep-by-Step Process:\n\nTrigger: This workflow starts when the user asks to review unprocessed records. They may ask for one, a specific number (n), or all of them.\n\nFetch Records: Based on the user's request, retrieve the specified number of unprocessed records from the database.\n\nProcess Each Record: For each record you have retrieved, perform the following steps:\na. Find Matches: Call the SEARCH_ADDRESS_CANDIDATES tool, passing in the customer_full_detail for the current record.\nb. Present to User: Show the user the unprocessed record's details alongside the top 3 potential \"golden\" record matches returned by the search tool. You must display the following:\n- search_confidence_score (from cortex search)\n- confidence_score (similarity vector score directly from address comparison)\n- edit_distance (Levenshtein distance between two input strings)\nc. Ask for Action: Ask the user how to proceed with the current record. Their options are:\n* To assign it to an existing record, use the ASSIGN_IDENTIFIER_TO_BUSINESS_ID tool.\n* To create a new \"golden\" record, use the CREATE_NEW_BUSINESS_ID_AND_ASSIGN tool.\nd. Continue: After the user makes a decision, move to the next record in the queue. Stop only when all requested records are processed or the user asks to stop.\n\n3. Look Up Customer Records\nThis workflow is for finding existing customer data.\n\nWhen a user asks to look up a customer, or any address associated with a customer, use the CUSTOMER_NAME_LOOKUP tool with their search query.\n\nFor the search results, find all associated records in the customer_identifier table.\n\nPresent the top 3 matches to the user. For each match, display the following information:\ncustomer_full_detail\naddress_role\nA hyperlink formatted as http://sourcesystem.com/{identifier_value} with the link text displayed as {identifier_type} Link. The identifier_value and identifier_type fields are columns in the customer_identifier table.\n\n4. If the user asks about unprocessed records, show them a table of the unprocessed records with the customer_name, customer_full_detail, enriched_indicator, search_confidence_score.",
        "sample_questions": [
            {
                "question": "What's the next unprocessed record?"
            },
            {
                "question": "Show me all the records for Sunshine House."
            }
        ]
    },
    "tools": [
        {
            "tool_spec": {
                "type": "cortex_analyst_text_to_sql",
                "name": "Database_Analyst",
                "description": "TABLE1: CUSTOMER_ADDRESS\n- Database: MDM_CUSTOMER_MATCHING, Schema: PUBLIC\n- This table stores comprehensive address information for customers, primarily educational institutions like schools, academies, and districts. It contains detailed mailing addresses with full geographic information including extensions and county details.\n- The table serves as a master address repository with enriched location data and includes customer identification through business IDs. It supports address-based customer matching and verification processes.\n- LIST OF COLUMNS: ADDRESS_LINE_1 (primary street address), ADDRESS_LINE_2 (secondary address info), CITY (customer city location), COUNTRY (country code), COUNTY (county information), CUSTOMER_BUSINESS_ID (unique business identifier - links to CUSTOMER_IDENTIFIER table), CUSTOMER_FULL_DETAIL (complete address details), CUSTOMER_NAME (organization name with synonyms for educational institutions), PHONE (contact number), POSTAL_CODE (zip code), POSTALCODE_EXTENSION (4-digit zip extension), STATE (state code)\n\nTABLE2: CUSTOMER_IDENTIFIER\n- Database: MDM_CUSTOMER_MATCHING, Schema: PUBLIC\n- This table manages customer identification and verification processes, storing various identifier types like NWEA SFDC ID, AgileEd ID, and NCES ID. It includes enrichment status tracking and confidence scoring for data quality assessment.\n- The table contains vector embeddings for advanced matching capabilities and detailed verification messages showing field-level validation results. It tracks creation and update timestamps for audit purposes and maintains confidence scores for matching accuracy.\n- LIST OF COLUMNS: ADDRESS_LINE_1 (street address), ADDRESS_LINE_2 (secondary address), ADDRESS_ROLE (address purpose like warehouse/office/school), CITY (location city), COUNTRY (country identifier), COUNTY (county name), CUSTOMER_BUSINESS_ID (business identifier), CUSTOMER_FULL_DETAIL (complete customer info), CUSTOMER_FULL_DETAIL_EMBEDDING (vector embedding for matching), CUSTOMER_NAME (organization name), ENRICHED_INDICATOR (enrichment status), IDENTIFIER_TYPE (type of customer ID), IDENTIFIER_VALUE (actual identifier), PHONE (phone number), POSTAL_CODE (zip code), POSTALCODE_EXTENSION (zip extension), STATE (state code), VERIFICATION_MESSAGE (field validation results), VERIFICATION_STATUS_CODE (verification status), CREATED_TIMESTAMP (record creation time), UPDATED_TIMESTAMP (last update time), CONFIDENCE_SCORE (matching accuracy score)\n\nREASONING:\nThis semantic model represents a Master Data Management (MDM) system specifically designed for customer matching and verification, with a focus on educational institutions. The two tables work together to provide comprehensive customer identification and address management capabilities. CUSTOMER_ADDRESS serves as the master address repository while CUSTOMER_IDENTIFIER handles the identification, verification, and matching processes. The relationship between tables is established through CUSTOMER_BUSINESS_ID, enabling cross-referencing of address and identifier information. The model includes advanced features like vector embeddings for semantic matching, confidence scoring for data quality, and detailed verification tracking.\n\nDESCRIPTION:\nThe MDM_CUSTOMER_MATCHING_V2 semantic model from the MDM_CUSTOMER_MATCHING database provides comprehensive customer identification and address management capabilities, primarily focused on educational institutions like schools, academies, and districts. The model consists of two interconnected tables: CUSTOMER_ADDRESS (master address repository) and CUSTOMER_IDENTIFIER (identification and verification management), linked through CUSTOMER_BUSINESS_ID. It supports advanced customer matching using vector embeddings, confidence scoring for data quality assessment, and detailed verification tracking with field-level validation results. The system handles various identifier types (NWEA SFDC ID, AgileEd ID, NCES ID) and maintains enrichment status indicators to ensure data completeness and accuracy."
            }
        },
        {
            "tool_spec": {
                "type": "cortex_search",
                "name": "Customer_Name_Lookup",
                "description": "Used to find the closest customer or school name in the customer_address table."
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "Generate_Customer_Samples",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom JavaScript Function\n- Language: JAVASCRIPT\n- Signature: ()\n- Returns: VARIANT (integer count)\n- Execution: CALLER with CALLED ON NULL INPUT\n- Volatility: VOLATILE\n- Primary Function: Test data generation with realistic variations\n- Target: CUSTOMER_IDENTIFIER table in MDM_CUSTOMER_MATCHING schema\n- Error Handling: Basic SQL execution error propagation\n\nDESCRIPTION:\nThis JavaScript function generates synthetic test data for customer matching and data quality testing by creating realistic variations of existing customer records. The function samples 8 records from the CUSTOMER_IDENTIFIER table and 2 records from PUBLIC_SCHOOLS, then generates variants with controlled modifications including exact matches (60%), slight variations like tweaked street numbers or postal codes (30%), and records with intentional typos (10%). Each generated record is enriched with random identifier types, address roles, and computed embeddings using Snowflake's AI_EMBED function for vector similarity matching. The function requires INSERT permissions on the target table and READ permissions on source tables, making it ideal for populating test environments with realistic data that mimics real-world data quality challenges. Users should be cautious when running this in production environments as it directly inserts data and uses random sampling which could impact performance on large datasets.\n\nUSAGE SCENARIOS:\n- Testing customer matching algorithms and data deduplication processes with realistic data variations that simulate common data entry errors and inconsistencies\n- Populating development and staging environments with synthetic customer data that maintains referential integrity while protecting sensitive production information\n- Validating data quality rules and fuzzy matching logic by generating controlled datasets with known relationships between original and variant records"
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "Assign_Identifier_To_Business_Id",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Stored Function\n- Language: SQL\n- Signature: (IDENTIFIER_TYPE VARCHAR, IDENTIFIER_VALUE VARCHAR, CUSTOMER_BUSINESS_ID VARCHAR)\n- Returns: VARCHAR\n- Execution: CALLER with standard null handling\n- Volatility: Volatile (modifies data and uses AI services)\n- Primary Function: Customer data matching and enrichment with AI-powered verification\n- Target: Customer identifier records in MDM_CUSTOMER_MATCHING schema\n- Error Handling: Built-in error handling with TRY_PARSE_JSON and conditional logic\n\nDESCRIPTION:\nThis function performs comprehensive customer data matching and enrichment by assigning a business ID to a specific customer identifier record and computing advanced similarity metrics using vector embeddings and AI analysis. The procedure updates the target customer identifier with the provided business ID, calculates a confidence score using vector cosine similarity between customer detail embeddings, and sets an enrichment indicator based on confidence thresholds (VALID for scores > 0.95, ERROR otherwise). It leverages AI completion services (Mistral-Large2) to generate detailed field-by-field comparison results stored as JSON verification messages, providing granular insights into which customer attributes match between records. This function is essential for master data management workflows where accurate customer matching and data quality assessment are critical for business operations. Users should ensure appropriate permissions for the MDM_CUSTOMER_MATCHING schema and be aware that AI service calls may introduce latency and require external connectivity.\n\nUSAGE SCENARIOS:\n- Data Integration: When onboarding new customer data sources and need to match incoming records against existing master customer records with high confidence scoring\n- Data Quality Management: During routine data cleansing operations to validate customer record accuracy and identify potential duplicates or data inconsistencies\n- Customer Master Data Maintenance: When consolidating customer information from multiple systems and require detailed verification of field-level matches with AI-powered analysis",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "customer_business_id": {
                            "type": "string"
                        },
                        "identifier_type": {
                            "type": "string"
                        },
                        "identifier_value": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "customer_business_id",
                        "identifier_type",
                        "identifier_value"
                    ]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "create_new_business_id_and_assign",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Function\n- Language: SQL\n- Signature: (IDENTIFIER_TYPE VARCHAR, IDENTIFIER_VALUE VARCHAR)\n- Returns: VARCHAR\n- Execution: CALLER with standard null handling\n- Volatility: Volatile (generates new IDs and inserts data)\n- Primary Function: Customer record creation and identifier assignment\n- Target: Customer master data management tables\n- Error Handling: Implicit SQL exception handling with transaction rollback\n\nDESCRIPTION:\nThis SQL function creates a new customer business record by retrieving customer information from an existing identifier, generating a unique business ID, and establishing a complete customer address profile with AI-powered embeddings for enhanced matching capabilities. The function operates within a Master Data Management (MDM) system specifically designed for customer matching and deduplication, automatically computing full customer detail strings and generating vector embeddings using Snowflake's Arctic embedding model for similarity searches. It performs a multi-step process: first fetching customer data from the CUSTOMER_IDENTIFIER table based on the provided identifier type and value, then generating a new business ID using a sequence-based generator, creating a comprehensive address record with computed full details, and finally assigning the original identifier to the new business ID through a separate procedure call. This function is essential for onboarding new customer records into the MDM system while maintaining referential integrity and enabling advanced matching algorithms. Users should ensure they have appropriate permissions to access the MDM schema and understand that this function will create permanent records in the customer address table, making it suitable for production customer data processing workflows.\n\nUSAGE SCENARIOS:\n- Customer onboarding: When integrating new customer data from external systems or applications that need to be registered in the central MDM repository with proper business ID assignment\n- Data migration projects: During system consolidations where existing customer identifiers need to be converted into the standardized MDM business ID format while preserving all address and contact information\n- API integration workflows: When external applications need to programmatically create customer records through automated processes that require consistent business ID generation and proper embedding creation for matching algorithms",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "IDENTIFIER_TYPE": {
                            "description": "customer_identifier.identifier_type field value",
                            "type": "string"
                        },
                        "IDENTIFIER_VALUE": {
                            "description": "customer_indentifier.identifier_value",
                            "type": "string"
                        }
                    },
                    "required": [
                        "IDENTIFIER_TYPE",
                        "IDENTIFIER_VALUE"
                    ]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "populate_verification_messages_batch",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Function\n- Language: SQL\n- Signature: ()\n- Returns: VARCHAR\n- Execution: CALLER with NULL-safe handling\n- Volatility: Volatile (uses AI_COMPLETE)\n- Primary Function: Customer record verification and field-level matching analysis\n- Target: CUSTOMER_IDENTIFIER table records with confidence scores\n- Error Handling: TRY_PARSE_JSON for AI response parsing\n\nDESCRIPTION:\nThis SQL function performs intelligent customer record verification by comparing customer identifier records against their corresponding address records and generating detailed field-level match analysis. The function uses a hybrid approach: for perfect confidence scores (1.0), it automatically generates an \"Identical match\" verification message, while for all other confidence scores, it leverages AI (Mistral-Large2) to perform sophisticated field-by-field comparison of customer data including name, address components, and phone information. The AI analysis produces structured JSON verification messages that indicate which specific fields match between records, enabling data quality teams to understand exactly why records were matched and with what level of certainty. This function is particularly valuable for master data management workflows where understanding the granular reasons behind customer record matching is critical for data governance and compliance. Users should ensure they have appropriate permissions to access both the CUSTOMER_IDENTIFIER and CUSTOMER_ADDRESS tables, and be aware that AI-powered analysis may incur additional computational costs and requires network connectivity to the AI service.\n\nUSAGE SCENARIOS:\n- Data quality audits where detailed field-level matching explanations are needed for regulatory compliance or data governance reporting\n- Customer master data management processes that require transparent matching logic and verification trails for downstream systems\n- Development and testing environments where data analysts need to validate and fine-tune customer matching algorithms before production deployment"
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "GENERATE_CUSTOMER_BUSINESS_ID",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Function\n- Language: SQL\n- Signature: (SEQ_VALUE NUMBER)\n- Returns: VARCHAR\n- Execution: Standard SQL function with deterministic behavior\n- Volatility: Immutable (same input always produces same output)\n- Primary Function: Customer ID generation with embedded check digit\n- Target: Sequential numbering system for customer identification\n- Error Handling: Relies on standard SQL error handling for invalid inputs\n\nDESCRIPTION:\nThis custom SQL function generates standardized customer identification codes by combining a fixed prefix \"CUS\" with a zero-padded 9-digit sequence number and an alphanumeric check digit. The function takes a numeric sequence value as input and transforms it into a 13-character customer ID format (CUS + 9 digits + 1 check character), where the check digit is calculated using modulo 36 arithmetic to produce either a digit (0-9) or letter (A-Z). This function is designed for applications requiring unique, sequential customer identifiers with built-in validation capabilities through the embedded check digit. The function should be used when creating new customer records or migrating existing customer data to ensure consistent ID formatting across the system. Users should ensure they have appropriate database permissions to execute custom functions and should validate that input sequence values are positive integers to avoid unexpected results.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "seq_value": {
                            "type": "number"
                        }
                    },
                    "required": [
                        "seq_value"
                    ]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "PROCESS_IDENTIFIER_ASSIGN_OR_ERROR",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Function\n- Language: SQL\n- Signature: (IDENTIFIER_TYPE VARCHAR, IDENTIFIER_VALUE VARCHAR, CANDIDATE_CUSTOMER_BUSINESS_ID VARCHAR, SCORE FLOAT, THRESHOLD FLOAT)\n- Returns: VARCHAR\n- Execution: CALLER with standard null handling\n- Volatility: Volatile (modifies data)\n- Primary Function: Conditional customer identifier assignment with scoring validation\n- Target: Customer identifier records and business ID assignments\n- Error Handling: Automatic error marking for failed assignments\n\nDESCRIPTION:\nThis custom SQL function performs intelligent customer identifier assignment based on confidence scoring within a Master Data Management (MDM) system. The function evaluates whether a candidate customer business ID should be assigned to a specific identifier by comparing a provided confidence score against a defined threshold. When the score exceeds the threshold and a valid candidate business ID is provided, it automatically assigns the identifier to the business entity through a dedicated assignment procedure and returns 'ASSIGNED'. If the conditions are not met (low confidence score or missing candidate ID), the function marks the customer identifier record with an 'ERROR' status in the enrichment indicator field and returns 'ERROR_MARKED'. This function is essential for automated customer matching workflows where data quality and confidence levels must be maintained, requiring appropriate database permissions to modify customer identifier tables and execute related assignment procedures.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "candidate_customer_business_id": {
                            "type": "string"
                        },
                        "identifier_type": {
                            "type": "string"
                        },
                        "identifier_value": {
                            "type": "string"
                        },
                        "score": {
                            "type": "number"
                        },
                        "threshold": {
                            "type": "number"
                        }
                    },
                    "required": [
                        "candidate_customer_business_id",
                        "identifier_type",
                        "identifier_value",
                        "score",
                        "threshold"
                    ]
                }
            }
        },
        {
            "tool_spec": {
                "type": "generic",
                "name": "SEARCH_ADDRESS_CANDIDATES",
                "description": "PROCEDURE/FUNCTION DETAILS:\n- Type: Custom Function\n- Language: JavaScript\n- Signature: (QUERY VARCHAR)\n- Returns: VARIANT\n- Execution: CALLER with CALLED ON NULL INPUT\n- Volatility: VOLATILE\n- Primary Function: Customer address search using Snowflake Cortex AI\n- Target: MDM_CUSTOMER_ADDRESS_SEARCH search service\n- Error Handling: Returns null if no results found\n\nDESCRIPTION:\nThis JavaScript function provides intelligent customer address search capabilities by leveraging Snowflake's Cortex AI search functionality against a master data management (MDM) customer address repository. The function accepts a natural language query parameter and searches across comprehensive customer address fields including full details, business IDs, names, and complete address components (street, city, county, state, postal codes, and country). It utilizes the MDM_CUSTOMER_ADDRESS_SEARCH service to perform semantic search operations, returning structured JSON results that can be easily parsed and integrated into business applications. The function executes with caller privileges, meaning users need appropriate permissions to access the underlying Cortex search service and customer data repository. Since it's marked as volatile, results are not cached, ensuring real-time search capabilities but potentially impacting performance for repeated identical queries.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "query"
                    ]
                }
            }
        }
    ],
    "tool_resources": {
        "Assign_Identifier_To_Business_Id": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.ASSIGN_IDENTIFIER_TO_BUSINESS_ID",
            "name": "ASSIGN_IDENTIFIER_TO_BUSINESS_ID(VARCHAR, VARCHAR, VARCHAR)",
            "type": "procedure"
        },
        "Customer_Name_Lookup": {
            "id_column": "CUSTOMER_BUSINESS_ID",
            "max_results": 3,
            "name": "MDM_CUSTOMER_MATCHING.PUBLIC.MDM_CUSTOMER_NAME_LOOKUP",
            "title_column": "CUSTOMER_NAME"
        },
        "Database_Analyst": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "semantic_model_file": "@MDM_CUSTOMER_MATCHING.PUBLIC.SEMANTIC_MODELS/MDM_CUSTOMER_MATCHING_V2.yaml"
        },
        "GENERATE_CUSTOMER_BUSINESS_ID": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.GENERATE_CUSTOMER_BUSINESS_ID",
            "name": "GENERATE_CUSTOMER_BUSINESS_ID(NUMBER)",
            "type": "function"
        },
        "Generate_Customer_Samples": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.GENERATE_CUSTOMER_SAMPLES",
            "name": "GENERATE_CUSTOMER_SAMPLES()",
            "type": "procedure"
        },
        "PROCESS_IDENTIFIER_ASSIGN_OR_ERROR": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.PROCESS_IDENTIFIER_ASSIGN_OR_ERROR",
            "name": "PROCESS_IDENTIFIER_ASSIGN_OR_ERROR(VARCHAR, VARCHAR, VARCHAR, FLOAT, DEFAULT FLOAT)",
            "type": "procedure"
        },
        "SEARCH_ADDRESS_CANDIDATES": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.SEARCH_ADDRESS_CANDIDATES_SP",
            "name": "SEARCH_ADDRESS_CANDIDATES_SP(VARCHAR)",
            "type": "procedure"
        },
        "create_new_business_id_and_assign": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.CREATE_AND_ASSIGN_NEW_CUSTOMER_ADDRESS_FROM_CI",
            "name": "CREATE_AND_ASSIGN_NEW_CUSTOMER_ADDRESS_FROM_CI(VARCHAR, VARCHAR)",
            "type": "procedure"
        },
        "populate_verification_messages_batch": {
            "execution_environment": {
                "type": "warehouse",
                "warehouse": ""
            },
            "identifier": "MDM_CUSTOMER_MATCHING.PUBLIC.POPULATE_VERIFICATION_MESSAGE_SQL",
            "name": "POPULATE_VERIFICATION_MESSAGE_SQL()",
            "type": "procedure"
        }
    }
}
$$;


