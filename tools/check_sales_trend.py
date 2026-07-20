"""
check_sales_trend — Satış hızını karşılaştırır.

Son X dakika vs önceki X dakikayı karşılaştırarak
satışların düşüp düşmediğini tespit eder.
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

# SURGE'ü gürültüden ayırmak için minimum hacim eşiği. Önceki pencere boşsa
# (previous_count == 0) tek bir satış bile %100 artış gibi görünür ve sahte
# SURGE üretir — bu da gereksiz fiyat yükseltmesi / bundle indirimi tetikler.
# SURGE ancak son pencerede en az bu kadar satış varsa ilan edilir.
MIN_SURGE_COUNT = 3


def check_sales_trend(product_id: str, window_minutes: int = 30) -> dict:
    """
    Son window_minutes dakikayı önceki window_minutes dakikayla karşılaştırır.

    Returns:
        {
            "trend":          "OK" | "WARNING" | "CRITICAL" | "SURGE" | "NO_DATA",
            "current_count":  int,   # son X dakikadaki satış sayısı
            "previous_count": int,   # önceki X dakikadaki satış sayısı
            "change_pct":     float, # % değişim (negatif = düşüş)
            "message":        str,   # açıklama
        }
    """
    now      = datetime.now(timezone.utc)
    t_now    = now.isoformat()
    t_mid    = (now - timedelta(minutes=window_minutes)).isoformat()
    t_start  = (now - timedelta(minutes=window_minutes * 2)).isoformat()

    # Son window
    r_current = _table.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id)
            & Key("timestamp").between(t_mid, t_now)
        ),
    )
    current_count = len(r_current.get("Items", []))

    # Önceki window
    r_previous = _table.query(
        IndexName="product_id-timestamp-index",
        KeyConditionExpression=(
            Key("product_id").eq(product_id)
            & Key("timestamp").between(t_start, t_mid)
        ),
    )
    previous_count = len(r_previous.get("Items", []))

    # Hiç veri yoksa
    if previous_count == 0 and current_count == 0:
        return {
            "trend": "NO_DATA",
            "current_count": 0,
            "previous_count": 0,
            "change_pct": 0.0,
            "message": f"No sales data in last {window_minutes * 2} minutes.",
        }

    # % değişim hesapla
    if previous_count == 0:
        change_pct = 100.0  # önceden hiç yoktu, şimdi var → SURGE
    else:
        change_pct = ((current_count - previous_count) / previous_count) * 100

    # Trend kategorisi
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
