"""
Shared utility functions for the Customer Matching application.
This module contains functions that are used across multiple pages.
"""

import streamlit as st
import pandas as pd
from typing import Dict

# Default thresholds - matches the original working configuration
DEFAULT_THRESHOLDS = {
    'exact': 0.995,
    'very_close': 0.980,
    'somewhat_close': 0.920
}

def recalculate_all_similarities(_conn, thresholds: Dict[str, float] = None) -> bool:
    """Recalculate ALL similarities using the exact working SQL with user's threshold values"""
    try:
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()
            
        cursor = _conn.cursor()
        
        # Update all embeddings to ensure they're current
        embedding_sql = """
        UPDATE TEST_MATCHES 
        SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
        """
        cursor.execute(embedding_sql)
        
        # Delete all existing results
        delete_sql = "DELETE FROM CUSTOMER_MATCH_RESULTS"
        cursor.execute(delete_sql)
        
        # Recalculate all similarities using the exact working SQL with user's thresholds
        recalc_sql = """
        INSERT INTO CUSTOMER_MATCH_RESULTS 
        (VALID_ID, VALID_CUSTOMER_FULL_DETAIL, TEST_ID, TEST_CUSTOMER_FULL_DETAIL, SIMILARITY_SCORE, MATCH_CATEGORY)
        SELECT
            v.ID AS VALID_ID,
            v.CUSTOMER_FULL_DETAIL AS VALID_CUSTOMER_FULL_DETAIL,
            t.SOURCE_PKEY AS TEST_ID,
            t.CUSTOMER_FULL_DETAIL AS TEST_CUSTOMER_FULL_DETAIL,
            VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) AS SIMILARITY_SCORE,
            CASE
                WHEN SIMILARITY_SCORE >= %s THEN 'EXACT'
                WHEN SIMILARITY_SCORE >= %s THEN 'VERY_CLOSE'
                WHEN SIMILARITY_SCORE >= %s THEN 'SOMEWHAT_CLOSE'
                ELSE 'NOT_CLOSE'
            END AS MATCH_CATEGORY
        FROM VALID_CUSTOMERS v
        CROSS JOIN TEST_MATCHES t
        WHERE v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR IS NOT NULL
            AND t.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY t.SOURCE_PKEY ORDER BY SIMILARITY_SCORE DESC) = 1
        """
        cursor.execute(recalc_sql, (thresholds['exact'], thresholds['very_close'], thresholds['somewhat_close']))
        
        cursor.close()
        return True
        
    except Exception as e:
        st.error(f"Error recalculating similarities: {str(e)}")
        return False


def recalculate_similarity_for_test_id(_conn, test_id: str, thresholds: Dict[str, float] = None) -> bool:
    """Recalculate similarity for a single test record identified by SOURCE_PKEY.

    This function updates the embedding for the specific test record, removes any
    existing result rows for that test id from `CUSTOMER_MATCH_RESULTS`, and then
    inserts the top 1 best match calculated against all valid customers using the
    provided thresholds.
    """
    try:
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()

        cursor = _conn.cursor()

        # Ensure the test record's embedding is up to date
        update_embedding_sql = """
        UPDATE TEST_MATCHES 
        SET CUSTOMER_FULL_DETAIL_EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m', CUSTOMER_FULL_DETAIL)
        WHERE SOURCE_PKEY = %s
        """
        cursor.execute(update_embedding_sql, (test_id,))

        # Remove existing results for this specific test id
        delete_sql = "DELETE FROM CUSTOMER_MATCH_RESULTS WHERE TEST_ID = %s"
        cursor.execute(delete_sql, (test_id,))

        # Insert recalculated top-1 match for this test id
        insert_sql = """
        INSERT INTO CUSTOMER_MATCH_RESULTS 
        (VALID_ID, VALID_CUSTOMER_FULL_DETAIL, TEST_ID, TEST_CUSTOMER_FULL_DETAIL, SIMILARITY_SCORE, MATCH_CATEGORY)
        SELECT
            v.ID AS VALID_ID,
            v.CUSTOMER_FULL_DETAIL AS VALID_CUSTOMER_FULL_DETAIL,
            t.SOURCE_PKEY AS TEST_ID,
            t.CUSTOMER_FULL_DETAIL AS TEST_CUSTOMER_FULL_DETAIL,
            VECTOR_COSINE_SIMILARITY(v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR, t.CUSTOMER_FULL_DETAIL_EMBEDDING) AS SIMILARITY_SCORE,
            CASE
                WHEN SIMILARITY_SCORE >= %s THEN 'EXACT'
                WHEN SIMILARITY_SCORE >= %s THEN 'VERY_CLOSE'
                WHEN SIMILARITY_SCORE >= %s THEN 'SOMEWHAT_CLOSE'
                ELSE 'NOT_CLOSE'
            END AS MATCH_CATEGORY
        FROM VALID_CUSTOMERS v
        CROSS JOIN TEST_MATCHES t
        WHERE t.SOURCE_PKEY = %s
          AND v.CUSTOMER_FULL_DETAIL_EMBEDDING_VECTOR IS NOT NULL
          AND t.CUSTOMER_FULL_DETAIL_EMBEDDING IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY t.SOURCE_PKEY ORDER BY SIMILARITY_SCORE DESC) = 1
        """
        cursor.execute(
            insert_sql,
            (
                thresholds['exact'],
                thresholds['very_close'],
                thresholds['somewhat_close'],
                test_id,
            ),
        )

        cursor.close()
        return True

    except Exception as e:
        st.error(f"Error recalculating similarity for {test_id}: {str(e)}")
        return False