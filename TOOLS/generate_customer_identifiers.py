import os
import re
import sys
import argparse
import random
import string
from typing import Dict, List, Any, Tuple

import snowflake.connector
import toml


IDENTIFIER_TYPES: Tuple[str, ...] = (
    "NWEA SFDC ID",
    "NCES ID",
    "SAP Customer Number",
    "HMH ID",
    "HMH Ref ID",
    "HMH SFDC ID",
    "AgileEd ID",
)

ADDRESS_ROLES: Tuple[str, ...] = (
    "OFFICE",
    "WAREHOUSE",
    "SCHOOL",
)


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    """Create Snowflake connection using snow CLI config or environment variables.

    Mirrors the approach in app.py to reduce configuration friction.
    """
    # Try to read from snow CLI connections.toml first
    connections_path = os.path.expanduser("~/.snowflake/connections.toml")
    if os.path.exists(connections_path):
        with open(connections_path, 'r') as f:
            config = toml.load(f)
            default_conn = config.get('default', {})

            connection_params = {
                'account': default_conn.get('account'),
                'user': default_conn.get('user'),
                'password': default_conn.get('password'),
                'database': 'MDM_CUSTOMER_MATCHING',
                'schema': 'PUBLIC',
                'warehouse': default_conn.get('warehouse', 'COMPUTE_WH')
            }
    else:
        # Fallback to environment variables
        connection_params = {
            'account': os.getenv('SNOWFLAKE_ACCOUNT'),
            'user': os.getenv('SNOWFLAKE_USER'),
            'password': os.getenv('SNOWFLAKE_PASSWORD'),
            'database': 'MDM_CUSTOMER_MATCHING',
            'schema': 'PUBLIC',
            'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH')
        }

    # Remove None values
    connection_params = {k: v for k, v in connection_params.items() if v is not None}
    return snowflake.connector.connect(**connection_params)


def run_use_statements(cursor) -> None:
    # Always set context explicitly per user rules
    cursor.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
    cursor.execute("USE SCHEMA PUBLIC")


def fetch_all_customer_addresses(cursor) -> List[Dict[str, Any]]:
    """Load all rows from CUSTOMER_ADDRESS with explicit column list."""
    query = (
        "SELECT CUSTOMER_BUSINESS_ID, CUSTOMER_NAME, ADDRESS_LINE_1, ADDRESS_LINE_2, "
        "CITY, COUNTY, STATE, POSTAL_CODE, POSTALCODE_EXTENSION, COUNTRY, PHONE "
        "FROM CUSTOMER_ADDRESS"
    )
    cursor.execute(query)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def random_identifier_value(length: int = 12) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=length))


_street_num_regex = re.compile(r"^(\d+)(.*)$")


def tweak_street_number(address_line_1: str) -> str:
    if not address_line_1:
        return address_line_1
    match = _street_num_regex.match(address_line_1.strip())
    if not match:
        return address_line_1
    num_str, rest = match.groups()
    try:
        num = int(num_str)
    except ValueError:
        return address_line_1
    delta = random.choice([-2, -1, 1, 2])
    new_num = max(1, num + delta)
    return f"{new_num}{rest}"


def tweak_postal_code(postal_code: str) -> str:
    if not postal_code:
        return postal_code
    # Change one character at the end
    last = postal_code[-1]
    choices = string.digits + string.ascii_uppercase
    replacement = random.choice([c for c in choices if c != last])
    return postal_code[:-1] + replacement


def introduce_typo(value: str) -> str:
    if not value or len(value) < 3:
        return value
    ops = ["delete", "swap", "substitute", "insert"]
    op = random.choice(ops)
    i = random.randint(0, len(value) - 2)
    if op == "delete":
        return value[:i] + value[i+1:]
    if op == "swap":
        return value[:i] + value[i+1] + value[i] + value[i+2:]
    if op == "substitute":
        alphabet = string.ascii_letters
        ch = random.choice(alphabet)
        return value[:i] + ch + value[i+1:]
    # insert
    alphabet = string.ascii_letters
    ch = random.choice(alphabet)
    return value[:i] + ch + value[i:]


def make_slight_variations(row: Dict[str, Any]) -> Dict[str, Any]:
    new_row = dict(row)
    # 50% chance to tweak street number, 50% chance to tweak postal code, may do both
    if random.random() < 0.7:
        new_row['ADDRESS_LINE_1'] = tweak_street_number(new_row.get('ADDRESS_LINE_1'))
    if random.random() < 0.6:
        new_row['POSTAL_CODE'] = tweak_postal_code(new_row.get('POSTAL_CODE'))
    return new_row


def make_typo_variant(row: Dict[str, Any]) -> Dict[str, Any]:
    new_row = dict(row)
    # Choose one field to typo among name/addr/city
    fields = [
        'CUSTOMER_NAME',
        'ADDRESS_LINE_1',
        'CITY',
    ]
    field = random.choice(fields)
    new_row[field] = introduce_typo(new_row.get(field))
    return new_row


def generate_records_for_customer(
    source_row: Dict[str, Any],
    min_per_customer: int,
    max_per_customer: int,
    ratios: Tuple[float, float, float]
) -> List[Dict[str, Any]]:
    exact_p, slight_p, typo_p = ratios
    n = random.randint(min_per_customer, max_per_customer)
    categories = random.choices(
        population=["exact", "slight", "typo"],
        weights=[exact_p, slight_p, typo_p],
        k=n,
    )

    outputs: List[Dict[str, Any]] = []
    for cat in categories:
        base = dict(source_row)
        if cat == "slight":
            base = make_slight_variations(base)
        elif cat == "typo":
            base = make_typo_variant(base)

        # Enrich with identifier-specific fields
        base['IDENTIFIER_TYPE'] = random.choice(IDENTIFIER_TYPES)
        base['IDENTIFIER_VALUE'] = random_identifier_value()
        base['ADDRESS_ROLE'] = random.choice(ADDRESS_ROLES)

        # Non-overlapping optional fields left as None (NULL)
        base['VERIFICATION_STATUS_CODE'] = None
        base['VERIFICATION_MESSAGE'] = None
        base['ENRICHED_INDICATOR'] = None
        base['CONFIDENCE_SCORE'] = None
        base['CUSTOMER_FULL_DETAIL'] = None
        base['CUSTOMER_FULL_DETAIL_EMBEDDING'] = None

        outputs.append(base)
    return outputs


def insert_identifier_rows(cursor, rows: List[Dict[str, Any]], batch_size: int) -> int:
    if not rows:
        return 0

    columns = [
        'IDENTIFIER_TYPE',
        'IDENTIFIER_VALUE',
        'CUSTOMER_BUSINESS_ID',
        'CUSTOMER_NAME',
        'ADDRESS_ROLE',
        'ADDRESS_LINE_1',
        'ADDRESS_LINE_2',
        'CITY',
        'COUNTY',
        'STATE',
        'POSTAL_CODE',
        'POSTALCODE_EXTENSION',
        'COUNTRY',
        'PHONE',
        'VERIFICATION_STATUS_CODE',
        'VERIFICATION_MESSAGE',
        'ENRICHED_INDICATOR',
        'CONFIDENCE_SCORE',
        'CUSTOMER_FULL_DETAIL',
    ]

    placeholders = ", ".join(["%s"] * len(columns))
    cols_sql = ", ".join(columns + ['CREATED_TIMESTAMP', 'UPDATED_TIMESTAMP'])
    insert_sql = (
        "INSERT INTO MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER (" + cols_sql + ") "
        "VALUES (" + placeholders + ", CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())"
    )

    total_inserted = 0
    batch: List[List[Any]] = []

    for row in rows:
        values = [row.get(col) for col in columns]
        batch.append(values)
        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            total_inserted += len(batch)
            batch = []

    if batch:
        cursor.executemany(insert_sql, batch)
        total_inserted += len(batch)

    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Generate CUSTOMER_IDENTIFIER rows from CUSTOMER_ADDRESS with controlled noise.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--min-per-customer", type=int, default=3, help="Minimum generated rows per customer")
    parser.add_argument("--max-per-customer", type=int, default=7, help="Maximum generated rows per customer")
    parser.add_argument("--exact-ratio", type=float, default=0.6, help="Approximate ratio of exact copies")
    parser.add_argument("--slight-ratio", type=float, default=0.3, help="Approximate ratio of slight variations")
    parser.add_argument("--typo-ratio", type=float, default=0.1, help="Approximate ratio with spelling errors")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for inserts")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert; print summary only")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit of customers to process")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    # Basic ratios sanity
    total_ratio = args.exact_ratio + args.slight_ratio + args.typo_ratio
    if total_ratio <= 0:
        print("Ratios must sum to > 0", file=sys.stderr)
        sys.exit(1)

    ratios = (
        args.exact_ratio / total_ratio,
        args.slight_ratio / total_ratio,
        args.typo_ratio / total_ratio,
    )

    conn = get_snowflake_connection()
    cur = conn.cursor()
    try:
        run_use_statements(cur)

        print("Loading CUSTOMER_ADDRESS ...")
        source_rows = fetch_all_customer_addresses(cur)
        if args.limit:
            source_rows = source_rows[: args.limit]
        print(f"Loaded {len(source_rows)} source customers")

        all_generated: List[Dict[str, Any]] = []
        for idx, src in enumerate(source_rows, start=1):
            generated = generate_records_for_customer(
                source_row=src,
                min_per_customer=args.min_per_customer,
                max_per_customer=args.max_per_customer,
                ratios=ratios,
            )
            all_generated.extend(generated)
            if idx % 1000 == 0:
                print(f"Prepared {idx} customers ... total generated so far: {len(all_generated)}")

        print(f"Prepared total {len(all_generated)} CUSTOMER_IDENTIFIER rows")

        if args.dry_run:
            # Show a small sample
            for sample in all_generated[:5]:
                print({k: sample.get(k) for k in (
                    'IDENTIFIER_TYPE','IDENTIFIER_VALUE','CUSTOMER_BUSINESS_ID','CUSTOMER_NAME','ADDRESS_ROLE','ADDRESS_LINE_1','CITY','STATE','POSTAL_CODE'
                )})
            print("Dry run complete. No rows inserted.")
            return

        print("Inserting rows into CUSTOMER_IDENTIFIER ...")
        inserted = insert_identifier_rows(cur, all_generated, args.batch_size)
        conn.commit()
        print(f"Inserted {inserted} rows into CUSTOMER_IDENTIFIER")

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()


