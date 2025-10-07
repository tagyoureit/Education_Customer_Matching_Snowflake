-- Benchmark Cortex models for latency on representative prompts
-- Reference: Snowflake Docs (Cortex LLM Functions, Model availability)

USE ROLE MDM_CUSTOMER_MATCHING_ROLE;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.BENCHMARK_CORTEX_MODELS()
RETURNS VARIANT
LANGUAGE JAVASCRIPT
EXECUTE AS CALLER
AS
$$
var results = [];

// Models to compare
var models = ['mistral-large2', 'mistral-7b', 'llama3.1-8b'];

// Structured output schema used in production verification logic
var responseFormat = {
  type: 'json',
  schema: {
    type: 'object',
    properties: {
      reason: { type: 'string' },
      name: { type: 'boolean' },
      address_line_1: { type: 'boolean' },
      address_line_2: { type: 'boolean' },
      city: { type: 'boolean' },
      county: { type: 'boolean' },
      state: { type: 'boolean' },
      postal_code: { type: 'boolean' },
      postalcode_extension: { type: 'boolean' },
      country: { type: 'boolean' },
      phone: { type: 'boolean' }
    },
    required: ['reason','name','address_line_1','address_line_2','city','county','state','postal_code','postalcode_extension','country','phone']
  }
};

var modelParams = { temperature: 0, max_tokens: 512 };

// Helper to fetch one representative prompt constructed in SQL like production
function fetchPrompt() {
  var sql = `
    SELECT CONCAT_WS(
      '',
      'You are given two customer records (A and B). Compare the fields case-insensitively, trimming whitespace and treating NULL as empty. ',
      'Return a JSON object matching the exact schema with booleans set to TRUE when the fields MATCH and FALSE when they DO NOT MATCH. ',
      'For the reason field, give your best explanation of why they do not match.  If they are a close match, should this 1st record be assumed to be the same as the second "Golden" record anyway or is it a completely new customer/address. ',
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
    ) AS PROMPT
    FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
    JOIN MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
      ON ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
    WHERE ci.CONFIDENCE_SCORE > 0.90
    ORDER BY RANDOM()
    LIMIT 1`;
  var stmt = snowflake.createStatement({ sqlText: sql });
  var rs = stmt.execute();
  if (rs.next()) {
    return rs.getColumnValue('PROMPT');
  }
  return 'Compare two customer records and produce the schema as JSON.';
}

var iterations = 5;
for (var i = 1; i <= iterations; i++) {
  var prompt = fetchPrompt();
  var promptLen = (prompt == null ? 0 : ('' + prompt).length);

  for (var m = 0; m < models.length; m++) {
    var model = models[m];
    var started = Date.now();

    // Execute AI_COMPLETE with structured outputs (same as production)
    var aiSql = `
      SELECT AI_COMPLETE(
        ?,
        ?,
        PARSE_JSON(?)::VARIANT,
        PARSE_JSON(?)::VARIANT
      ) AS RESP`;
    var aiStmt = snowflake.createStatement({
      sqlText: aiSql,
      binds: [model, prompt, JSON.stringify(modelParams).replace(/'/g, "''"), JSON.stringify(responseFormat).replace(/'/g, "''")] 
    });

    var respStr = '';
    try {
      var rs = aiStmt.execute();
      if (rs.next()) {
        var v = rs.getColumnValue('RESP');
        respStr = (v == null ? '' : '' + v);
      }
      var ended = Date.now();
      var durationMs = ended - started;

      results.push({
        iteration: i,
        model: model,
        duration_ms: durationMs,
        prompt_chars: promptLen,
        response_chars: respStr.length
      });
    } catch (e) {
      var endedErr = Date.now();
      results.push({
        iteration: i,
        model: model,
        duration_ms: endedErr - started,
        prompt_chars: promptLen,
        response_chars: 0,
        error: '' + e
      });
    }
  }
}

return results;
$$;

-- Example manual run:
-- USE DATABASE MDM_CUSTOMER_MATCHING; USE SCHEMA PUBLIC; CALL MDM_CUSTOMER_MATCHING.PUBLIC.BENCHMARK_CORTEX_MODELS(5);


