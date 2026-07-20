"""
decide_price — Fiyat kararını matematiği doğru yaparak verir.

Model rakip fiyatı GEÇMEZ — tool direkt DynamoDB'den çeker.
Bu sayede modelin değer aktarım hatası ortadan kalkar.
"""

import os
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION        = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE    = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def decide_price(product_id: str, mode: str, traffic_ratio: float = None, preferred_drop_pct: float = None, bundle_discount_pct: float = None) -> dict:
    """
    Rakip fiyatlarını kendisi çekip fiyat kararını verir.

    Args:
        product_id:         Ürün ID
        mode:               "crisis"   → fiyat düşür mü?
                            "recovery" → fiyat artır mı?
        traffic_ratio:      get_time_context'ten gelen trafik oranı (opsiyonel).
        preferred_drop_pct: analyze_price_elasticity'den gelen optimal indirim % (opsiyonel, negatif).
                            Verilirse rakip eşitleme yerine elastiklik bazlı hedef fiyat hesaplanır.
                            Her iki durumda da min_price koruması devreye girer.

    Returns:
        {
            "action":              "UPDATE" | "NO_ACTION",
            "new_price":           float | None,
            "cheapest_competitor": float,
            "current_price":       float,
            "min_price":           float,
            "base_price":          float,
            "competitor_gap_pct":  float | None,
            "traffic_ratio":       float | None,
            "elasticity_target":   float | None,  # preferred_drop_pct'den hesaplanan hedef
            "context_note":        str,
            "reason":              str,
        }
    """
    # Ürün bilgilerini çek
    product = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": product_id}).get("Item", {})

    P = float(product.get("current_price", 0))
    M = float(product.get("min_price", 0))
    B = float(product.get("base_price", P))

    # Rakip fiyatlarını çek
    comps = _dynamodb.Table(COMPETITORS_TABLE) \
        .query(KeyConditionExpression=Key("product_id").eq(product_id)) \
        .get("Items", [])

    if not comps:
        return {
            "action": "NO_ACTION", "new_price": None,
            "cheapest_competitor": None, "current_price": P,
            "min_price": M, "base_price": B,
            "reason": "No competitor data available.",
        }

    C = float(min(comps, key=lambda x: float(x["price"]))["price"])

    gap_pct = round((C - P) / P * 100, 2) if P > 0 else None

    # Elastiklik bazlı hedef fiyat hesapla (varsa)
    elasticity_target = None
    if preferred_drop_pct is not None and P > 0:
        elasticity_target = round(P * (1 + preferred_drop_pct / 100), 2)
        elasticity_target = max(elasticity_target, M)  # min_price koruması

    context_note_parts = []
    if gap_pct is not None:
        context_note_parts.append(
            f"Competitor is {abs(gap_pct):.1f}% {'cheaper' if gap_pct < 0 else 'more expensive'} than us."
        )
    if traffic_ratio is not None:
        context_note_parts.append(f"Traffic is {traffic_ratio}x hourly average.")
    if elasticity_target is not None:
        context_note_parts.append(
            f"Elasticity suggests target price {elasticity_target} ({abs(preferred_drop_pct):.1f}% drop from current)."
        )
    context_note_parts.append(f"Math: current={P}, competitor={C}, min={M}, base={B}.")
    context_note = " ".join(context_note_parts)

    # Bundle modu: parent telefon SURGE'de, aksesuar proaktif indirim
    if mode == "bundle":
        if bundle_discount_pct is None:
            bundle_discount_pct = 7.0
    if mode == "bundle" and bundle_discount_pct is not None:
        target = round(float(P) * (1 - bundle_discount_pct / 100), 2)
        target = max(target, float(M))
        if target < float(P):
            return {
                "action": "UPDATE", "new_price": target,
                "cheapest_competitor": C, "current_price": P,
                "min_price": M, "base_price": B,
                "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
                "elasticity_target": elasticity_target,
                "context_note": context_note,
                "reason": f"Bundle discount {bundle_discount_pct}%: {P} → {target} (parent phone is surging).",
            }
        return {
            "action": "NO_ACTION", "new_price": None,
            "cheapest_competitor": C, "current_price": P,
            "min_price": M, "base_price": B,
            "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
            "elasticity_target": elasticity_target,
            "context_note": context_note,
            "reason": f"Bundle discount would hit min_price floor — no action.",
        }

    if mode == "crisis":
        if C < M and (elasticity_target is None or elasticity_target < M):
            return {
                "action": "NO_ACTION", "new_price": None,
                "cheapest_competitor": C, "current_price": P,
                "min_price": M, "base_price": B,
                "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
                "elasticity_target": elasticity_target,
                "context_note": context_note,
                "reason": f"Competitor ({C}) < min_price ({M}). Cannot match — floor protection.",
            }
        if C < P or (elasticity_target is not None and elasticity_target < P):
            # Hedef: elastiklik ve rakip arasından en düşüğü al, ama min_price'ın altına inme
            if elasticity_target is not None:
                target = max(min(C, elasticity_target), M)
                reason_detail = (
                    f"Elasticity target ({elasticity_target}) vs competitor ({C}) → chose {target}."
                )
            else:
                target = max(C, M)
                reason_detail = f"Matching competitor ({C})."
            return {
                "action": "UPDATE", "new_price": target,
                "cheapest_competitor": C, "current_price": P,
                "min_price": M, "base_price": B,
                "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
                "elasticity_target": elasticity_target,
                "context_note": context_note,
                "reason": reason_detail,
            }
        return {
            "action": "NO_ACTION", "new_price": None,
            "cheapest_competitor": C, "current_price": P,
            "min_price": M, "base_price": B,
            "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
            "elasticity_target": elasticity_target,
            "context_note": context_note,
            "reason": f"Already competitive — competitor ({C}) >= current ({P}).",
        }

    elif mode == "recovery":
        target = min(C, B)
        if target > P:
            return {
                "action": "UPDATE", "new_price": target,
                "cheapest_competitor": C, "current_price": P,
                "min_price": M, "base_price": B,
                "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
                "elasticity_target": elasticity_target,
                "context_note": context_note,
                "reason": f"Sales recovered. Raising {P} → {target} (min of competitor {C} and base {B}).",
            }
        return {
            "action": "NO_ACTION", "new_price": None,
            "cheapest_competitor": C, "current_price": P,
            "min_price": M, "base_price": B,
            "competitor_gap_pct": gap_pct, "traffic_ratio": traffic_ratio,
            "elasticity_target": elasticity_target,
            "context_note": context_note,
            "reason": f"Recovery: competitor ({C}) not above current ({P}). No raise.",
        }

    return {
        "action": "NO_ACTION", "new_price": None,
        "cheapest_competitor": None, "current_price": P,
        "min_price": M, "base_price": B,
        "competitor_gap_pct": None, "traffic_ratio": traffic_ratio,
        "elasticity_target": elasticity_target,
        "context_note": context_note,
        "reason": f"Unknown mode: {mode}",
    }


if __name__ == "__main__":
    from infrastructure.dynamodb_setup import seed_all
    seed_all(crisis_mode=True)
    print("PROD-001 crisis:", decide_price("PROD-001", "crisis"))
    print("PROD-002 crisis:", decide_price("PROD-002", "crisis"))
    print("PROD-003 crisis:", decide_price("PROD-003", "crisis"))
