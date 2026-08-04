"""
Demo script: flash sale vs structural competitor pattern.

Usage:
  python3 tests/demo_competitor_pattern.py flash      → undercut_since = now (FLASH_SALE)
  python3 tests/demo_competitor_pattern.py structural → undercut_since = 4 hours ago (STRUCTURAL)
  python3 tests/demo_competitor_pattern.py reset      → clear undercut_since
"""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION        = os.getenv("AWS_REGION", "eu-central-1")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")
PRODUCTS_TABLE    = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

UNDERCUT_PAIRS = [
    # Competitors priced below us (seed data default)
    ("PROD-001", "Trendyol"),
    ("PROD-002", "Trendyol"),
    ("PROD-003", "Trendyol"),
]


def set_undercut_since(minutes_ago: int):
    table = dynamodb.Table(COMPETITORS_TABLE)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    for pid, comp in UNDERCUT_PAIRS:
        table.update_item(
            Key={"product_id": pid, "competitor_name": comp},
            UpdateExpression="SET undercut_since = :t",
            ExpressionAttributeValues={":t": ts},
        )
    print(f"✅ undercut_since = {minutes_ago} minutes ago ({ts[:19]})")


def clear_undercut():
    table = dynamodb.Table(COMPETITORS_TABLE)
    for pid, comp in UNDERCUT_PAIRS:
        table.update_item(
            Key={"product_id": pid, "competitor_name": comp},
            UpdateExpression="REMOVE undercut_since",
        )
    print("✅ undercut_since cleared")


def show_status():
    from tools.check_competitor_pattern import check_competitor_pattern
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = check_competitor_pattern(pid)
        mins = f"{r['undercut_minutes']:.0f}min" if r['undercut_minutes'] is not None else "—"
        print(f"  {pid}: {r['pattern']:15} ({mins}) | {r['recommendation'][:60]}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "flash":
        set_undercut_since(5)   # 5 minutes ago → FLASH_SALE
        print("\nStatus:")
        show_status()
        print("\nEffect: The agent will say 'FLASH_SALE — waiting' and not change the price.")

    elif mode == "structural":
        set_undercut_since(240)  # 4 hours ago → STRUCTURAL
        print("\nStatus:")
        show_status()
        print("\nEffect: The agent will say 'STRUCTURAL — acting' and lower the price.")

    elif mode == "reset":
        clear_undercut()
        print("\nStatus (cleared):")
        show_status()

    else:
        print("Status:")
        show_status()
