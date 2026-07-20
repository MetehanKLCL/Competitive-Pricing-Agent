"""
check_competitor_pattern — Rakibin fiyat düşüşünün flash sale mi
yoksa kalıcı bir değişim mi olduğunu tespit eder.

Yöntem:
  CompetitorPrices tablosundaki undercut_since alanına bakar.
  Bu alan, rakip fiyatı bizim fiyatımızın altına düştüğünde set edilir.
  undercut_since ne kadar eskiyse, değişim o kadar kalıcı demektir.

Karar:
  < 60 dakika  → FLASH_SALE  (bekle, tepki verme)
  60-180 dk    → MONITOR     (dikkat et, henüz net değil)
  > 180 dakika → STRUCTURAL  (kalıcı değişim, harekete geç)
  undercut_since yok → NOT_UNDERCUT (rakip bizden pahalı/eşit)
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

    # Bizim fiyatımız
    product = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": product_id}).get("Item", {})
    our_price = float(product.get("current_price", 0))

    # Rakip fiyatları
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

    # Bayat kronometre temizliği: artık bizden ucuz OLMAYAN her rakibin
    # undercut_since'ını sıfırla. Yoksa bir rakip ucuzlayıp (damga yazılır)
    # sonra tekrar pahalılaşınca damga kalır; ileride yeniden ucuzladığında
    # eski damga yüzünden yanlışlıkla STRUCTURAL sayılır ve flash-sale koruması çöker.
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

    # Ne zaman ucuzladı?
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
    """Rakip tekrar pahalılaşınca undercut_since sıfırlanır."""
    _dynamodb.Table(COMPETITORS_TABLE).update_item(
        Key={"product_id": product_id, "competitor_name": competitor_name},
        UpdateExpression="REMOVE undercut_since",
    )


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = check_competitor_pattern(pid)
        print(f"{pid}: {r['pattern']} | {r['recommendation']}")
