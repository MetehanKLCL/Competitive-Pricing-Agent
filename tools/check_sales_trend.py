"""
check_sales_trend — Compares sales velocity across two time windows.

What it does:
  - Counts sales in the last X minutes vs the previous X minutes.
  - Classifies the change into OK / WARNING / CRITICAL / SURGE / NO_DATA.

Why it exists / how it fits:
  This is STEP 1 of the agent's decision flow — the trend it returns drives
  everything downstream (crisis pricing on CRITICAL, price raise / bundle
  discount on SURGE). A min-volume gate keeps a single sale from faking a SURGE.
"""

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION  = os.getenv("AWS_REGION", "eu-central-1")
SALES_TABLE = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table    = _dynamodb.Table(SALES_TABLE)

# Minimum volume threshold that separates a real SURGE from noise. When the
# previous window is empty (previous_count == 0) even a single sale looks like a
# 100% jump and produces a fake SURGE — which would trigger a needless price
# raise / bundle discount. A SURGE is only declared if the latest window has at
# least this many sales.
MIN_SURGE_COUNT = 3


def check_sales_trend(product_id: str, window_minutes: int = 30) -> dict:
    """
    Compares the last window_minutes minutes with the previous window_minutes.

    Returns:
        {
            "trend":          "OK" | "WARNING" | "CRITICAL" | "SURGE" | "NO_DATA",
            "current_count":  int,   # sales in the last X minutes
            "previous_count": int,   # sales in the previous X minutes
            "change_pct":     float, # % change (negative = drop)
            "message":        str,   # human-readable explanation
        }
    """
    now      = datetime.now(timezone.utc)
    t_now    = now.isoformat()
    t_mid    = (now - timedelta(minutes=window_minutes)).isoformat()
    t_start  = (now - timedelta(minutes=window_minutes * 2)).isoformat()

    # Latest window
    r_current = _table.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id)
            & Key("timestamp").between(t_mid, t_now)
        ),
    )
    current_count = len(r_current.get("Items", []))

    # Previous window
    r_previous = _table.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id)
            & Key("timestamp").between(t_start, t_mid)
        ),
    )
    previous_count = len(r_previous.get("Items", []))

    # No data at all
    if previous_count == 0 and current_count == 0:
        return {
            "trend": "NO_DATA",
            "current_count": 0,
            "previous_count": 0,
            "change_pct": 0.0,
            "message": f"No sales data in last {window_minutes * 2} minutes.",
        }

    # Compute % change
    if previous_count == 0:
        change_pct = 100.0  # nothing before, sales now → SURGE
    else:
        change_pct = ((current_count - previous_count) / previous_count) * 100

    # Trend category
    if change_pct <= -80:
        trend   = "CRITICAL"
        message = (
            f"CRITICAL DROP: Sales fell {abs(change_pct):.0f}% "
            f"({previous_count} → {current_count} in last {window_minutes}min). "
            f"Treat as crisis — check competitors immediately."
        )
    elif change_pct <= -50:
        trend   = "WARNING"
        message = (
            f"WARNING: Sales dropped {abs(change_pct):.0f}% "
            f"({previous_count} → {current_count} in last {window_minutes}min). "
            f"Proactive competitor check recommended."
        )
    elif change_pct >= 100 and current_count >= MIN_SURGE_COUNT:
        trend   = "SURGE"
        message = (
            f"SURGE: Sales up {change_pct:.0f}% "
            f"({previous_count} → {current_count} in last {window_minutes}min). "
            f"Consider raising price."
        )
    else:
        trend   = "OK"
        message = (
            f"Stable: {previous_count} → {current_count} sales "
            f"({change_pct:+.0f}%) in last {window_minutes}min."
        )

    return {
        "trend":          trend,
        "current_count":  current_count,
        "previous_count": previous_count,
        "change_pct":     round(change_pct, 1),
        "message":        message,
    }


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = check_sales_trend(pid)
        print(f"{pid}: {r['trend']} | {r['message']}")
