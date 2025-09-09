# Customer Matching Chatbot User Guide

## Overview
The Customer Matching Chatbot is an AI-powered assistant that helps you analyze and manage customer matching data using natural language queries. It integrates Snowflake Cortex Analyst capabilities with your customer matching system.

## Features

### 🤖 Natural Language Queries
Ask questions about your data in plain English:
- "Which test customers are exact matches?"
- "How many customers are in each match category?"
- "Which test customers match between 95-97%?"

### 📝 Inline Record Editing
Edit customer records directly from the chat:
- Ask "Let me edit a test_match record"
- Select a customer from the dropdown
- Update fields inline and save

### 🎯 Top Matches Display
View top matching customers:
- Ask "Show me top 5 matches for TEST_001"
- See similarity scores and match categories
- View detailed customer information

### 🔍 AI Analysis Integration
Get AI-powered analysis of record differences:
- Ask "Why are these records different?"
- Integrates with existing AI analysis features

## Getting Started

### 1. Access the Chatbot
1. Run the Streamlit application
2. Navigate to the "💬 Chat View" tab
3. Start asking questions!

### 2. Example Questions to Try

#### Data Analysis Questions:
```
- Which test customers are exact matches?
- Which test customers are very close matches?
- Which test customers match between 95-97%?
- How many test customers are in each match category?
- Show me a breakdown of match categories
```

#### Record Management:
```
- Let me edit a test_match record
- I want to update customer information
- Show me top 5 matches for [CUSTOMER_ID]
```

#### Analysis Questions:
```
- Why are these records different?
- Analyze the differences between customers
```

### 3. Using the Interface

#### Chat Input
- Type your question in the text input field
- Click "Send" or press Enter
- Wait for the AI response

#### Example Questions Buttons
- Click any of the pre-built example questions
- These demonstrate the chatbot's capabilities
- Great for getting started

#### Chat Controls
- **Clear Chat History**: Removes all conversation history
- **Export Chat**: Download your conversation as JSON

## Advanced Features

### Inline Forms
When you ask to edit records:
1. A form appears in the chat
2. Select the customer to edit
3. Modify the fields as needed
4. Click "Update Customer" to save

### Top Matches Display
When asking about specific customers:
1. Provide the customer ID (e.g., TEST_001)
2. View color-coded similarity scores:
   - 🟢 Exact matches (≥99.5%)
   - 🟡 Very close (≥98%)
   - 🟠 Somewhat close (≥92%)
   - 🔴 Not close (<92%)

### SQL Query Execution
The chatbot can:
- Generate SQL queries based on your questions
- Execute them against your Snowflake database
- Display results in a user-friendly format
- Show the SQL used for transparency

## Technical Details

### Supported Question Types
1. **Data Retrieval**: Questions that fetch customer data
2. **Statistical Analysis**: Questions about counts, percentages, categories
3. **Record Management**: Editing and updating customer information
4. **Comparative Analysis**: Analyzing differences between records

### Data Sources
The chatbot queries three main tables:
- `TEST_MATCHES`: Incoming customer data
- `VALID_CUSTOMERS`: Reference customer data
- `CUSTOMER_MATCH_RESULTS`: Precomputed similarity results

### Security & Privacy
- Uses existing Snowflake authentication
- Respects database access controls
- Chat history stored in session (not persistent)
- No data leaves Snowflake governance boundary

## Troubleshooting

### Common Issues

#### "No response from chatbot"
- Check your Snowflake connection
- Verify database permissions
- Try a simpler question first

#### "Error executing query"
- Database might be busy
- Check table names and permissions
- Try refreshing the page

#### "No matches found"
- Verify the customer ID exists
- Check spelling of customer identifiers
- Use the Data View tab to browse available customers

### Getting Help

#### Predefined Responses
The demo version includes predefined responses for common questions. In production, this would connect to full Cortex Analyst capabilities.

#### Error Messages
Error messages appear as toast notifications. Common issues:
- Database connection problems
- Permission errors
- Invalid customer IDs

## Best Practices

### Asking Effective Questions
1. **Be Specific**: "Show matches for TEST_001" vs "show matches"
2. **Use Keywords**: Include terms like "exact match", "similarity", "customer"
3. **Reference IDs**: Provide specific customer identifiers when possible

### Managing Data
1. **Review Before Editing**: Check current values before making changes
2. **Use Descriptive Updates**: Make meaningful changes to customer data
3. **Clear Cache**: The system automatically refreshes after updates

### Performance Tips
1. **Start Simple**: Begin with basic questions to test connectivity
2. **Use Filters**: Specific questions perform better than broad queries
3. **Batch Operations**: For multiple edits, use the Data View tab

## Integration with Existing Features

### Data View Tab
- Continue using the original interface for detailed analysis
- Form submissions automatically refresh data
- Threshold adjustments affect chatbot results

### AI Analysis
- Existing AI analysis features work in chat
- Record comparisons integrate seamlessly
- Top matches use current similarity thresholds

## Future Enhancements

The chatbot is designed for extensibility:
- Full Cortex Analyst REST API integration
- Advanced conversation memory
- Custom update operations
- Enhanced AI analysis integration
- Multi-turn conversation support

---

**Need Help?** Try asking the chatbot: "What questions can I ask?" or use the example question buttons to get started!