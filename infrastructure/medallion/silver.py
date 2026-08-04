"""
silver.py — Bronze → Silver transformation.

Medallion Architecture — Silver layer:
  Cleaned, joined data with derived fields added.
  Reads from Bronze, writes to Silver.

Tables produced:
  silver/sales_enriched/     — Sales + Product join, revenue computed
  silver/price_actions/      — Price changes from the audit log, enriched
  silver/competitor_gaps/    — Competitor prices vs our prices, gap computed

Why it exists / how it fits:
  This is the Python Silver stage of the live pipeline (the dbt project rebuilds
  the same tables in SQL, in an isolated schema). Agent tools query Silver for
  elasticity, time context and bundle signals.
"""

import json
import os
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
BUCKET = "heweso-data-lake"

s3 = boto3.client("s3", region_name=AWS_REGION)
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Helper functions ──────────────────────────────────────────────────────────

def _read_bronze(table: str, date: str) -> list:
    """Reads NDJSON from the Bronze layer."""
    key = f"bronze/{table}/date={date}/data.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        lines = response["Body"].read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]
    except s3.exceptions.NoSuchKey:
        print(f"  ⚠️  Bronze not found: {key} (export may not have run yet)")
        return []
    except Exception as e:
        print(f"  ❌ Bronze read error ({key}): {e}")
        return []


def _write_silver(table: str, records: list, date: str):
    """Writes NDJSON to the Silver layer."""
    key = f"silver/{table}/date={date}/data.json"
    body = "\n".join(json.dumps(r, default=str) for r in records)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"  ✅ {len(records)} rows → s3://{BUCKET}/{key}")


def _parse_ts(ts: str, fallback_date: str):
    """Parses an ISO timestamp; returns the fallback on error."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.hour
    except Exception:
        return fallback_date, 0


def _is_price_action(action: dict) -> bool:
    """Checks whether an audit log record is a price change."""
    keywords = ["price", "discount", "bundle", "recovery", "crisis"]
    return any(kw in str(action.get("action", "")).lower() for kw in keywords)


# ── Silver transformations ────────────────────────────────────────────────────

def transform_sales_enriched(date: str) -> int:
    """
    silver_sales_enriched: sales data + product info.

    Bronze sales only holds product_id. We join product_id → name, category and
    compute revenue (revenue = quantity × price_at_sale).

    Why it matters: in the Gold layer we can answer "how much revenue did the
    iPhone 17 Pro produce today?" directly — no need to join every time.
    """
    sales    = _read_bronze("sales", date)
    products = _read_bronze("products", date)

    product_map = {p["product_id"]: p for p in products}

    enriched = []
    for sale in sales:
        product   = product_map.get(sale.get("product_id"), {})
        sale_date, sale_hour = _parse_ts(sale.get("timestamp", ""), date)
        qty       = float(sale.get("quantity", 1))
        price     = float(sale.get("price_at_sale", 0))

        enriched.append({
            "sale_id":      sale.get("sale_id"),
            "timestamp":    sale.get("timestamp"),
            "sale_date":    sale_date,
            "sale_hour":    sale_hour,
            "product_id":   sale.get("product_id"),
            "product_name": product.get("name", "Unknown"),
            "category":     product.get("category", "unknown"),
            "quantity":     qty,
            "price_at_sale": price,
            "revenue":      round(qty * price, 2),   # derived field
            "customer_id":  sale.get("customer_id"),
        })

    _write_silver("sales_enriched", enriched, date)
    return len(enriched)


def transform_price_actions(date: str) -> int:
    """
    silver_price_actions: enriches price changes.

    The audit log holds everything: escalations, skips, price changes, etc.
    We filter to just the price changes and compute price_change_pct and direction.

    direction: DOWN (discount), UP (recovery), SAME
    price_change_pct: -9.1 (a 9.1% discount was applied)
    """
    audit    = _read_bronze("audit", date)
    products = _read_bronze("products", date)

    product_map   = {p["product_id"]: p for p in products}
    price_actions = [
        a for a in audit
        if _is_price_action(a) and a.get("product_id") in product_map
    ]

    enriched = []
    for action in price_actions:
        product     = product_map.get(action.get("product_id"), {})
        action_date, action_hour = _parse_ts(action.get("timestamp", ""), date)

        try:
            old_price  = float(action.get("old_value", 0))
            new_price  = float(action.get("new_value", 0))
            change_pct = round((new_price - old_price) / old_price * 100, 2) if old_price > 0 else 0.0
            direction  = "DOWN" if new_price < old_price else "UP" if new_price > old_price else "SAME"
        except (TypeError, ValueError):
            old_price, new_price, change_pct, direction = 0.0, 0.0, 0.0, "UNKNOWN"

        enriched.append({
            "log_id":         action.get("log_id"),
            "timestamp":      action.get("timestamp"),
            "action_date":    action_date,
            "action_hour":    action_hour,
            "product_id":     action.get("product_id"),
            "product_name":   product.get("name", "Unknown"),
            "category":       product.get("category", "unknown"),
            "action":         action.get("action"),
            "old_price":      old_price,
            "new_price":      new_price,
            "price_change_pct": change_pct,   # derived field
            "direction":      direction,        # derived field
            # Structured field: bundle discount rate. Written at the source
            # (log_action), so there's no need to scrape it from the reason text
            # with REGEXP. Absent on non-bundle / old records → None (the learner
            # ignores NULLs).
            "bundle_discount_pct": (
                float(action["bundle_discount_pct"])
                if action.get("bundle_discount_pct") is not None else None
            ),
            "reason":         action.get("reason", ""),
            "agent_decision": action.get("agent_decision", ""),
        })

    _write_silver("price_actions", enriched, date)
    return len(enriched)


def transform_competitor_gaps(date: str) -> int:
    """
    silver_competitor_gaps: competitor prices vs our prices.

    Computes the price gap for each competitor-product pair.
    gap_pct: positive = we are more expensive, negative = we are cheaper.
    we_are_cheaper: are we cheaper than the competitor?

    Why it matters: "on how many products are we more expensive than competitors?"
    becomes answerable in a single SQL query.
    """
    competitors = _read_bronze("competitors", date)
    products    = _read_bronze("products", date)

    product_map = {p["product_id"]: p for p in products}

    enriched = []
    for comp in competitors:
        product    = product_map.get(comp.get("product_id"), {})
        our_price  = float(product.get("current_price", 0))
        comp_price = float(comp.get("price", 0))

        if our_price > 0 and comp_price > 0:
            gap     = round(our_price - comp_price, 2)
            gap_pct = round((our_price - comp_price) / comp_price * 100, 2)
        else:
            gap, gap_pct = 0.0, 0.0

        enriched.append({
            "product_id":       comp.get("product_id"),
            "product_name":     product.get("name", "Unknown"),
            "category":         product.get("category", "unknown"),
            "competitor":       comp.get("competitor_name"),
            "our_price":        our_price,
            "competitor_price": comp_price,
            "price_gap":        gap,           # derived: positive = we are more expensive
            "gap_pct":          gap_pct,       # derived: percentage gap
            "we_are_cheaper":   our_price < comp_price,
            "undercut_since":   comp.get("undercut_since"),
            "last_checked":     comp.get("last_checked"),
            "snapshot_date":    date,
        })

    _write_silver("competitor_gaps", enriched, date)
    return len(enriched)


# ── Main function ─────────────────────────────────────────────────────────────

def run_silver(date: str = None) -> int:
    date = date or today
    print(f"\n=== Bronze → Silver Transform ({date}) ===")
    n1 = transform_sales_enriched(date)
    n2 = transform_price_actions(date)
    n3 = transform_competitor_gaps(date)
    total = n1 + n2 + n3
    print(f"\n✅ Silver complete — {total} total rows written")
    return total


if __name__ == "__main__":
    run_silver()
