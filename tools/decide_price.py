"""
decide_price — Makes the pricing decision with the math done correctly in Python.

What it does:
  - Fetches the product + competitor prices itself, then computes the target
    price for the given mode (crisis / recovery / bundle).
  - Enforces the min_price floor and base_price ceiling on every path.

Why it exists / how it fits:
  Nova Lite makes numeric comparison errors, so ALL price math lives here, not
  in the model. The model NEVER passes competitor prices — the tool reads them
  straight from DynamoDB, which removes the model's value-passing errors.
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
    Fetches competitor prices itself and makes the pricing decision.

    Args:
        product_id:         Product ID
        mode:               "crisis"   → should we drop the price?
                            "recovery" → should we raise the price?
                            "bundle"   → proactive accessory discount when the
                                         parent phone is surging.
        traffic_ratio:      Traffic ratio from get_time_context (optional).
        preferred_drop_pct: Optimal discount % from analyze_price_elasticity
                            (optional, negative). When given, an elasticity-based
                            target price is computed instead of plain competitor
                            matching. The min_price floor applies in either case.

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
            "elasticity_target":   float | None,  # target derived from preferred_drop_pct
            "context_note":        str,
            "reason":              str,
        }
    """
    # Fetch product details
    product = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": product_id}).get("Item", {})

    P = float(product.get("current_price", 0))
    M = float(product.get("min_price", 0))
    B = float(product.get("base_price", P))

    # Fetch competitor prices
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

    # Compute the elasticity-based target price (if provided)
    elasticity_target = None
    if preferred_drop_pct is not None and P > 0:
        elasticity_target = round(P * (1 + preferred_drop_pct / 100), 2)
        elasticity_target = max(elasticity_target, M)  # min_price floor

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

    # Bundle mode: parent phone is surging → proactive accessory discount
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
            # Target: take the lower of elasticity and competitor, but never below min_price
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
