-- Stored procedures to support agent single-record operations
-- Reference: @Snowflake Docs

USE ROLE MDM_CUSTOMER_MATCHING_ROLE;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

--
-- Assign an existing CUSTOMER_IDENTIFIER to a CUSTOMER_BUSINESS_ID and update derived fields
--
CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.ASSIGN_IDENTIFIER_TO_BUSINESS_ID(
  IDENTIFIER_TYPE VARCHAR,
  IDENTIFIER_VALUE VARCHAR,
  CUSTOMER_BUSINESS_ID VARCHAR
)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
  -- 1) Assign BUSINESS ID
  UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
  SET CUSTOMER_BUSINESS_ID = :CUSTOMER_BUSINESS_ID
  WHERE IDENTIFIER_TYPE = :IDENTIFIER_TYPE
    AND IDENTIFIER_VALUE = :IDENTIFIER_VALUE;

  -- 2) Recompute confidence for this CI row
  UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
  SET CONFIDENCE_SCORE = VECTOR_COSINE_SIMILARITY(ca.CUSTOMER_FULL_DETAIL_EMBEDDING, ci.CUSTOMER_FULL_DETAIL_EMBEDDING)
  FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
  WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
    AND ci.IDENTIFIER_TYPE = :IDENTIFIER_TYPE
    AND ci.IDENTIFIER_VALUE = :IDENTIFIER_VALUE;

  -- 3) Update enriched indicator
  UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
  SET ENRICHED_INDICATOR = (CASE WHEN CONFIDENCE_SCORE > 90 THEN 'VALID' ELSE 'ERROR' END)
  WHERE IDENTIFIER_TYPE = :IDENTIFIER_TYPE
    AND IDENTIFIER_VALUE = :IDENTIFIER_VALUE
    AND CONFIDENCE_SCORE IS NOT NULL;

  -- 4) Populate verification message for this specific row
  UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
  SET VERIFICATION_MESSAGE =
    CASE
      WHEN ci.CONFIDENCE_SCORE = 1 THEN
        OBJECT_CONSTRUCT(
          'reason','Identical match',
          'name',TRUE,'address_line_1',TRUE,'address_line_2',TRUE,
          'city',TRUE,'county',TRUE,'state',TRUE,'postal_code',TRUE,
          'postalcode_extension',TRUE,'country',TRUE,'phone',TRUE
        )
      ELSE
        TRY_PARSE_JSON(
          AI_COMPLETE(
            'llama3.1-8b',
            CONCAT_WS(
              '',
              'You are given two customer records (A and B). Compare the fields case-insensitively, trimming whitespace and treating NULL as empty. ',
              'Return a JSON object matching the exact schema with booleans set to TRUE when the fields MATCH and FALSE when they DO NOT MATCH. ',
              'If all fields match, set reason to "Identical match". ',
              'Fields: name, address_line_1, address_line_2, city, county, state, postal_code, postalcode_extension, country, phone. ',
              'Record A => ',
              'Name: ', NVL(ci.CUSTOMER_NAME,''), '; ',
              'Address Line 1: ', NVL(ci.ADDRESS_LINE_1,''), '; ',
              'Address Line 2: ', NVL(ci.ADDRESS_LINE_2,''), '; ',
              'City: ', NVL(ci.CITY,''), '; ',
              'County: ', NVL(ci.COUNTY,''), '; ',
              'State: ', NVL(ci.STATE,''), '; ',
              'Postal Code: ', NVL(ci.POSTAL_CODE,''), '; ',
              'PostalCode Extension: ', NVL(ci.POSTALCODE_EXTENSION,''), '; ',
              'Country: ', NVL(ci.COUNTRY,''), '; ',
              'Phone: ', NVL(ci.PHONE,''),
              '. Record B => ',
              'Name: ', NVL(ca.CUSTOMER_NAME,''), '; ',
              'Address Line 1: ', NVL(ca.ADDRESS_LINE_1,''), '; ',
              'Address Line 2: ', NVL(ca.ADDRESS_LINE_2,''), '; ',
              'City: ', NVL(ca.CITY,''), '; ',
              'County: ', NVL(ca.COUNTY,''), '; ',
              'State: ', NVL(ca.STATE,''), '; ',
              'Postal Code: ', NVL(ca.POSTAL_CODE,''), '; ',
              'PostalCode Extension: ', NVL(ca.POSTALCODE_EXTENSION,''), '; ',
              'Country: ', NVL(ca.COUNTRY,''), '; ',
              'Phone: ', NVL(ca.PHONE,''),
              '.'
            ),
            {
              'temperature': 0,
              'max_tokens': 512
            },
            {
              'type': 'json',
              'schema': {
                'type': 'object',
                'properties': {
                  'reason': { 'type': 'string' },
                  'name': { 'type': 'boolean' },
                  'address_line_1': { 'type': 'boolean' },
                  'address_line_2': { 'type': 'boolean' },
                  'city': { 'type': 'boolean' },
                  'county': { 'type': 'boolean' },
                  'state': { 'type': 'boolean' },
                  'postal_code': { 'type': 'boolean' },
                  'postalcode_extension': { 'type': 'boolean' },
                  'country': { 'type': 'boolean' },
                  'phone': { 'type': 'boolean' }
                },
                'required': ['reason','name','address_line_1','address_line_2','city','county','state','postal_code','postalcode_extension','country','phone']
              }
            }
          )
        )
    END
  FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
  WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
    AND ci.IDENTIFIER_TYPE = :IDENTIFIER_TYPE
    AND ci.IDENTIFIER_VALUE = :IDENTIFIER_VALUE;

  RETURN 'ASSIGNED';
END;
$$;



-- Wrapper around MDM_CUSTOMER_ADDRESS_SEARCH as a stored procedure (accepts dynamic inputs)
-- Reference: @Snowflake Docs
CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.SEARCH_ADDRESS_CANDIDATES_SP(
  QUERY VARCHAR
)
RETURNS VARIANT
LANGUAGE JAVASCRIPT
EXECUTE AS OWNER
AS
$$
var payload = {
  query: QUERY,
  columns: [
    'customer_full_detail',
    'customer_business_id',
    'customer_name',
    'address_line_1',
    'address_line_2',
    'city',
    'county',
    'state',
    'postal_code',
    'postalcode_extension',
    'country'
  ],
  limit: 3
};

var payloadStr = JSON.stringify(payload).replace(/'/g, "''");
var sql = "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(\n" +
          "  'MDM_CUSTOMER_ADDRESS_SEARCH',\n" +
          "  '" + payloadStr + "'\n" +
          "))";
var stmt = snowflake.createStatement({ sqlText: sql });
var rs = stmt.execute();
if (rs.next()) {
  return rs.getColumnValue(1);
}
return null;
$$;

--
-- Process single identifier: assign if score > threshold and candidate provided; else mark ERROR
-- Default threshold set to 0.90 per requirements
--
CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.PROCESS_IDENTIFIER_ASSIGN_OR_ERROR(
  IDENTIFIER_TYPE VARCHAR,
  IDENTIFIER_VALUE VARCHAR,
  CANDIDATE_CUSTOMER_BUSINESS_ID VARCHAR,
  SCORE FLOAT,
  THRESHOLD FLOAT DEFAULT 0.90
)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
  IF (CANDIDATE_CUSTOMER_BUSINESS_ID IS NOT NULL AND SCORE > THRESHOLD) THEN
    CALL MDM_CUSTOMER_MATCHING.PUBLIC.ASSIGN_IDENTIFIER_TO_BUSINESS_ID(
      :IDENTIFIER_TYPE,
      :IDENTIFIER_VALUE,
      :CANDIDATE_CUSTOMER_BUSINESS_ID
    );
    RETURN 'ASSIGNED';
  ELSE
    UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
    SET ENRICHED_INDICATOR = 'ERROR'
    WHERE IDENTIFIER_TYPE = :IDENTIFIER_TYPE
      AND IDENTIFIER_VALUE = :IDENTIFIER_VALUE;
    RETURN 'ERROR_MARKED';
  END IF;
END;
$$;

--
-- Create a new CUSTOMER_ADDRESS from a CI row and assign the CI to it
--
CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.CREATE_AND_ASSIGN_NEW_CUSTOMER_ADDRESS_FROM_CI(
  IDENTIFIER_TYPE VARCHAR,
  IDENTIFIER_VALUE VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  NEW_ID VARCHAR;
  C_NAME VARCHAR;
  A1 VARCHAR;
  A2 VARCHAR;
  CITY VARCHAR;
  COUNTY VARCHAR;
  STATE VARCHAR;
  POSTAL VARCHAR;
  POSTALX VARCHAR;
  COUNTRY VARCHAR;
  PHONE VARCHAR;
BEGIN
  -- Fetch CI fields
  SELECT 
    CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE
  INTO 
    :C_NAME, :A1, :A2, :CITY, :COUNTY, :STATE, :POSTAL, :POSTALX, :COUNTRY, :PHONE
  FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
  WHERE IDENTIFIER_TYPE = :IDENTIFIER_TYPE
    AND IDENTIFIER_VALUE = :IDENTIFIER_VALUE
  LIMIT 1;

  -- Generate new business id
  SELECT MDM_CUSTOMER_MATCHING.PUBLIC.GENERATE_CUSTOMER_BUSINESS_ID(MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_BUSINESS_ID_SEQ.NEXTVAL)
  INTO :NEW_ID;

  -- Insert new address with computed full detail and embedding
  INSERT INTO MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS (
    CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE,
    POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE, CUSTOMER_FULL_DETAIL, CUSTOMER_FULL_DETAIL_EMBEDDING
  )
  SELECT
    :NEW_ID,
    :C_NAME, :A1, :A2, :CITY, :COUNTY, :STATE,
    :POSTAL, :POSTALX, :COUNTRY, :PHONE,
    RTRIM(
      ARRAY_TO_STRING(
        ARRAY_CONSTRUCT_COMPACT(
          IFF(TRIM(:C_NAME) = '', NULL, TRIM(:C_NAME)),
          IFF(TRIM(:A1) = '', NULL, TRIM(:A1)),
          IFF(TRIM(:A2) = '', NULL, TRIM(:A2)),
          IFF(TRIM(:CITY) = '', NULL, TRIM(:CITY)),
          IFF(TRIM(:STATE) = '', NULL, TRIM(:STATE)),
          IFF(TRIM(:POSTAL) = '', NULL, TRIM(:POSTAL))
        ),
        ', '
      )
    ) AS CUSTOMER_FULL_DETAIL,
    AI_EMBED('snowflake-arctic-embed-m-v1.5', RTRIM(
      ARRAY_TO_STRING(
        ARRAY_CONSTRUCT_COMPACT(
          IFF(TRIM(:C_NAME) = '', NULL, TRIM(:C_NAME)),
          IFF(TRIM(:A1) = '', NULL, TRIM(:A1)),
          IFF(TRIM(:A2) = '', NULL, TRIM(:A2)),
          IFF(TRIM(:CITY) = '', NULL, TRIM(:CITY)),
          IFF(TRIM(:STATE) = '', NULL, TRIM(:STATE)),
          IFF(TRIM(:POSTAL) = '', NULL, TRIM(:POSTAL))
        ),
        ', '
      )
    )) AS CUSTOMER_FULL_DETAIL_EMBEDDING;

  -- Assign CI to the new id with derived updates
  CALL MDM_CUSTOMER_MATCHING.PUBLIC.ASSIGN_IDENTIFIER_TO_BUSINESS_ID(:IDENTIFIER_TYPE, :IDENTIFIER_VALUE, :NEW_ID);

  RETURN :NEW_ID;
END;
$$;


