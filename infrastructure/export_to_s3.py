"""
export_to_s3.py — Exports the DynamoDB tables to the Bronze layer.

Medallion Architecture — Bronze layer:
  Raw, untouched data. The source is always preserved here.

Hive partition format (Athena recognizes it automatically):
  s3://heweso-data-lake/bronze/sales/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/audit/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/competitors/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/products/date=2026-06-26/data.json

Why it exists / how it fits:
  This is the entry point of the data pipeline. The main Lambda runs it hourly
  (handler._maybe_export_to_s3) so Athena always has fresh data to query. Note it
  does a FULL scan each run (not incremental), so each snapshot holds all history.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION        = os.getenv("AWS_REGION", "eu-central-1")
BUCKET            = "heweso-data-lake"
PRODUCTS_TABLE    = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")
SALES_TABLE       = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")
AUDIT_TABLE       = os.getenv("DYNAMODB_AUDIT_TABLE", "heweso-audit-log")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
s3       = boto3.client("s3", region_name=AWS_REGION)

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def export_table(table_name: str, bronze_prefix: str) -> int:
    """
    Scans a DynamoDB table and writes it to the Bronze layer in Hive partition format.

    bronze_prefix: "sales", "audit", "competitors", "products"
    S3 target: bronze/{prefix}/date={today}/data.json
    """
    table = dynamodb.Table(table_name)
    items = []
    response = table.scan()
    items.extend(response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])

    # Newline-delimited JSON (NDJSON) — Athena reads this format directly
    body = "\n".join(json.dumps(item, default=_decimal_default) for item in items)

    # Hive partition format: the date= prefix is the standard Athena auto-detects
    key = f"bronze/{bronze_prefix}/date={today}/data.json"

    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"  ✅ {len(items)} rows → s3://{BUCKET}/{key}")
    return len(items)


def run_export():
    print(f"\n=== DynamoDB → S3 Bronze Export ({today}) ===")
    total = 0
    total += export_table(SALES_TABLE,        "sales")
    total += export_table(AUDIT_TABLE,         "audit")
    total += export_table(COMPETITORS_TABLE,   "competitors")
    total += export_table(PRODUCTS_TABLE,      "products")
    print(f"\n✅ Bronze export complete — {total} total rows")
    return total


if __name__ == "__main__":
    run_export()
