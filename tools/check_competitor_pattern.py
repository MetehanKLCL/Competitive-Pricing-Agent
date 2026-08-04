"""
check_competitor_pattern — Detects whether a competitor's price drop is a
flash sale or a lasting (structural) change.

Method:
  Looks at the undercut_since field in the CompetitorPrices table. This field is
  set when a competitor's price first drops below ours. The older undercut_since
  is, the more permanent the change is.

Decision:
  < 60 minutes  → FLASH_SALE  (wait, don't react)
  60-180 min    → MONITOR     (watch, not yet clear)
  > 180 minutes → STRUCTURAL  (lasting change, act)
  no undercut_since → NOT_UNDERCUT (competitor is more expensive/equal to us)

Why it exists / how it fits:
  Without this, the agent reacted to every temporary competitor discount. It
  keeps the agent from chasing flash sales while still matching real structural
  price moves.
"""

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION        = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE    = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def check_competitor_pattern(product_id: str) -> dict:
    """
    Analyzes how long competitors have been undercutting our price.

    Returns:
        {
            "pattern":            "FLASH_SALE" | "MONITOR" | "STRUCTURAL" | "NOT_UNDERCUT",
            "cheapest_competitor": str,
            "cheapest_price":      float,
            "our_price":           float,
            "undercut_minutes":    float | None,
            "recommendation":      str,
        }
    """
    now = datetime.now(timezone.utc)

    # Our price
    product = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": product_id}).get("Item", {})
    our_price = float(product.get("current_price", 0))

    # Competitor prices
    comps = _dynamodb.Table(COMPETITORS_TABLE) \
        .query(KeyConditionExpression=Key("product_id").eq(product_id)) \
        .get("Items", [])

    if not comps:
        return {
            "pattern": "NOT_UNDERCUT", "cheapest_competitor": None,
            "cheapest_price": None, "our_price": our_price,
            "undercut_minutes": None,
            "recommendation": "No competitor data available.",
        }

    cheapest = min(comps, key=lambda x: float(x["price"]))
    C = float(cheapest["price"])
    comp_name = cheapest["competitor_name"]

    # Stale-timer cleanup: reset undercut_since for every competitor that is NO
    # longer cheaper than us. Otherwise, once a competitor drops (stamp written)
    # then rises again, the stamp lingers; when it drops again later the old
    # stamp would wrongly mark it STRUCTURAL and the flash-sale guard breaks.
    for comp in comps:
        if float(comp["price"]) >= our_price and comp.get("undercut_since"):
            clear_undercut(product_id, comp["competitor_name"])

    if C >= our_price:
        return {
            "pattern": "NOT_UNDERCUT", "cheapest_competitor": comp_name,
            "cheapest_price": C, "our_price": our_price,
            "undercut_minutes": None,
            "recommendation": f"{comp_name} ({C}) is not cheaper than our price ({our_price}).",
        }

    # When did it go cheaper?
    undercut_since = cheapest.get("undercut_since")

    if not undercut_since:
        # First time detected — write undercut_since
        _dynamodb.Table(COMPETITORS_TABLE).update_item(
            Key={"product_id": product_id, "competitor_name": comp_name},
            UpdateExpression="SET undercut_since = :t",
            ExpressionAttributeValues={":t": now.isoformat()},
        )
        return {
            "pattern": "FLASH_SALE",
            "cheapest_competitor": comp_name,
            "cheapest_price": C,
            "our_price": our_price,
            "undercut_minutes": 0,
            "recommendation": (
                f"{comp_name} just dropped to {C} (we are at {our_price}). "
                f"First detected now — treating as potential flash sale. Monitor."
            ),
        }

    undercut_dt   = datetime.fromisoformat(undercut_since)
    undercut_mins = (now - undercut_dt).total_seconds() / 60

    if undercut_mins < 60:
        pattern = "FLASH_SALE"
        rec = (
            f"{comp_name} has been cheaper for {undercut_mins:.0f} min. "
            f"Likely a flash sale — do NOT match yet. Wait for 60+ min."
        )
    elif undercut_mins < 180:
        pattern = "MONITOR"
        rec = (
            f"{comp_name} has been cheaper for {undercut_mins:.0f} min. "
            f"Situation unclear — monitor closely. Consider acting if it continues."
        )
    else:
        pattern = "STRUCTURAL"
        rec = (
            f"{comp_name} has been cheaper for {undercut_mins:.0f} min ({undercut_mins/60:.1f}h). "
            f"This is a structural price change — match competitor price."
        )

    return {
        "pattern":             pattern,
        "cheapest_competitor": comp_name,
        "cheapest_price":      C,
        "our_price":           our_price,
        "undercut_minutes":    round(undercut_mins, 1),
        "recommendation":      rec,
    }


def clear_undercut(product_id: str, competitor_name: str) -> None:
    """Resets undercut_since once the competitor is no longer cheaper than us."""
    _dynamodb.Table(COMPETITORS_TABLE).update_item(
        Key={"product_id": product_id, "competitor_name": competitor_name},
        UpdateExpression="REMOVE undercut_since",
    )


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = check_competitor_pattern(pid)
        print(f"{pid}: {r['pattern']} | {r['recommendation']}")
