"""
export_to_s3.py — DynamoDB tablolarını Bronze katmanına export eder.

Medallion Architecture — Bronze katmanı:
  Ham, dokunulmamış veri. Kaynak her zaman burada korunur.

Hive partition formatı (Athena otomatik tanır):
  s3://heweso-data-lake/bronze/sales/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/audit/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/competitors/date=2026-06-26/data.json
  s3://heweso-data-lake/bronze/products/date=2026-06-26/data.json
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
    DynamoDB tablosunu tarar ve Bronze katmanına Hive partition formatında yazar.

    bronze_prefix: "sales", "audit", "competitors", "products"
    S3 hedef: bronze/{prefix}/date={today}/data.json
    """
    table = dynamodb.Table(table_name)
    items = []
    response = table.scan()
    items.extend(response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])

    # Newline-delimited JSON (NDJSON) — Athena bu formatı doğrudan okur
    body = "\n".join(json.dumps(item, default=_decimal_default) for item in items)

    # Hive partition formatı: date= prefix'i Athena'nın otomatik tanıdığı standarttır
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
