"""
query_sales — Fetches sales from DynamoDB for the last X minutes.

Uses GSI: product_id-timestamp-index
"""

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
SALES_TABLE = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(SALES_TABLE)
_products_table = _dynamodb.Table(PRODUCTS_TABLE)


def query_sales(product_id: str, minutes: int = 60) -> dict:
    """
    Queries sales in the last `minutes` minutes.
    Also returns the product's current price so the agent can make pricing decisions.

    Returns:
        {
            "status": "critical" | "healthy",
            "sale_count": int,
            "last_sale": str | None,
            "product_id": str,
            "product_name": str,
            "current_price": float,
            "min_price": float,
            "window_minutes": int,
        }
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    response = _table.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id) & Key("timestamp").gte(cutoff)
        ),
        ScanIndexForward=False,
    )

    items = response.get("Items", [])
    sale_count = len(items)
    last_sale = items[0]["timestamp"] if items else None

    product = _products_table.get_item(Key={"product_id": product_id}).get("Item", {})

    return {
        "status": "critical" if sale_count == 0 else "healthy",
        "sale_count": sale_count,
        "last_sale": last_sale,
        "product_id": product_id,
        "product_name": product.get("name", ""),
        "current_price": float(product.get("current_price", 0)),
        "base_price": float(product.get("base_price", product.get("current_price", 0))),
        "min_price": float(product.get("min_price", 0)),
        "window_minutes": minutes,
    }


if __name__ == "__main__":
    result = query_sales("PROD-001", minutes=60)
    print(result)
