# Streamlit PRD

Goal:
Create a streamlit application to validate and update potential "incoming" matches from the MDM_CUSTOMER_MATCHING.public.test_matches (test_matches.csv) to the MDM_CUSTOMER_MATCHING.public.valid_customers(valid.csv).  

# UI:
## Threshold Configuration
- Configurable similarity thresholds with real-time recomputation:
    - Exact match threshold (default: ≥0.995)
    - Very close match threshold (default: ≥0.980)
    - Somewhat close match threshold (default: ≥0.920)
- Recompute button to update results when thresholds change

## Dashboard overview with:
- # of matches per bucket (based on current thresholds):
    - Exact match count and percentage
    - Very close match count and percentage
    - Somewhat close match count and percentage
    - Not very close count and percentage
- Total number of valid customers
- Total number of test customers

## Table view 1
- Valid customers (scrollable)

## Table view 2
- Test customers (scrollable)

## Form
- Inputs 
    ID (readonly - populated for existing records, generated with UUID_STRING() for new),
    NAME,
    SOURCE_SYSTEM,
    ADDRESS_LINE_1,
    ADDRESS_LINE_2,
    CITY,
    STATE,
    POSTAL_CODE,
    COUNTRY
- Submit button (updates existing record if ID exists, creates new if no ID)
- New button (clears form for new record creation)
- Error handling with toast notifications

## Current Record
- Show the current id, customer_full_detail, and cosine similarity %

## Matched Records
- Top 5 matching records sorted by similarity desc



# Interaction:
- When a row is clicked in the test customers, load it into the form and update the current record and matched records
- When the submit button is clicked:
  - If record has ID: Update existing test_matches record
  - If no ID: Create new test_matches record with UUID_STRING() 
  - Recalculate similarity and update precomputed results table
  - Refresh current & matched records display
- When new button is clicked: Clear form for new record creation
- When thresholds are changed: Recompute match categories and refresh dashboard
- All operations only affect test_matches table (no records move to valid_customers)

# Technical requirements
- **Precomputed Results Table Schema**:
  ```sql
  CREATE TABLE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_MATCH_RESULTS (
      VALID_ID VARCHAR(50),                    -- ID from valid_customers 
      VALID_CUSTOMER_FULL_DETAIL VARCHAR(1000), -- Concatenated customer details
      TEST_ID VARCHAR(50),                     -- SOURCE_PKEY from test_matches
      TEST_CUSTOMER_FULL_DETAIL VARCHAR(1000), -- Concatenated customer details  
      SIMILARITY_SCORE FLOAT,                  -- Vector cosine similarity (0-1)
      MATCH_CATEGORY VARCHAR(20),              -- 'EXACT', 'VERY_CLOSE', 'SOMEWHAT_CLOSE', 'NOT_CLOSE'
      CREATED_TIMESTAMP TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
      UPDATED_TIMESTAMP TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
  );
  ```
- **Connection**: Use snow CLI credentials for Snowflake connection
- **Authentication**: No auth required for Streamlit app
- **Compatibility**: Build as standalone Streamlit app compatible with Streamlit in Snowflake (SiS)
- **Error Handling**: Toast notifications for all database operations
- When the current record form is submitted, recalculate similarity and update precomputed results table 

# All Tasks

## ✅ COMPLETED - Streamlit Customer Matching Application

### Phase 1: Foundation & Planning ✅
- [x] Updated PRD with configurable thresholds and technical requirements
- [x] Analyzed existing Snowflake table schemas  
- [x] Designed precomputed results table schema
- [x] Set up Snowflake connection using snow CLI credentials/env variables

### Phase 2: Core Application Development ✅
- [x] Created dashboard with configurable thresholds and real-time recomputation
- [x] Implemented scrollable table views for valid and test customers
- [x] Built customer form with CRUD operations (update existing, create new with UUID)
- [x] Implemented current record and top 5 matched records display
- [x] Added comprehensive error handling with toast messages

### Phase 3: Deliverables ✅
- [x] Complete Streamlit application (`app.py`)
- [x] Requirements file (`requirements.txt`)
- [x] Documentation (`README_streamlit.md`)
- [x] Streamlit in Snowflake (SiS) compatibility ensured

# Success Critera
A local Streamlit application that can be run and let the user investigate different record types and their results.