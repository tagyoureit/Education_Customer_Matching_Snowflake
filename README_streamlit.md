# Customer Matching Streamlit Application

A Streamlit application for validating and updating customer matching results using Snowflake vector similarity.

## Features

- 📊 **Dashboard Overview**: Real-time metrics with configurable similarity thresholds
- 📋 **Data Tables**: Browse valid customers and test matches
- ✏️ **Form Interface**: Edit existing records or create new ones
- 🎯 **Match Analysis**: View top 5 matches with similarity scores
- 🔄 **Real-time Updates**: Automatic similarity recalculation after changes

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Snowflake Connection**:
   The app will try to connect using:
   - Snow CLI configuration (`~/.snowflake/connections.toml`)
   - Or environment variables:
     ```bash
     export SNOWFLAKE_ACCOUNT=your_account
     export SNOWFLAKE_USER=your_user
     export SNOWFLAKE_PASSWORD=your_password
     export SNOWFLAKE_WAREHOUSE=your_warehouse
     ```

3. **Run the Application**:
   ```bash
   streamlit run app.py
   ```

## Usage

### Configurable Thresholds
- Use the sidebar to adjust similarity thresholds
- Click "Recompute Results" to update match categories
- Default thresholds based on analysis:
  - Exact: ≥0.995
  - Very Close: ≥0.980  
  - Somewhat Close: ≥0.920

### Customer Management
- Click rows in the "Test Customers" table to load into the form
- Edit fields and click "Submit" to update existing records
- Click "New" to clear the form for creating new records
- New records automatically get a UUID-based ID

### Match Analysis
- Select a test customer to see similarity score
- View top 5 matching valid customers with percentages
- Real-time updates after editing customer data

## Database Schema

The application uses these Snowflake tables:
- `VALID_CUSTOMERS`: Reference customer data
- `TEST_MATCHES`: Incoming customer data to validate
- `CUSTOMER_MATCH_RESULTS`: Precomputed similarity results

## Streamlit in Snowflake (SiS) Compatibility

The application is designed to be compatible with Streamlit in Snowflake:
- Uses standard Streamlit components
- Snowflake connector integration
- No external dependencies beyond Snowflake ecosystem