"""
check_outcome — Did the last price change actually bring sales back?

Queries AuditLog for the most recent PRICE_UPDATE for a product,
then checks if sales recovered after that change.
"""

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AUDIT_TABLE = os.getenv("DYNAMODB_AUDIT_TABLE", "heweso-audit-log")
SALES_TABLE = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")

# Bir fiyat değişimini "başarılı" saymak için, satışın değişimden sonraki bu
# pencere içinde gelmesi gerekir. Üst sınır olmadan, günler sonra gelen bir
# satış bile yanlışlıkla "değişim işe yaradı" sayılırdı. analyze_price_elasticity
# ile aynı 60 dakikalık pencereyi kullanıyoruz — tutarlılık için.
OUTCOME_WINDOW_MIN = 60
# Değişimin üstünden bu kadar dakika geçmeden FAILED demiyoruz (çok erken).
# Demo değeri 2dk; prodüksiyonda 15-30dk olmalı.
PENDING_MIN = 2

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_audit = _dynamodb.Table(AUDIT_TABLE)
_sales = _dynamodb.Table(SALES_TABLE)


def check_outcome(product_id: str) -> dict:
    """
    Finds the most recent PRICE_UPDATE log for the product and checks
    if sales recovered after that change.

    Returns:
        {
            "had_recent_change": bool,
            "changed_at": str | None,
            "old_price": str | None,
            "new_price": str | None,
            "sales_after_change": int,
            "outcome": "SUCCESS" | "FAILED" | "NO_RECENT_CHANGE",
            "outcome_detail": str,
        }
    """
    # Get all audit logs for this product
    response = _audit.scan(
        FilterExpression="product_id = :pid AND #a = :act",
        ExpressionAttributeNames={"#a": "action"},
        ExpressionAttributeValues={
            ":pid": product_id,
            ":act": "PRICE_UPDATE",
        },
    )
    items = response.get("Items", [])

    # Only consider genuine price changes (old != new)
    items = [
        i for i in items
        if i.get("old_value") and i.get("new_value")
        and str(i["old_value"]).strip() != str(i["new_value"]).strip()
    ]

    if not items:
        return {
            "had_recent_change": False,
            "changed_at": None,
            "old_price": None,
            "new_price": None,
            "sales_after_change": 0,
            "outcome": "NO_RECENT_CHANGE",
            "outcome_detail": "No real price change found in audit log.",
        }

    # Most recent genuine PRICE_UPDATE
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    last_change = items[0]
    changed_at = last_change["timestamp"]

    # How long ago was the change?
    changed_dt = datetime.fromisoformat(changed_at)
    now = datetime.now(timezone.utc)
    minutes_since = (now - changed_dt).total_seconds() / 60

    # Count sales inside a bounded [change, change + OUTCOME_WINDOW_MIN] window.
    # Bounding the upper edge means only sales that plausibly FOLLOWED the change
    # count as success — a sale days later no longer gets credited to it.
    window_end = (changed_dt + timedelta(minutes=OUTCOME_WINDOW_MIN)).isoformat()
    sales_response = _sales.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id)
            & Key("timestamp").between(changed_at, window_end)
        ),
    )
    sales_after = len(sales_response.get("Items", []))

    if sales_after >= 1:
        outcome = "SUCCESS"
        detail = (
            f"Price changed {int(minutes_since)}m ago from {last_change.get('old_value')} "
            f"to {last_change.get('new_value')}. "
            f"{sales_after} sale(s) recorded within {OUTCOME_WINDOW_MIN}min of the change. Strategy worked."
        )
    elif minutes_since < PENDING_MIN:
        outcome = "PENDING"
        detail = (
            f"Price changed {int(minutes_since * 60):.0f}s ago. "
            f"Too early to evaluate — waiting for sales data."
        )
    else:
        outcome = "FAILED"
        detail = (
            f"Price changed {int(minutes_since)}m ago from {last_change.get('old_value')} "
            f"to {last_change.get('new_value')}. "
            f"No sales recorded within {OUTCOME_WINDOW_MIN}min of the change. Strategy did not work."
        )

    return {
        "had_recent_change": True,
        "changed_at": changed_at,
        "old_price": last_change.get("old_value"),
        "new_price": last_change.get("new_value"),
        "sales_after_change": sales_after,
        "outcome": outcome,
        "outcome_detail": detail,
    }


if __name__ == "__main__":
    result = check_outcome("PROD-001")
    print(result)
