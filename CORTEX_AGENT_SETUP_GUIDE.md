# 🤖 Cortex Agent Setup Guide

This guide will help you create and configure the Customer Matching Cortex Agent based on the [Snowflake Intelligence Preview Guide](https://github.com/sfc-gh-jhollan/snowflake-intelligence-preview-guide/blob/main/3_feature_overview.md).

## 📋 Prerequisites

1. **Snowflake Account** with Cortex Agent preview enabled
2. **Semantic Model** already uploaded to `@SEMANTIC_MODELS/customer_matching_semantic_model.yaml`
3. **Appropriate Permissions** (ACCOUNTADMIN or SYSADMIN role)

## 🚀 Step 1: Create the Cortex Agent

Run the SQL script in Snowflake:

```bash
# In your terminal or use Snow CLI
snow sql -f create_customer_matching_agent.sql
```

Or copy and paste the contents of `create_customer_matching_agent.sql` into a Snowflake worksheet and execute.

## 🔧 Step 2: Verify Agent Creation

After running the script, verify the agent was created:

```sql
-- Check if agent exists
SHOW CORTEX AGENTS;

-- Describe the agent
DESCRIBE CORTEX AGENT customer_matching_agent;

-- Test the agent manually
SELECT SNOWFLAKE.CORTEX.COMPLETE_AGENT(
  'customer_matching_agent',
  'Which test customers are exact matches?'
) AS agent_response;
```

## 🎯 Step 3: Test in Streamlit

1. **Access the app** at http://localhost:8501
2. **Go to Chat View** 
3. **Ask a question** like "Which test customers are exact matches?"

### Expected Behavior:

- ✅ **Success**: Agent responds with intelligent analysis
- ⚠️ **Fallback**: If agent not found, falls back to Enhanced Cortex Analyst
- ℹ️ **Info Messages**: Clear guidance on any issues

## 🔧 Troubleshooting

### Agent Not Found
```
ℹ️ Cortex Agent not found. Please run the agent creation script first.
```
**Solution**: Run `create_customer_matching_agent.sql`

### Permission Issues
```
ℹ️ Insufficient permissions for Cortex Agent.
```
**Solution**: Ensure you have USAGE privileges on the agent

### Semantic Model Issues
```
Error: Semantic model file not found
```
**Solution**: Verify the semantic model is uploaded to the correct stage

## 🎉 Success Indicators

When working properly, you'll see:
- Direct agent responses (no fallback messages)
- Intelligent SQL generation and execution
- Detailed explanations alongside query results
- Advanced orchestration between data queries and analysis

## 📁 Files Created

- `create_customer_matching_agent.sql` - Agent creation script
- `CORTEX_AGENT_SETUP_GUIDE.md` - This guide
- Updated `pages/2_💬_Chat_View.py` - Modified to call the actual agent

## 🔄 Agent Architecture

The created agent includes:
- **Model**: `claude-3-5-sonnet`
- **Tools**: 
  - `cortex_analyst_text_to_sql` (for structured data queries)
  - `sql_exec` (for executing generated SQL)
- **Resources**: Your customer matching semantic model
- **System Message**: Specialized for customer matching assistance

## 🎯 Next Steps

Once the agent is working:
1. Test various customer matching scenarios
2. Explore complex analytical questions
3. Use the agent for both data retrieval and insights
4. Leverage the intelligent orchestration capabilities

## 📞 Support

If you encounter issues:
1. Check the [Snowflake Intelligence Preview Guide](https://github.com/sfc-gh-jhollan/snowflake-intelligence-preview-guide)
2. Verify your account has Cortex Agent preview access
3. Ensure all prerequisites are met