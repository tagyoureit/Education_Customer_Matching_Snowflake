-- Use SQL for a more efficient, set-based approach
USE ROLE SYSADMIN;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.POPULATE_VERIFICATION_MESSAGE_SQL()
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
  UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
  SET
    VERIFICATION_MESSAGE =
      CASE
        -- Condition 1: Hardcode for perfect confidence scores
        WHEN ci.CONFIDENCE_SCORE = 1 THEN
          OBJECT_CONSTRUCT(
            'reason', 'Identical match',
            'name', TRUE, 'address_line_1', TRUE, 'address_line_2', TRUE,
            'city', TRUE, 'county', TRUE, 'state', TRUE, 'postal_code', TRUE,
            'postalcode_extension', TRUE, 'country', TRUE, 'phone', TRUE
          )
        -- Condition 2: Use AI for all other non-null scores
        ELSE
          TRY_PARSE_JSON(
            AI_COMPLETE(
              'mistral-large2',
              -- Prompt is constructed dynamically for each row using SQL
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
              }, -- model_parameters
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
                  'required': [
                    'reason','name','address_line_1','address_line_2','city','county','state','postal_code','postalcode_extension','country','phone'
                  ]
                }
              } -- response_format
            )
          )
      END
  FROM
    MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
  WHERE
    ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
    AND ci.CONFIDENCE_SCORE IS NOT NULL;

  RETURN 'Rows updated: ' || SQLROWCOUNT;
END;
$$;