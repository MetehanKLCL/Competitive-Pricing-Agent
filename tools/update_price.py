"""
update_price — Updates the product price in DynamoDB.

min_price floor and base_price ceiling are enforced here;
the agent can never price below the floor or above the ceiling.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(PRODUCTS_TABLE)


def update_price(product_id: str, new_price: float, reason: str) -> dict:
    """
    Updates the product price.

    Rules:
    - new_price cannot go below min_price.
    - new_price cannot go above base_price.
    - Returns an error if the product is not found.
    - Returns success=False if new_price equals the current price.

    Returns:
        {
            "success": bool,
            "product_id": str,
            "old_price": float | None,
            "new_price": float | None,
            "min_price": float | None,
            "reason": str,
            "error": str | None,
        }
    """
    response = _table.get_item(Key={"product_id": product_id})
    item = response.get("Item")

    if not item:
        return {
            "success": False,
            "product_id": product_id,
            "old_price": None,
            "new_price": None,
            "min_price": None,
            "reason": reason,
            "error": f"Product not found: {product_id}",
        }

    old_price = float(item["current_price"])
    min_price = float(item["min_price"])
    base_price = float(item.get("base_price", 0)) or None

    if new_price == old_price:
        return {
            "success": False,
            "product_id": product_id,
            "old_price": old_price,
            "new_price": new_price,
            "min_price": min_price,
            "reason": reason,
            "error": "Price is already the same — no update needed.",
        }

    if new_price < min_price:
        return {
            "success": False,
            "product_id": product_id,
            "old_price": old_price,
            "new_price": new_price,
            "min_price": min_price,
            "reason": reason,
            "error": (
                f"Price is below min_price floor: "
                f"requested={new_price}, min={min_price}"
            ),
        }

    if base_price is not None and new_price > base_price:
        return {
            "success": False,
            "product_id": product_id,
            "old_price": old_price,
            "new_price": new_price,
            "min_price": min_price,
            "reason": reason,
            "error": (
                f"Price is above base_price ceiling: "
                f"requested={new_price}, base={base_price}"
            ),
        }

    now = datetime.now(timezone.utc).isoformat()
    _table.update_item(
        Key={"product_id": product_id},
        UpdateExpression="SET current_price = :p, updated_at = :t",
        ExpressionAttributeValues={
            ":p": Decimal(str(new_price)),
            ":t": now,
        },
    )

    return {
        "success": True,
        "product_id": product_id,
        "old_price": old_price,
        "new_price": new_price,
        "min_price": min_price,
        "reason": reason,
        "error": None,
    }


if __name__ == "__main__":
    result = update_price("PROD-001", 23499.0, "Matching Trendyol price")
    print(result)
