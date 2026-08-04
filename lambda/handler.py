"""
Lambda entry point.

Triggered by EventBridge.
If the event contains a product_id, checks only that product.
Otherwise scans and checks all products.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Lambda runs under /var/task — add to import path
sys.path.insert(0, "/var/task")

from agent.bedrock_agent import run_agent
from tools.query_sales import query_sales


def lambda_handler(event, context):
    """
    EventBridge event formats:

    Specific product:
        {"product_id": "PROD-001"}

    All products (scheduled rule):
        {} or {"source": "aws.events"}
    """
    print(f"Event received: {json.dumps(event)}")

    # Hourly automatic S3 export — keep Athena's elasticity data fresh
    _maybe_export_to_s3()

    product_ids = _get_product_ids(event)
    results = []

    for product_id in product_ids:
        # Quick sales check — skip agent if sales are healthy
        sales = query_sales(product_id, minutes=60)

        if sales["status"] == "healthy":
            print(f"[SKIP] {product_id} — sales are running, agent not started.")
            results.append({"product_id": product_id, "action": "skipped"})
            continue

        print(f"[TRIGGER] {product_id} — sales stopped, starting agent...")
        summary = run_agent(product_id, trigger_reason="No sales in the last 60 minutes")
        results.append({"product_id": product_id, "action": "agent_run", "summary": summary})

    return {
        "statusCode": 200,
        "body": json.dumps(results, ensure_ascii=False),
    }


def _maybe_export_to_s3():
    """
    At the top of every hour (minute == 0) runs the full Medallion pipeline:
      1. Bronze: DynamoDB → S3 (raw data)
      2. Silver: Bronze → cleaned + joined
      3. Gold:   Silver → aggregated + business metrics
    """
    now = datetime.now(timezone.utc)
    if now.minute != 0:
        return
    try:
        from infrastructure.export_to_s3 import run_export
        from infrastructure.medallion.silver import run_silver
        from infrastructure.medallion.gold import run_gold

        print("[MEDALLION] Top of hour — running full pipeline...")

        print("[MEDALLION] Step 1/3: DynamoDB → Bronze (S3)")
        run_export()

        print("[MEDALLION] Step 2/3: Bronze → Silver")
        run_silver()

        print("[MEDALLION] Step 3/3: Silver → Gold")
        run_gold()

        print("[MEDALLION] Pipeline complete.")
    except Exception as e:
        print(f"[MEDALLION] Failed (non-fatal): {e}")


def _get_product_ids(event: dict) -> list:
    """Extracts product_id list from the event."""

    # Specific product provided — check only that one
    if "product_id" in event:
        return [event["product_id"]]

    # Scheduled EventBridge rule — check all products
    return _scan_all_product_ids()


def _scan_all_product_ids() -> list:
    """Fetches all product_ids from the Products table."""
    import boto3
    from dotenv import load_dotenv

    load_dotenv()

    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-central-1"))
    table = dynamodb.Table(os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products"))

    response = table.scan(ProjectionExpression="product_id")
    return [item["product_id"] for item in response.get("Items", [])]
