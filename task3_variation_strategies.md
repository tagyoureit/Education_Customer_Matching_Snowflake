# Task 3: Variation Strategy Design

## Match Categories and Row Distribution:
- **Exact Match (1.0 similarity)**: 50 rows (10%)
- **Very Close Match (>0.98 similarity)**: 100 rows (20%)  
- **Somewhat Close Match (>0.93 similarity)**: 100 rows (20%)
- **Not Very Close (<0.93 similarity)**: 250 rows (50%)

## Variation Strategies by Match Level:

### 1. Exact Match (50 rows)
**Strategy**: Perfect duplicates
- Copy records exactly as they appear in valid.csv
- Only change: SOURCE_PKEY (new unique value) and SOURCE_SYSTEM
- All other fields identical: NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, CITY, STATE, POSTAL_CODE, COUNTRY

### 2. Very Close Match (100 rows) - Similarity > 0.98
**Strategy**: Minor variations that preserve most semantic meaning
- **Case variations**: "Elementary School" → "elementary school" 
- **Minor abbreviations**: "Street" → "St", "Road" → "Rd", "Drive" → "Dr", "Avenue" → "Ave"
- **Whitespace differences**: "123  Main St" → "123 Main St" (double to single space)
- **Punctuation**: "Eagle's Landing" → "Eagles Landing" (remove apostrophe)
- **Common typos**: Single character substitutions in non-critical positions
- **Directional abbreviations**: "North" → "N", "Southeast" → "SE"

### 3. Somewhat Close Match (100 rows) - Similarity > 0.93
**Strategy**: Moderate variations that still clearly identify the same institution
- **Multiple abbreviations**: "Elementary School" → "Elem Sch"
- **Address variations**: "400 North 5th Street" → "400 N 5th St"
- **Institution type changes**: "Learning Center" → "Learning Centre" → "Educational Center"
- **Common misspellings**: "Academy" → "Acadamy", "Elementary" → "Elementry" 
- **ZIP code format**: "12345-6789" → "12345" (remove +4)
- **Building number variations**: "123 Main St" → "123A Main St"
- **Order changes**: "Franklin High School" → "High School Franklin"

### 4. Not Very Close Match (250 rows) - Similarity < 0.93
**Strategy**: Significant variations but still plausibly the same institution
- **Major abbreviations**: "Elementary School" → "Elem", "Community College" → "CC"
- **Alternative names**: "Franklin High School" → "Franklin Secondary School"
- **Address changes**: Different street numbers on same street
- **ZIP code variations**: Change last 1-2 digits (still valid postal codes)
- **Multiple typos**: 2-3 character errors per field
- **Formatting differences**: "PO Box 123" → "P.O. Box 123" → "Post Office Box 123"
- **Alternative street types**: "123 Main Street" → "123 Main Boulevard"
- **Institution descriptor changes**: "Early Learning Center" → "Child Development Center"

## SOURCE_SYSTEM Distribution Strategy:
Distribute the 500 records across 7 SOURCE_SYSTEM values:
- sap_hmh: ~72 records
- sfdc_hmh: ~72 records  
- sfdc_nwea: ~72 records
- 112: ~71 records
- sis_pearson: ~71 records
- erp_oracle: ~71 records
- crm_edtech: ~71 records

## Address Variation Examples:

### Original: "400 N 5TH ST"
- **Very Close**: "400 North 5th St", "400 N 5TH STREET"
- **Somewhat Close**: "400 N Fifth St", "400 North Fifth Street"  
- **Not Very Close**: "402 N 5th St", "400 N 5th Ave", "400 North 5 Street"

### Original: "PO BOX 29493"
- **Very Close**: "Po Box 29493", "P.O. BOX 29493"
- **Somewhat Close**: "Post Office Box 29493", "PO Box 29493-0001"
- **Not Very Close**: "PO Box 29495", "P.O. Box 2949", "Box 29493"

## Common Educational Typos to Include:
- Academy → Acadamy, Acadmey
- Elementary → Elementry, Elmentary  
- Secondary → Secondry, Secandary
- Community → Comunity, Commmunity
- Christian → Cristian, Chirstian
- Learning → Learing, Lerning
- District → Distict, Distrct

## Quality Assurance:
- Ensure each variation maintains logical consistency
- Verify postal codes remain valid for their geographic areas
- Keep institution names recognizable as educational facilities
- Maintain consistent country/state relationships