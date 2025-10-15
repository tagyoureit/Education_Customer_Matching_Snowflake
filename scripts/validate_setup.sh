#!/usr/bin/env bash
set -euo pipefail

# Validation script for MDM Customer Matching prerequisites
# Run this before setup.sh to verify environment is ready

WH=${MDM_WH:-COMPUTE_WH}
ERRORS=0

echo "==> Validating MDM Customer Matching prerequisites..."
echo ""

# Check if snow CLI is installed
echo "Checking Snow CLI installation..."
if ! command -v snow &> /dev/null; then
    echo "❌ ERROR: Snow CLI not found. Please install it first."
    echo "   Visit: https://docs.snowflake.com/en/developer-guide/snowflake-cli-v2/installation/installation"
    ERRORS=$((ERRORS + 1))
else
    echo "✅ Snow CLI found: $(snow --version)"
fi
echo ""

# Check if snow CLI is authenticated
echo "Checking Snow CLI authentication..."
if ! snow connection test &> /dev/null; then
    echo "❌ ERROR: Snow CLI not authenticated or connection failed."
    echo "   Run: snow connection add"
    ERRORS=$((ERRORS + 1))
else
    echo "✅ Snow CLI authenticated"
fi
echo ""

# Check if warehouse exists
echo "Checking warehouse: ${WH}..."
WH_CHECK=$(snow sql -q "SHOW WAREHOUSES LIKE '${WH}'" 2>&1 || echo "ERROR")
if echo "$WH_CHECK" | grep -qi "error\|does not exist"; then
    echo "❌ ERROR: Warehouse '${WH}' not found or not accessible."
    echo "   Available warehouses:"
    snow sql -q "SHOW WAREHOUSES" 2>&1 | grep -i "name" || echo "   (Unable to list warehouses)"
    echo ""
    echo "   To use a different warehouse, set: export MDM_WH=YOUR_WAREHOUSE_NAME"
    ERRORS=$((ERRORS + 1))
else
    echo "✅ Warehouse '${WH}' exists and is accessible"
fi
echo ""

# Check if user has ACCOUNTADMIN or sufficient privileges
echo "Checking role privileges..."
CURRENT_ROLE=$(snow sql -q "SELECT CURRENT_ROLE()" 2>&1 | tail -1 | tr -d '[:space:]')
if [[ "$CURRENT_ROLE" == "ACCOUNTADMIN" ]]; then
    echo "✅ Current role: ACCOUNTADMIN (sufficient for setup)"
else
    echo "⚠️  WARNING: Current role is '${CURRENT_ROLE}', not ACCOUNTADMIN"
    echo "   Setup requires ACCOUNTADMIN to create database and grant privileges."
    echo "   You may need to switch roles or request assistance from an admin."
fi
echo ""

# Check Python installation
echo "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: Python 3 not found. Please install Python 3.8 or higher."
    ERRORS=$((ERRORS + 1))
else
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    echo "✅ Python found: $PYTHON_VERSION"
fi
echo ""

# Summary
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ All validation checks passed!"
    echo "=========================================="
    echo ""
    echo "You can proceed with setup:"
    echo "  bash scripts/setup.sh"
    exit 0
else
    echo "❌ Found $ERRORS error(s)"
    echo "=========================================="
    echo ""
    echo "Please fix the errors above before running setup."
    exit 1
fi
