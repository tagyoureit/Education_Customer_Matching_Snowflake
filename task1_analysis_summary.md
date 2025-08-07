# Task 1: Data Analysis Summary

## Valid.csv Analysis
- **Total Records**: 500 data rows + 1 header = 501 lines
- **SOURCE_SYSTEM**: All records use "MDM"
- **Data Quality**: High quality, consistent formatting

## Educational Institution Patterns
### Institution Types:
- Elementary School
- High School  
- Learning Center / Early Learning Center / Early Childhood Center
- Academy (Christian, Adventist)
- Community College
- School District (abbreviated as "Dist")

### Name Characteristics:
- Often include location (city/area name)
- Religious affiliations (Lutheran, Christian, Adventist) 
- Grade levels (Elementary, High)
- Descriptive terms (Eagle's Landing, Prairie Home R5)

## Address Patterns
### Street Address Format:
- Street number + street name + street type
- Common abbreviations: ST, RD, DR, AVE, BLVD
- Directional indicators: N, S, E, W, NE, etc.
- Examples: "400 N 5TH ST", "2400 HIGHWAY 42 N"

### PO Box Format:
- "PO BOX [number]"
- Example: "PO BOX 29493"

### Address Line 2:
- Usually empty ("") 
- Sometimes contains apartment/suite info

## Geographic Distribution:
- US States: NE, WA, GA, IL, KS, NY, WI, PR, CA, etc.
- State format: "US-[STATE]"
- International: Some Canadian entries ("CA-[PROVINCE]")

## SOURCE_SYSTEM Values for Test Data:
### From invalid.csv:
1. sap_hmh (172 records)
2. sfdc_hmh (300 records) 
3. sfdc_nwea (28 records)
4. 112 (1 record)

### New SOURCE_SYSTEM values to create:
1. **sis_pearson** - Student Information System from Pearson
2. **erp_oracle** - Oracle ERP system for educational institutions  
3. **crm_edtech** - Educational Technology CRM system

## Data Generation Strategy:
- Use existing valid.csv as base data
- Apply variations based on match similarity levels
- Distribute across 7 SOURCE_SYSTEM values (4 existing + 3 new)
- Maintain educational institution context