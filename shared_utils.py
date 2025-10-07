"""
Shared utility functions for the Customer Matching application.
This module contains functions that are used across multiple pages.
"""

import streamlit as st
import pandas as pd
import json
from typing import Dict, Optional, Tuple

# Default thresholds - matches the original working configuration
DEFAULT_THRESHOLDS = {
    'exact': 0.995,
    'very_close': 0.980,
    'somewhat_close': 0.920
}

def recalculate_all_similarities(_conn, thresholds: Dict[str, float] = None) -> bool:
    """Deprecated: legacy function removed (VALID_CUSTOMERS/TEST_MATCHES not used)."""
    return False


def recalculate_similarity_for_test_id(_conn, test_id: str, thresholds: Dict[str, float] = None) -> bool:
    """Deprecated: legacy function removed (VALID_CUSTOMERS/TEST_MATCHES not used)."""
    return False


# --- Customer Identifier auto-assign helpers ---
def fetch_first_unassigned_ci(_conn) -> Optional[dict]:
    try:
        if _conn is None:
            return None
        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        cur.execute(
            """
            SELECT 
                IDENTIFIER_TYPE,
                IDENTIFIER_VALUE,
                CUSTOMER_NAME,
                ADDRESS_LINE_1,
                ADDRESS_LINE_2,
                CITY,
                COUNTY,
                STATE,
                POSTAL_CODE,
                POSTALCODE_EXTENSION,
                COUNTRY,
                PHONE,
                CUSTOMER_FULL_DETAIL,
                CREATED_TIMESTAMP
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
            WHERE CUSTOMER_BUSINESS_ID IS NULL
            ORDER BY CREATED_TIMESTAMP DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        columns = [
            'IDENTIFIER_TYPE', 'IDENTIFIER_VALUE', 'CUSTOMER_NAME', 'ADDRESS_LINE_1',
            'ADDRESS_LINE_2', 'CITY', 'COUNTY', 'STATE', 'POSTAL_CODE',
            'POSTALCODE_EXTENSION', 'COUNTRY', 'PHONE', 'CUSTOMER_FULL_DETAIL',
            'CREATED_TIMESTAMP'
        ]
        return dict(zip(columns, row))
    except Exception:
        return None


def search_top_address_candidate(_conn, ci_row: dict) -> Optional[dict]:
    try:
        if _conn is None or not ci_row or not ci_row.get('CUSTOMER_FULL_DETAIL'):
            return None
        cur = _conn.cursor()
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        try:
            cur.execute("USE WAREHOUSE COMPUTE_WH")
        except Exception:
            pass

        payload = {
            "query": ci_row.get('CUSTOMER_FULL_DETAIL'),
            "columns": [
                "customer_full_detail",
                "customer_business_id",
                "customer_name",
                "address_line_1",
                "address_line_2",
                "city",
                "county",
                "state",
                "postal_code",
                "postalcode_extension",
                "country"
            ],
            "limit": 3
        }
        payload_str = json.dumps(payload)
        payload_sql_literal = payload_str.replace("'", "''")

        sql = (
            "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(\n"
            "  'MDM_CUSTOMER_ADDRESS_SEARCH',\n"
            f"  '{payload_sql_literal}'\n"
            ")) AS RESULT"
        )
        cur.execute(sql)
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        result = row[0]
        try:
            if isinstance(result, str):
                result = json.loads(result)
        except Exception:
            result = None

        items = []
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            for key in ['results', 'matches', 'data', 'documents', 'rows', 'items']:
                if isinstance(result.get(key), list):
                    items = result.get(key)
                    break
            if not items:
                inner = result.get('result') if isinstance(result, dict) else None
                if isinstance(inner, list):
                    items = inner

        if not items:
            return None

        def _normalize(item):
            doc = item
            if isinstance(item, dict) and isinstance(item.get('document'), dict):
                doc = item['document']
            score_val = None
            # Prefer Cortex SEARCH_PREVIEW @scores.cosine_similarity when present
            if isinstance(item, dict):
                scores_block = item.get('@scores') or item.get('scores')
                if isinstance(scores_block, dict):
                    # cosine_similarity is our primary ranking metric
                    if scores_block.get('cosine_similarity') is not None:
                        score_val = scores_block.get('cosine_similarity')
                # Fallbacks some providers use
                if score_val is None:
                    score_val = item.get('score') if 'score' in item else item.get('similarity')
            return {
                'CUSTOMER_BUSINESS_ID': (doc.get('customer_business_id') if isinstance(doc, dict) else '') or '',
                'CUSTOMER_NAME': (doc.get('customer_name') if isinstance(doc, dict) else '') or '',
                'ADDRESS_LINE_1': (doc.get('address_line_1') if isinstance(doc, dict) else '') or '',
                'ADDRESS_LINE_2': (doc.get('address_line_2') if isinstance(doc, dict) else '') or '',
                'CITY': (doc.get('city') if isinstance(doc, dict) else '') or '',
                'COUNTY': (doc.get('county') if isinstance(doc, dict) else '') or '',
                'STATE': (doc.get('state') if isinstance(doc, dict) else '') or '',
                'POSTAL_CODE': (doc.get('postal_code') if isinstance(doc, dict) else '') or '',
                'POSTALCODE_EXTENSION': (doc.get('postalcode_extension') if isinstance(doc, dict) else '') or '',
                'COUNTRY': (doc.get('country') if isinstance(doc, dict) else '') or '',
                '_SCORE': float(score_val) if score_val is not None else None,
            }

        

        candidates = [_normalize(it) for it in items]
        candidates.sort(key=lambda x: (x.get('_SCORE') is not None, x.get('_SCORE') or 0.0), reverse=True)
        return candidates[0] if candidates else None
    except Exception:
        return None


def process_unenriched_identifiers(_conn, threshold: float = 0.90, limit: int = 100, progress=None) -> Dict[str, any]:
    """Process up to `limit` CUSTOMER_IDENTIFIER rows where ENRICHED_INDICATOR IS NULL.

    For each row:
    - Run Cortex SEARCH_PREVIEW using CI.CUSTOMER_FULL_DETAIL
    - Parse top candidate score via @scores.cosine_similarity
    - Update CI.CONFIDENCE_SCORE to that score (if available)
    - Set ENRICHED_INDICATOR to 'VALID' if score > threshold else 'ERROR'

    Returns a dict with keys: processed_rows (list of identifier keys),
    results (list of dict rows mirroring requested display columns), count.
    Reference: @Snowflake Docs
    """
    processed_rows = []
    results = []
    any_valid = False
    try:
        if _conn is None:
            return { 'processed_rows': processed_rows, 'results': results, 'count': 0 }

        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        try:
            cur.execute("USE WAREHOUSE COMPUTE_WH")
        except Exception:
            pass

        if callable(progress):
            try:
                progress('fetch_start')
            except Exception:
                pass

        cur.execute(
            f"""
            SELECT 
                IDENTIFIER_TYPE,
                IDENTIFIER_VALUE,
                CUSTOMER_NAME,
                CUSTOMER_BUSINESS_ID,
                CUSTOMER_FULL_DETAIL,
                CREATED_TIMESTAMP
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
            WHERE ENRICHED_INDICATOR IS NULL
            ORDER BY CREATED_TIMESTAMP DESC
            LIMIT {int(limit)}
            """
        )
        rows = cur.fetchall()
        columns = ['IDENTIFIER_TYPE','IDENTIFIER_VALUE','CUSTOMER_NAME','CUSTOMER_BUSINESS_ID','CUSTOMER_FULL_DETAIL','CREATED_TIMESTAMP']
        cur.close()

        if callable(progress):
            try:
                progress('fetch_end', count=len(rows))
            except Exception:
                pass

        total = len(rows)
        idx = 0
        for row in rows:
            idx += 1
            if callable(progress):
                try:
                    progress('row_start', index=idx, total=total)
                except Exception:
                    pass
            ci = dict(zip(columns, row))
            top = search_top_address_candidate(_conn, {
                'CUSTOMER_FULL_DETAIL': ci.get('CUSTOMER_FULL_DETAIL')
            })
            score = (top.get('_SCORE') if isinstance(top, dict) else None) or 0.0

            # Update columns per rule; if VALID also assign to top candidate so verification can compare CI vs CA
            if score > threshold and isinstance(top, dict) and top.get('CUSTOMER_BUSINESS_ID'):
                # Use existing helper to assign, compute confidence, set indicator, and populate verification
                assign_ci_to_business_id(
                    _conn,
                    ci.get('IDENTIFIER_TYPE'),
                    ci.get('IDENTIFIER_VALUE'),
                    top.get('CUSTOMER_BUSINESS_ID')
                )
                # Ensure the in-memory row reflects the assigned BUSINESS_ID before display
                ci['CUSTOMER_BUSINESS_ID'] = top.get('CUSTOMER_BUSINESS_ID')
            else:
                cur2 = _conn.cursor()
                try:
                    cur2.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
                    cur2.execute("USE SCHEMA PUBLIC")
                    try:
                        cur2.execute("USE WAREHOUSE COMPUTE_WH")
                    except Exception:
                        pass
                    cur2.execute(
                        """
                        UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
                        SET ENRICHED_INDICATOR = 'ERROR'
                        WHERE IDENTIFIER_TYPE = %s AND IDENTIFIER_VALUE = %s
                        """,
                        (ci['IDENTIFIER_TYPE'], ci['IDENTIFIER_VALUE'])
                    )
                finally:
                    try:
                        cur2.close()
                    except Exception:
                        pass

            processed_rows.append((ci['IDENTIFIER_TYPE'], ci['IDENTIFIER_VALUE']))

            is_valid = (score > threshold)
            if is_valid:
                any_valid = True
            results.append({
                'ENRICHED_INDICATOR': 'VALID' if score > threshold else 'ERROR',
                'CUSTOMER_NAME': ci.get('CUSTOMER_NAME'),
                'CUSTOMER_BUSINESS_ID': ci.get('CUSTOMER_BUSINESS_ID'),
                'IDENTIFIER_TYPE': ci.get('IDENTIFIER_TYPE'),
                'CUSTOMER_FULL_DETAIL': ci.get('CUSTOMER_FULL_DETAIL'),
                'CONFIDENCE_SCORE': score,
                'CREATED_TIMESTAMP': ci.get('CREATED_TIMESTAMP'),
            })

            if callable(progress):
                try:
                    progress('row_end', index=idx, total=total)
                except Exception:
                    pass

        # If any VALID rows were set, run verification population per POPULATE_VERIFICATION_MESSAGE.sql
        if any_valid:
            try:
                if callable(progress):
                    try:
                        progress('verify_start')
                    except Exception:
                        pass
                run_populate_verification_message(_conn)
                if callable(progress):
                    try:
                        progress('verify_end')
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            'processed_rows': processed_rows,
            'results': results,
            'count': len(processed_rows),
            'verification_ran': any_valid,
        }
    except Exception:
        return { 'processed_rows': processed_rows, 'results': results, 'count': len(processed_rows), 'verification_ran': False }

def assign_ci_to_business_id(_conn, identifier_type: str, identifier_value: str, customer_business_id: str) -> bool:
    try:
        if _conn is None or not identifier_type or not identifier_value or not customer_business_id:
            return False
        cur = _conn.cursor()
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        try:
            cur.execute("USE WAREHOUSE COMPUTE_WH")
        except Exception:
            pass

        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
            SET CUSTOMER_BUSINESS_ID = %s
            WHERE IDENTIFIER_TYPE = %s AND IDENTIFIER_VALUE = %s
            """,
            (customer_business_id, identifier_type, identifier_value)
        )

        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
            SET CONFIDENCE_SCORE = VECTOR_COSINE_SIMILARITY(ca.CUSTOMER_FULL_DETAIL_EMBEDDING, ci.CUSTOMER_FULL_DETAIL_EMBEDDING)
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
              AND ci.IDENTIFIER_TYPE = %s AND ci.IDENTIFIER_VALUE = %s
            """,
            (identifier_type, identifier_value)
        )

        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER
            SET ENRICHED_INDICATOR = (CASE WHEN CONFIDENCE_SCORE > 90 THEN 'VALID' ELSE 'ERROR' END)
            WHERE IDENTIFIER_TYPE = %s AND IDENTIFIER_VALUE = %s AND CONFIDENCE_SCORE IS NOT NULL
            """,
            (identifier_type, identifier_value)
        )

        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
            SET VERIFICATION_MESSAGE =
              CASE
                WHEN ci.CONFIDENCE_SCORE = 1 THEN
                  OBJECT_CONSTRUCT(
                    'reason','Identical match',
                    'name',TRUE,'address_line_1',TRUE,'address_line_2',TRUE,
                    'city',TRUE,'county',TRUE,'state',TRUE,'postal_code',TRUE,
                    'postalcode_extension',TRUE,'country',TRUE,'phone',TRUE
                  )
                ELSE
                  PARSE_JSON(
                    AI_COMPLETE(
                      'mistral-large2',
                      CONCAT_WS(
                        '',
                        'You are given two customer records (A and B). Compare the fields case-insensitively, trimming whitespace and treating NULL as empty. ',
                        'Return a JSON object matching the exact schema with booleans set to TRUE when the fields MATCH and FALSE when they DO NOT MATCH. ',
                        'If all fields match, set reason to "Identical match". ',
                        'Fields: name, address_line_1, address_line_2, city, county, state, postal_code, postalcode_extension, country, phone. ',
                        'Record A => ',
                        'Name: ', NVL(ci.CUSTOMER_NAME,''), '; ',
                        'Address Line 1: ', NVL(ci.ADDRESS_LINE_1,''), '; ',
                        'Address Line 2: ', NVL(ci.ADDRESS_LINE_2,''), '; ',
                        'City: ', NVL(ci.CITY,''), '; ',
                        'County: ', NVL(ci.COUNTY,''), '; ',
                        'State: ', NVL(ci.STATE,''), '; ',
                        'Postal Code: ', NVL(ci.POSTAL_CODE,''), '; ',
                        'PostalCode Extension: ', NVL(ci.POSTALCODE_EXTENSION,''), '; ',
                        'Country: ', NVL(ci.COUNTRY,''), '; ',
                        'Phone: ', NVL(ci.PHONE,''),
                        '. Record B => ',
                        'Name: ', NVL(ca.CUSTOMER_NAME,''), '; ',
                        'Address Line 1: ', NVL(ca.ADDRESS_LINE_1,''), '; ',
                        'Address Line 2: ', NVL(ca.ADDRESS_LINE_2,''), '; ',
                        'City: ', NVL(ca.CITY,''), '; ',
                        'County: ', NVL(ca.COUNTY,''), '; ',
                        'State: ', NVL(ca.STATE,''), '; ',
                        'Postal Code: ', NVL(ca.POSTAL_CODE,''), '; ',
                        'PostalCode Extension: ', NVL(ca.POSTALCODE_EXTENSION,''), '; ',
                        'Country: ', NVL(ca.COUNTRY,''), '; ',
                        'Phone: ', NVL(ca.PHONE,''),
                        '.'
                      ),
                      { 'temperature': 0, 'max_tokens': 512 },
                      {
                        'type': 'json',
                        'schema': {
                          'type': 'object',
                          'properties': {
                            'reason': { 'type': 'string' },
                            'name': { 'type': 'boolean' },
                            'address_line_1': { 'type': 'boolean' },
                            'address_line_2': { 'type': 'boolean' },
                            'city': { 'type': 'boolean' },
                            'county': { 'type': 'boolean' },
                            'state': { 'type': 'boolean' },
                            'postal_code': { 'type': 'boolean' },
                            'postalcode_extension': { 'type': 'boolean' },
                            'country': { 'type': 'boolean' },
                            'phone': { 'type': 'boolean' }
                          },
                          'required': ['reason','name','address_line_1','address_line_2','city','county','state','postal_code','postalcode_extension','country','phone']
                        }
                      }
                    )
                  )
              END
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
              AND ci.IDENTIFIER_TYPE = %s AND ci.IDENTIFIER_VALUE = %s
            """,
            (identifier_type, identifier_value)
        )

        cur.close()
        return True
    except Exception:
        return False


def run_populate_verification_message(_conn) -> None:
    cur = _conn.cursor()
    try:
        try:
            cur.execute("USE ROLE SYSADMIN")
        except Exception:
            pass
        cur.execute("USE WAREHOUSE COMPUTE_WH")
        cur.execute("USE DATABASE MDM_CUSTOMER_MATCHING")
        cur.execute("USE SCHEMA PUBLIC")
        cur.execute(
            """
            UPDATE MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_IDENTIFIER ci
            SET VERIFICATION_MESSAGE = OBJECT_CONSTRUCT(
              'reason', 'Identical match',
              'name', TRUE,
              'address_line_1', TRUE,
              'address_line_2', TRUE,
              'city', TRUE,
              'county', TRUE,
              'state', TRUE,
              'postal_code', TRUE,
              'postalcode_extension', TRUE,
              'country', TRUE,
              'phone', TRUE
            )
            FROM MDM_CUSTOMER_MATCHING.PUBLIC.CUSTOMER_ADDRESS ca
            WHERE ci.CUSTOMER_BUSINESS_ID = ca.CUSTOMER_BUSINESS_ID
              AND ci.CONFIDENCE_SCORE = 1
            """
        )
        # Prefer the SQL procedure that updates ALL rows with non-null scores (not a random sample)
        try:
            cur.execute("CALL MDM_CUSTOMER_MATCHING.PUBLIC.POPULATE_VERIFICATION_MESSAGE_SQL()")
        except Exception:
            # Fallback to legacy proc name if present
            cur.execute("CALL MDM_CUSTOMER_MATCHING.PUBLIC.POPULATE_VERIFICATION_MESSAGE()")
    finally:
        try:
            cur.close()
        except Exception:
            pass


def auto_assign_top_match_then_populate(_conn, threshold: float = 0.90) -> Tuple[bool, str, Optional[dict], Optional[dict]]:
    """Return (success, message, ci_row, top_candidate)."""
    ci_row = fetch_first_unassigned_ci(_conn)
    if not ci_row:
        return False, "No unassigned CUSTOMER_IDENTIFIER found.", None, None
    top = search_top_address_candidate(_conn, ci_row)
    if not top:
        return False, "No candidates returned from Cortex Search.", ci_row, None
    score = top.get('_SCORE') or 0.0
    if score > threshold and top.get('CUSTOMER_BUSINESS_ID'):
        ok = assign_ci_to_business_id(
            _conn,
            ci_row.get('IDENTIFIER_TYPE'),
            ci_row.get('IDENTIFIER_VALUE'),
            top.get('CUSTOMER_BUSINESS_ID')
        )
        if not ok:
            return False, "Assign failed.", ci_row, top
        run_populate_verification_message(_conn)
        return True, f"Assigned with score {score:.3f} and populated verification message.", ci_row, top
    return False, f"Top score {score:.3f} not > {threshold:.2f}; no assignment performed.", ci_row, top