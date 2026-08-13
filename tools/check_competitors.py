"""
check_competitors — Fetches competitor prices for a product from DynamoDB.
"""

import os

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(COMPETITORS_TABLE)


def check_competitors(product_id: str) -> list:
    """
    Returns all competitor prices for the given product, sorted cheapest first.

    Returns:
        [
            {
                "competitor": str,
                "price": float,
                "url": str,
                "last_checked": str,
            },
            ...
        ]
    """
    response = _table.query(
        KeyConditionExpression=Key("product_id").eq(product_id)
    )

    items = response.get("Items", [])

    competitors = []
    for item in items:
        # Skip malformed rows that have no usable price. A partial record can
        # appear if something upserts a competitor by key without a price (e.g.
        # a stale demo/undercut helper). One bad row must not crash the whole
        # competitor check.
        if item.get("price") is None:
            continue
        try:
            price = float(item["price"])
        except (TypeError, ValueError):
            continue
        competitors.append({
            "competitor": item["competitor_name"],
            "price": price,
            "url": item.get("url", ""),
            "last_checked": item.get("last_checked", ""),
        })

    competitors.sort(key=lambda x: x["price"])
    return competitors


if __name__ == "__main__":
    result = check_competitors("PROD-001")
    for c in result:
        print(c)
