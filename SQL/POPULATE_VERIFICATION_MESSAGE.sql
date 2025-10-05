-- Populate VERIFICATION_MESSAGE on CUSTOMER_IDENTIFIER using AI_COMPLETE
-- - Overwrites existing values
-- - Compares CI vs CA on CUSTOMER_BUSINESS_ID
-- - Booleans are computed deterministically (case-insensitive, NULL treated as empty)
-- - If CONFIDENCE_SCORE = 1 then reason = 'Identical match' and all booleans = false
-- References: @Snowflake Docs
--   AI_COMPLETE: https://docs.snowflake.com/en/sql-reference/functions/ai_complete
--   OBJECT_CONSTRUCT: https://docs.snowflake.com/en/sql-reference/functions/object_construct

USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

-- Step 1: Deterministic hardcode for perfect confidence rows
UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
SET VERIFICATION_MESSAGE = OBJECT_CONSTRUCT(
  'reason', 'Identical match',
  'name', TRUE,
  'address_line_1', TRUE,
  'address_line_2', TRUE,
  'city', TRUE,
  'county', TRUE,
  'state', TRUE,
  'postal_code', TRUE,
  'postalcode_extension', TRUE,
  'country', TRUE,
  'phone', TRUE
)
FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
  AND ci.CONFIDENCE_SCORE = 1;

-- Step 2: Set-based, deterministic comparison for rows with scores (no AI, robust JSON). Reference: @Snowflake Docs
UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
SET VERIFICATION_MESSAGE = OBJECT_CONSTRUCT(
  'reason', IFF(
    (TRIM(UPPER(NVL(ci.CUSTOMER_NAME,''))) = TRIM(UPPER(NVL(ca.CUSTOMER_NAME,''))) AND
     TRIM(UPPER(NVL(ci.ADDRESS_LINE_1,''))) = TRIM(UPPER(NVL(ca.ADDRESS_LINE_1,''))) AND
     TRIM(UPPER(NVL(ci.ADDRESS_LINE_2,''))) = TRIM(UPPER(NVL(ca.ADDRESS_LINE_2,''))) AND
     TRIM(UPPER(NVL(ci.CITY,''))) = TRIM(UPPER(NVL(ca.CITY,''))) AND
     TRIM(UPPER(NVL(ci.COUNTY,''))) = TRIM(UPPER(NVL(ca.COUNTY,''))) AND
     TRIM(UPPER(NVL(ci.STATE,''))) = TRIM(UPPER(NVL(ca.STATE,''))) AND
     TRIM(UPPER(NVL(ci.POSTAL_CODE,''))) = TRIM(UPPER(NVL(ca.POSTAL_CODE,''))) AND
     TRIM(UPPER(NVL(ci.POSTALCODE_EXTENSION,''))) = TRIM(UPPER(NVL(ca.POSTALCODE_EXTENSION,''))) AND
     TRIM(UPPER(NVL(ci.COUNTRY,''))) = TRIM(UPPER(NVL(ca.COUNTRY,''))) AND
     TRIM(UPPER(NVL(ci.PHONE,''))) = TRIM(UPPER(NVL(ca.PHONE,'')))
    ), 'Identical match', 'Field-wise comparison' ),
  'name', TRIM(UPPER(NVL(ci.CUSTOMER_NAME,''))) = TRIM(UPPER(NVL(ca.CUSTOMER_NAME,''))),
  'address_line_1', TRIM(UPPER(NVL(ci.ADDRESS_LINE_1,''))) = TRIM(UPPER(NVL(ca.ADDRESS_LINE_1,''))),
  'address_line_2', TRIM(UPPER(NVL(ci.ADDRESS_LINE_2,''))) = TRIM(UPPER(NVL(ca.ADDRESS_LINE_2,''))),
  'city', TRIM(UPPER(NVL(ci.CITY,''))) = TRIM(UPPER(NVL(ca.CITY,''))),
  'county', TRIM(UPPER(NVL(ci.COUNTY,''))) = TRIM(UPPER(NVL(ca.COUNTY,''))),
  'state', TRIM(UPPER(NVL(ci.STATE,''))) = TRIM(UPPER(NVL(ca.STATE,''))),
  'postal_code', TRIM(UPPER(NVL(ci.POSTAL_CODE,''))) = TRIM(UPPER(NVL(ca.POSTAL_CODE,''))),
  'postalcode_extension', TRIM(UPPER(NVL(ci.POSTALCODE_EXTENSION,''))) = TRIM(UPPER(NVL(ca.POSTALCODE_EXTENSION,''))),
  'country', TRIM(UPPER(NVL(ci.COUNTRY,''))) = TRIM(UPPER(NVL(ca.COUNTRY,''))),
  'phone', TRIM(UPPER(NVL(ci.PHONE,''))) = TRIM(UPPER(NVL(ca.PHONE,'')))
)
FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
  AND ci.ENRICHED_INDICATOR = 'VALID';


