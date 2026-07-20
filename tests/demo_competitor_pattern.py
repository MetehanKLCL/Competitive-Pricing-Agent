"""
Demo script: flash sale vs structural competitor pattern.

Kullanım:
  python3 tests/demo_competitor_pattern.py flash      → undercut_since = şimdi (FLASH_SALE)
  python3 tests/demo_competitor_pattern.py structural → undercut_since = 4 saat önce (STRUCTURAL)
  python3 tests/demo_competitor_pattern.py reset      → undercut_since temizle
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
    # Fiyatı bizden düşük olan rakipler (seed data varsayılan)
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
    print(f"✅ undercut_since = {minutes_ago} dakika önce ({ts[:19]})")


def clear_undercut():
    table = dynamodb.Table(COMPETITORS_TABLE)
    for pid, comp in UNDERCUT_PAIRS:
        table.update_item(
            Key={"product_id": pid, "competitor_name": comp},
            UpdateExpression="REMOVE undercut_since",
        )
    print("✅ undercut_since temizlendi")


def show_status():
    from tools.check_competitor_pattern import check_competitor_pattern
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = check_competitor_pattern(pid)
        mins = f"{r['undercut_minutes']:.0f}dk" if r['undercut_minutes'] is not None else "—"
        print(f"  {pid}: {r['pattern']:15} ({mins}) | {r['recommendation'][:60]}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "flash":
        set_undercut_since(5)   # 5 dakika önce → FLASH_SALE
        print("\nDurum:")
        show_status()
        print("\nEfekt: Ajan 'FLASH_SALE — bekliyorum' diyecek, fiyat değiştirmeyecek.")

    elif mode == "structural":
        set_undercut_since(240)  # 4 saat önce → STRUCTURAL
        print("\nDurum:")
        show_status()
        print("\nEfekt: Ajan 'STRUCTURAL — harekete geçiyorum' diyecek, fiyat düşürecek.")

    elif mode == "reset":
        clear_undercut()
        print("\nDurum (temizlendi):")
        show_status()

    else:
        print("Durum:")
        show_status()
