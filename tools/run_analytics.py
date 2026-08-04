"""
run_analytics — Runs a SQL query on Athena and returns results.
Agent uses this to analyze its own performance.
"""

import os
import time

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION   = os.getenv("AWS_REGION", "eu-central-1")
WORKGROUP    = "heweso"
DATABASE     = "heweso_analytics"
OUTPUT_LOC   = "s3://heweso-data-lake/athena-results/"

_athena = boto3.client("athena", region_name=AWS_REGION)


def run_analytics(sql: str, max_rows: int = 20) -> dict:
    """
    Executes a SQL query against Athena (heweso_analytics database).
    Always use fully qualified table names: heweso_analytics.audit_log, etc.

    Available tables:
      - heweso_analytics.audit_log   (log_id, timestamp, product_id, action, old_value, new_value, reason)
      - heweso_analytics.sales       (sale_id, timestamp, product_id, quantity, price_at_sale)
      - heweso_analytics.competitors (product_id, competitor_name, price)
      - heweso_analytics.products    (product_id, name, current_price, base_price, min_price)

    Returns:
        {
            "success": bool,
            "columns": [str],
            "rows": [[str]],
            "row_count": int,
            "error": str | None,
        }
    """
    # Read-only guard: the model writes free-form SQL but may only read.
    # DROP/CREATE/INSERT and a second statement chained with ";" are rejected.
    normalized = sql.strip().rstrip(";").strip()
    first_word = normalized.split(None, 1)[0].upper() if normalized else ""
    if first_word not in ("SELECT", "WITH"):
        return {
            "success": False, "columns": [], "rows": [], "row_count": 0,
            "error": f"Only read-only SELECT/WITH queries are allowed, got: {first_word or 'empty query'}",
        }
    if ";" in normalized:
        return {
            "success": False, "columns": [], "rows": [], "row_count": 0,
            "error": "Multiple SQL statements are not allowed — send a single SELECT query.",
        }
    sql = normalized

    try:
        response = _athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": DATABASE},
            WorkGroup=WORKGROUP,
            ResultConfiguration={"OutputLocation": OUTPUT_LOC},
        )
        exec_id = response["QueryExecutionId"]

        # Poll until done
        for _ in range(30):
            status = _athena.get_query_execution(QueryExecutionId=exec_id)
            state  = status["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            if state in ("FAILED", "CANCELLED"):
                reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
                return {"success": False, "columns": [], "rows": [], "row_count": 0, "error": reason}
            time.sleep(1)

        result  = _athena.get_query_results(QueryExecutionId=exec_id, MaxResults=max_rows + 1)
        raw_rows = result["ResultSet"]["Rows"]
        columns  = [c["VarCharValue"] for c in raw_rows[0]["Data"]]
        rows     = [
            [cell.get("VarCharValue", "") for cell in row["Data"]]
            for row in raw_rows[1:]
        ]

        return {
            "success":   True,
            "columns":   columns,
            "rows":      rows,
            "row_count": len(rows),
            "error":     None,
        }

    except Exception as e:
        return {"success": False, "columns": [], "rows": [], "row_count": 0, "error": str(e)}


if __name__ == "__main__":
    result = run_analytics("""
        SELECT action, COUNT(*) as count
        FROM heweso_analytics.audit_log
        GROUP BY action ORDER BY count DESC
        LIMIT 10
    """)
    print("Columns:", result["columns"])
    for row in result["rows"]:
        print(row)
