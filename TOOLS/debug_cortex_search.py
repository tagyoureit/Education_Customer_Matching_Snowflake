import os
import sys
import json
import toml
import snowflake.connector


def get_conn():
    connections_path = os.path.expanduser("~/.snowflake/connections.toml")
    if os.path.exists(connections_path):
        with open(connections_path, 'r') as f:
            config = toml.load(f)
            default_conn = config.get('default', {})
            params = {
                'account': default_conn.get('account'),
                'user': default_conn.get('user'),
                'password': default_conn.get('password'),
                'database': 'MDM_CUSTOMER_MATCHING',
                'schema': 'PUBLIC',
                'warehouse': 'COMPUTE_WH',
            }
    else:
        params = {
            'account': os.getenv('SNOWFLAKE_ACCOUNT'),
            'user': os.getenv('SNOWFLAKE_USER'),
            'password': os.getenv('SNOWFLAKE_PASSWORD'),
            'database': 'MDM_CUSTOMER_MATCHING',
            'schema': 'PUBLIC',
            'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH'),
        }
    params = {k: v for k, v in params.items() if v is not None}
    return snowflake.connector.connect(**params)


def main():
    if len(sys.argv) < 3:
        print("Usage: python debug_cortex_search.py <SERVICE_NAME> <QUERY>")
        sys.exit(1)
    service = sys.argv[1]
    query = " ".join(sys.argv[2:])

    payload = {
        "query": query,
        "columns": [
            "customer_business_id",
            "customer_name",
            "address_line_1",
            "address_line_2",
            "city",
            "county",
            "state",
            "postal_code",
            "postalcode_extension",
            "country",
            "customer_full_detail",
        ],
        "limit": 3,
    }
    payload_str = json.dumps(payload).replace("'", "''")

    conn = get_conn()
    cur = conn.cursor()
    try:
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE WAREHOUSE COMPUTE_WH")
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")

        sql = (
            "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(\n"
            f"  '{service}',\n"
            f"  '{payload_str}'\n"
            ")) AS RESULT"
        )
        cur.execute(sql)
        row = cur.fetchone()
        print("SERVICE:", service)
        print("QUERY:", query)
        if not row:
            print("No row returned")
            return
        result = row[0]
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                result = parsed
            except Exception:
                pass
        print("RAW_RESULT:", type(result).__name__)
        print(json.dumps(result, indent=2, default=str))
    finally:
        try:
            cur.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()


