-- Stored Procedure to generate 10 modified identifier rows
--  - 8 random from CUSTOMER_IDENTIFIER
--  - 2 random from PUBLIC_SCHOOLS
-- Inserts back into MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
-- Reference: @Snowflake Docs

USE ROLE MDM_CUSTOMER_MATCHING_ROLE;
USE DATABASE MDM_CUSTOMER_MATCHING;
USE SCHEMA PUBLIC;

CREATE OR REPLACE PROCEDURE MDM_CUSTOMER_MATCHING.PUBLIC.GENERATE_CUSTOMER_SAMPLES()
RETURNS VARIANT
LANGUAGE JAVASCRIPT
EXECUTE AS CALLER
AS
$$
// Helper: random choice
function randomChoice(arrayValues) {
  return arrayValues[Math.floor(Math.random() * arrayValues.length)];
}

// Helper: random int inclusive
function randomInt(minInclusive, maxInclusive) {
  return Math.floor(Math.random() * (maxInclusive - minInclusive + 1)) + minInclusive;
}

// Helper: random opaque identifier value
function randomIdentifierValue(len) {
  var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  var out = '';
  for (var i = 0; i < len; i++) {
    out += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }
  return out;
}

// Tweak street number like Python version
function tweakStreetNumber(addressLine1) {
  if (!addressLine1) return addressLine1;
  var trimmed = ('' + addressLine1).trim();
  var match = trimmed.match(/^(\d+)(.*)$/);
  if (!match) return addressLine1;
  var numStr = match[1];
  var rest = match[2];
  var num = parseInt(numStr, 10);
  if (isNaN(num)) return addressLine1;
  var deltas = [-2, -1, 1, 2];
  var delta = randomChoice(deltas);
  var newNum = Math.max(1, num + delta);
  return newNum.toString() + rest;
}

// Tweak postal code by changing last character
function tweakPostalCode(postalCode) {
  if (!postalCode) return postalCode;
  var pc = '' + postalCode;
  var last = pc.charAt(pc.length - 1);
  var choices = '0123456789';
  var replacement = last;
  while (replacement === last) {
    replacement = choices.charAt(Math.floor(Math.random() * choices.length));
  }
  return pc.substring(0, pc.length - 1) + replacement;
}

// Introduce a small typo into a string
function introduceTypo(value) {
  if (!value) return value;
  var s = '' + value;
  if (s.length < 3) return value;
  var ops = ['delete', 'swap', 'substitute', 'insert'];
  var op = randomChoice(ops);
  var i = randomInt(0, s.length - 2);
  if (op === 'delete') {
    return s.substring(0, i) + s.substring(i + 1);
  }
  if (op === 'swap') {
    return s.substring(0, i) + s.charAt(i + 1) + s.charAt(i) + s.substring(i + 2);
  }
  if (op === 'substitute') {
    var alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var ch = alphabet.charAt(Math.floor(Math.random() * alphabet.length));
    return s.substring(0, i) + ch + s.substring(i + 1);
  }
  // insert
  var alphabet2 = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  var ch2 = alphabet2.charAt(Math.floor(Math.random() * alphabet2.length));
  return s.substring(0, i) + ch2 + s.substring(i);
}

function makeSlightVariations(row) {
  var out = Object.assign({}, row);
  if (Math.random() < 0.7) {
    out.ADDRESS_LINE_1 = tweakStreetNumber(out.ADDRESS_LINE_1);
  }
  if (Math.random() < 0.6) {
    out.POSTAL_CODE = tweakPostalCode(out.POSTAL_CODE);
  }
  return out;
}

function makeTypoVariant(row) {
  var out = Object.assign({}, row);
  var fields = ['CUSTOMER_NAME', 'ADDRESS_LINE_1', 'CITY'];
  var field = randomChoice(fields);
  out[field] = introduceTypo(out[field]);
  return out;
}

function generateVariantFromBase(base) {
  // Choose category with weights 0.6 exact, 0.3 slight, 0.1 typo
  var r = Math.random();
  var category = 'exact';
  if (r < 0.6) category = 'exact';
  else if (r < 0.9) category = 'slight';
  else category = 'typo';

  var record = Object.assign({}, base);
  if (category === 'slight') {
    record = makeSlightVariations(record);
  } else if (category === 'typo') {
    record = makeTypoVariant(record);
  }

  // Identifier enrichments
  var IDENTIFIER_TYPES = [
    'NWEA SFDC ID', 'NCES ID', 'SAP Customer Number', 'HMH ID', 'HMH Ref ID', 'HMH SFDC ID', 'AgileEd ID'
  ];
  var ADDRESS_ROLES = ['OFFICE', 'WAREHOUSE', 'SCHOOL'];

  record.IDENTIFIER_TYPE = randomChoice(IDENTIFIER_TYPES);
  record.IDENTIFIER_VALUE = randomIdentifierValue(12);
  record.ADDRESS_ROLE = randomChoice(ADDRESS_ROLES);

  // Optional fields not populated
  record.VERIFICATION_STATUS_CODE = null;
  record.VERIFICATION_MESSAGE = null;
  record.ENRICHED_INDICATOR = null;
  record.CONFIDENCE_SCORE = null;
  record.CUSTOMER_FULL_DETAIL = null;

  return record;
}

function buildBaseRowFromCI(row) {
  return {
    CUSTOMER_BUSINESS_ID: null,
    CUSTOMER_NAME: row.CUSTOMER_NAME,
    ADDRESS_LINE_1: row.ADDRESS_LINE_1,
    ADDRESS_LINE_2: row.ADDRESS_LINE_2,
    CITY: row.CITY,
    COUNTY: row.COUNTY,
    STATE: row.STATE,
    POSTAL_CODE: row.POSTAL_CODE,
    POSTALCODE_EXTENSION: row.POSTALCODE_EXTENSION,
    COUNTRY: row.COUNTRY,
    PHONE: row.PHONE
  };
}

function buildBaseRowFromSchools(row) {
  // Map NCES/public schools columns to our target fields
  return {
    CUSTOMER_BUSINESS_ID: null,
    CUSTOMER_NAME: row.NAME,
    ADDRESS_LINE_1: row.ADDRESS,
    ADDRESS_LINE_2: null,
    CITY: row.CITY,
    COUNTY: row.COUNTY,
    STATE: row.STATE,
    POSTAL_CODE: (row.ZIP == null ? null : ('' + row.ZIP)),
    POSTALCODE_EXTENSION: row.ZIP4,
    COUNTRY: (row.COUNTRY == null ? 'US' : row.COUNTRY),
    PHONE: row.TELEPHONE
  };
}

// Prepare source rows: 8 from CUSTOMER_IDENTIFIER
var ciStmt = snowflake.createStatement({
  sqlText: 
    `SELECT CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE
     FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
     ORDER BY RANDOM() LIMIT 8`
});
var ciRows = [];
var ciRS = ciStmt.execute();
while (ciRS.next()) {
  ciRows.push({
    CUSTOMER_NAME: ciRS.getColumnValue('CUSTOMER_NAME'),
    ADDRESS_LINE_1: ciRS.getColumnValue('ADDRESS_LINE_1'),
    ADDRESS_LINE_2: ciRS.getColumnValue('ADDRESS_LINE_2'),
    CITY: ciRS.getColumnValue('CITY'),
    COUNTY: ciRS.getColumnValue('COUNTY'),
    STATE: ciRS.getColumnValue('STATE'),
    POSTAL_CODE: ciRS.getColumnValue('POSTAL_CODE'),
    POSTALCODE_EXTENSION: ciRS.getColumnValue('POSTALCODE_EXTENSION'),
    COUNTRY: ciRS.getColumnValue('COUNTRY'),
    PHONE: ciRS.getColumnValue('PHONE')
  });
}

// 2 from PUBLIC_SCHOOLS
var schStmt = snowflake.createStatement({
  sqlText:
    `SELECT NAME, ADDRESS, CITY, COUNTY, STATE, ZIP, ZIP4, COUNTRY, TELEPHONE
     FROM MDM_CUSTOMER_MATCHING.PUBLIC.PUBLIC_SCHOOLS
     ORDER BY RANDOM() LIMIT 2`
});
var schRows = [];
var schRS = schStmt.execute();
while (schRS.next()) {
  schRows.push({
    NAME: schRS.getColumnValue('NAME'),
    ADDRESS: schRS.getColumnValue('ADDRESS'),
    CITY: schRS.getColumnValue('CITY'),
    COUNTY: schRS.getColumnValue('COUNTY'),
    STATE: schRS.getColumnValue('STATE'),
    ZIP: schRS.getColumnValue('ZIP'),
    ZIP4: schRS.getColumnValue('ZIP4'),
    COUNTRY: schRS.getColumnValue('COUNTRY'),
    TELEPHONE: schRS.getColumnValue('TELEPHONE')
  });
}

var sources = [];
for (var i = 0; i < ciRows.length; i++) {
  sources.push(buildBaseRowFromCI(ciRows[i]));
}
for (var j = 0; j < schRows.length; j++) {
  sources.push(buildBaseRowFromSchools(schRows[j]));
}

// Generate variants
var generated = [];
for (var k = 0; k < sources.length; k++) {
  generated.push(generateVariantFromBase(sources[k]));
}

// Insert each generated record (compute CUSTOMER_FULL_DETAIL and EMBEDDING in SQL)
var insertSql = `
  INSERT INTO MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER (
    IDENTIFIER_TYPE,
    IDENTIFIER_VALUE,
    CUSTOMER_BUSINESS_ID,
    CUSTOMER_NAME,
    ADDRESS_ROLE,
    ADDRESS_LINE_1,
    ADDRESS_LINE_2,
    CITY,
    COUNTY,
    STATE,
    POSTAL_CODE,
    POSTALCODE_EXTENSION,
    COUNTRY,
    PHONE,
    VERIFICATION_STATUS_CODE,
    VERIFICATION_MESSAGE,
    ENRICHED_INDICATOR,
    CONFIDENCE_SCORE,
    CUSTOMER_FULL_DETAIL,
    CUSTOMER_FULL_DETAIL_EMBEDDING,
    CREATED_TIMESTAMP,
    UPDATED_TIMESTAMP
  )
  SELECT
    base.IDENTIFIER_TYPE,
    base.IDENTIFIER_VALUE,
    base.CUSTOMER_BUSINESS_ID,
    base.CUSTOMER_NAME,
    base.ADDRESS_ROLE,
    base.ADDRESS_LINE_1,
    base.ADDRESS_LINE_2,
    base.CITY,
    base.COUNTY,
    base.STATE,
    base.POSTAL_CODE,
    base.POSTALCODE_EXTENSION,
    base.COUNTRY,
    base.PHONE,
    base.VERIFICATION_STATUS_CODE,
    base.VERIFICATION_MESSAGE,
    base.ENRICHED_INDICATOR,
    base.CONFIDENCE_SCORE,
    RTRIM(
  ARRAY_TO_STRING(
    ARRAY_CONSTRUCT_COMPACT(
      IFF(TRIM(base.CUSTOMER_NAME) = '', NULL, TRIM(base.CUSTOMER_NAME)),
      IFF(TRIM(base.ADDRESS_LINE_1) = '', NULL, TRIM(base.ADDRESS_LINE_1)),
      IFF(TRIM(base.ADDRESS_LINE_2) = '', NULL, TRIM(base.ADDRESS_LINE_2)),
      IFF(TRIM(base.CITY) = '', NULL, TRIM(base.CITY)),
      IFF(TRIM(base.STATE) = '', NULL, TRIM(base.STATE)),
      IFF(TRIM(base.POSTAL_CODE) = '', NULL, TRIM(base.POSTAL_CODE))
    ),
    ', '
  )
) AS CUSTOMER_FULL_DETAIL,
    AI_EMBED(
      'snowflake-arctic-embed-m-v1.5', customer_full_detail ) AS CUSTOMER_FULL_DETAIL_EMBEDDING,
    CURRENT_TIMESTAMP(),
    null
  FROM (
    SELECT
      ? AS IDENTIFIER_TYPE,
      ? AS IDENTIFIER_VALUE,
      ? AS CUSTOMER_BUSINESS_ID,
      ? AS CUSTOMER_NAME,
      ? AS ADDRESS_ROLE,
      ? AS ADDRESS_LINE_1,
      ? AS ADDRESS_LINE_2,
      ? AS CITY,
      ? AS COUNTY,
      ? AS STATE,
      ? AS POSTAL_CODE,
      ? AS POSTALCODE_EXTENSION,
      ? AS COUNTRY,
      ? AS PHONE,
      ? AS VERIFICATION_STATUS_CODE,
      CAST(? AS VARIANT) AS VERIFICATION_MESSAGE,
      ? AS ENRICHED_INDICATOR,
      CAST(? AS FLOAT) AS CONFIDENCE_SCORE
  ) base`;

var totalInserted = 0;
for (var g = 0; g < generated.length; g++) {
  var r = generated[g];
  var binds = [
    r.IDENTIFIER_TYPE,
    r.IDENTIFIER_VALUE,
    r.CUSTOMER_BUSINESS_ID,
    r.CUSTOMER_NAME,
    r.ADDRESS_ROLE,
    r.ADDRESS_LINE_1,
    r.ADDRESS_LINE_2,
    r.CITY,
    r.COUNTY,
    r.STATE,
    r.POSTAL_CODE,
    r.POSTALCODE_EXTENSION,
    r.COUNTRY,
    r.PHONE,
    r.VERIFICATION_STATUS_CODE,
    r.VERIFICATION_MESSAGE,
    r.ENRICHED_INDICATOR,
    r.CONFIDENCE_SCORE
  ];
  var stmt = snowflake.createStatement({ sqlText: insertSql, binds: binds });
  stmt.execute();
  totalInserted++;
}

return totalInserted;
$$;


