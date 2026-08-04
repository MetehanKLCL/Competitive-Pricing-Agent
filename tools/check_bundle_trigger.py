"""
check_bundle_trigger — Checks the parent phone's sales on behalf of an accessory.

Logic:
  - Every accessory has a parent phone (e.g. PROD-002 → PROD-001)
  - If the parent phone is in SURGE → there is a bundle opportunity for the accessory
  - With this signal the agent can proactively discount the accessory

Why it exists / how it fits:
  Implements the ONE-DIRECTION bundle rule (phone surge → accessory discount) and
  runs the epsilon-greedy learner that picks the discount rate — the reinforcement
  learning piece of the pipeline.
"""

import os
import random
import boto3
from datetime import datetime, timezone
from dotenv import load_dotenv

BUNDLE_RATES       = [5, 7, 9, 11]   # discount rates to try (%)
EXPLORATION_PROB   = 0.30             # 30% explore, 70% use the best known rate
MIN_BUNDLE_SAMPLES = 3               # a rate must have been tried at least this many
                                     # times before we "exploit" it (confidence gate) —
                                     # so a single lucky sample isn't crowned the best

load_dotenv()

AWS_REGION     = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def check_bundle_trigger(product_id: str) -> dict:
    """
    If this product is an accessory, looks at its parent phone's sales status.
    Returns a bundle opportunity if the parent phone is in SURGE.

    Args:
        product_id: Accessory product ID (PROD-002, PROD-004)

    Returns:
        {
            "is_accessory":       bool,
            "parent_product_id":  str | None,
            "parent_name":        str | None,
            "bundle_opportunity": bool,
            "parent_sales_30min": int,
            "parent_sales_prev":  int,
            "surge_ratio":        float | None,
            "recommendation":     str,
        }
    """
    product = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": product_id}).get("Item", {})

    parent_id = product.get("bundle_parent")

    if not parent_id:
        return {
            "is_accessory":       False,
            "parent_product_id":  None,
            "parent_name":        None,
            "bundle_opportunity": False,
            "parent_sales_30min": 0,
            "parent_sales_prev":  0,
            "surge_ratio":        None,
            "recommendation":     "This product has no bundle parent — standard pricing rules apply.",
        }

    # Parent phone details
    parent = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": parent_id}).get("Item", {})
    parent_name = parent.get("name", parent_id)

    # Learn whether the parent phone is in SURGE from a SINGLE SOURCE: check_sales_trend.
    # This used to have its own 30/30-min count + a loose 1.5x threshold, which
    # conflicted with check_sales_trend's 2x definition. Now "what is a surge" is
    # defined in one place in the system — the min-volume guard (MIN_SURGE_COUNT)
    # is inherited automatically too.
    from .check_sales_trend import check_sales_trend
    parent_trend = check_sales_trend(parent_id, window_minutes=30)

    recent      = parent_trend["current_count"]
    prev        = parent_trend["previous_count"]
    is_surge    = parent_trend["trend"] == "SURGE"
    surge_ratio = round(recent / prev, 2) if prev > 0 else None

    # Epsilon-greedy discount selection
    selected_discount, strategy = _pick_bundle_discount(product_id)

    if is_surge:
        rec = (f"{parent_name} surging ({recent} sales vs {prev} prev). "
               f"Apply {selected_discount}% bundle discount ({strategy}).")
    elif recent > 0:
        rec = f"{parent_name} has {recent} sales. No strong bundle signal."
    else:
        rec = f"{parent_name} has no recent sales. No bundle opportunity."

    return {
        "is_accessory":        True,
        "parent_product_id":   parent_id,
        "parent_name":         parent_name,
        "bundle_opportunity":  is_surge,
        "parent_sales_30min":  recent,
        "parent_sales_prev":   prev,
        "surge_ratio":         surge_ratio,
        "selected_discount_pct": selected_discount,
        "discount_strategy":   strategy,
        "recommendation":      rec,
    }


def _pick_bundle_discount(product_id: str) -> tuple:
    """
    Learns the optimal rate from past bundle discounts.
    If there isn't enough data, or in exploration mode, it tries a random rate.

    Returns: (discount_pct, strategy) — strategy: "exploit" | "explore" | "random"
    """
    from .run_analytics import run_analytics

    # date = today filter — Hive partition pruning:
    #   Bronze re-scans FULL history every day (not incremental), so the latest
    #   partition (today) already contains all history. Without the filter, Athena
    #   scanned EVERY day in the partition projection range (2026-01-01,NOW) —
    #   needless S3 cost.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # STRUCTURED FIELD (NOT REGEXP): the rate is now read from Silver's typed
    # bundle_discount_pct column — since it is written at the source (log_action),
    # there is no need to parse the reason text. Revenue also comes from Silver's
    # ready-made `revenue` field (same pattern as analyze_price_elasticity).
    # Reward = revenue, not unit count.
    # n_pulls = how many times that rate was applied → for the confidence gate.
    # bundle_discount_pct IS NOT NULL → old records without the field are ignored.
    sql = f"""
    SELECT
        pa.bundle_discount_pct AS rate,
        COUNT(DISTINCT pa.log_id) AS n_pulls,
        COALESCE(SUM(s.revenue), 0) AS revenue_after
    FROM heweso_analytics.silver_price_actions pa
    LEFT JOIN heweso_analytics.silver_sales_enriched s
        ON s.product_id = '{product_id}'
        AND s.date = '{today}'
        AND s.timestamp >= pa.timestamp
        AND s.timestamp <= date_add('minute', 60, from_iso8601_timestamp(pa.timestamp))
    WHERE pa.product_id = '{product_id}'
        AND pa.bundle_discount_pct IS NOT NULL
        AND pa.date = '{today}'
    GROUP BY pa.bundle_discount_pct
    ORDER BY revenue_after DESC
    LIMIT 1
    """

    try:
        result = run_analytics(sql, max_rows=5)
        if result["success"] and result["rows"]:
            best_rate = float(result["rows"][0][0])
            n_pulls   = int(float(result["rows"][0][1]))
            # Confidence gate: only "exploit" the best rate if it has been tried
            # enough (n_pulls >= MIN). Otherwise don't trust a single lucky sample
            # and keep exploring.
            if n_pulls >= MIN_BUNDLE_SAMPLES:
                if random.random() > EXPLORATION_PROB:
                    return best_rate, "exploit"
                others = [r for r in BUNDLE_RATES if r != best_rate]
                return random.choice(others), "explore"
    except Exception:
        pass

    return random.choice(BUNDLE_RATES), "random"


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003", "PROD-004"]:
        r = check_bundle_trigger(pid)
        print(f"\n{pid}: accessory={r['is_accessory']} | opportunity={r['bundle_opportunity']}")
        print(f"  {r['recommendation'][:100]}")
