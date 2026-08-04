"""
gold.py — Silver → Gold aggregation.

Medallion Architecture — Gold layer:
  Pre-computed, aggregated data organized around business questions.
  Reads from Silver, writes to Gold.
  Athena doesn't have to do heavy computation when querying these tables.

Tables produced:
  gold/daily_product_metrics/  — DAILY sales + price summary per product
  gold/agent_performance/      — The agent's DAILY decision quality
  gold/bundle_effectiveness/   — Outcomes of bundle discounts

═══════════════════════════════════════════════════════════════════════════════
EVENT-DATE PARTITIONING (why GROUP BY sale_date/action_date?)
───────────────────────────────────────────────────────────────────────────────
export_to_s3.py does a FULL scan of DynamoDB every run. So the "today" partition
(date=TODAY) holds not just today's sales but ALL historical sales — like
photocopying the entire diary from scratch each night and dropping it in the
"today" folder.

That's why grouping Gold by the snapshot date (the partition name) is WRONG: a
"date=TODAY" Gold row would give the sum of ALL time, not that day's, and summing
7 days would count old sales over and over (double-count).

The CORRECT way: look at each Silver row's OWN real event date (sale_date for
sales, action_date for price_actions — both ready in Silver), group by that, and
write to the partition of that event date. This way every sale is counted EXACTLY
once and the weekly report can read Gold directly instead of Silver. Full-refresh
but idempotent: the same run rewrites every event-date partition from scratch.
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
BUCKET = "heweso-data-lake"

s3 = boto3.client("s3", region_name=AWS_REGION)
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Helper functions ──────────────────────────────────────────────────────────

def _read_silver(table: str, date: str) -> list:
    """Reads NDJSON from the Silver layer."""
    key = f"silver/{table}/date={date}/data.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        lines = response["Body"].read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]
    except s3.exceptions.NoSuchKey:
        print(f"  ⚠️  Silver not found: {key} (run silver.py first)")
        return []
    except Exception as e:
        print(f"  ❌ Silver read error ({key}): {e}")
        return []


def _write_gold(table: str, records: list, date: str):
    """Writes NDJSON to the Gold layer (into the given event date's partition)."""
    key = f"gold/{table}/date={date}/data.json"
    body = "\n".join(json.dumps(r, default=str) for r in records)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"  ✅ {len(records)} rows → s3://{BUCKET}/{key}")


def _write_gold_by_event_date(table: str, records_by_date: dict) -> int:
    """
    records_by_date: {event_date: [record, ...]} — writes each event date into its
    OWN partition. Full-refresh: each partition is rewritten from scratch (idempotent).
    """
    total = 0
    for event_date in sorted(records_by_date):
        records = records_by_date[event_date]
        _write_gold(table, records, event_date)
        total += len(records)
    return total


# ── Gold aggregations ─────────────────────────────────────────────────────────

def build_daily_product_metrics(snapshot_date: str) -> int:
    """
    gold_daily_product_metrics: DAILY summary per product.

    Question: "on July 8, how many units did each product sell, how much revenue
               did it produce, how many times did its price change?"

    Grouping key is (event_date, product_id) — not the snapshot, but the row's OWN
    date (sales → sale_date, price_actions → action_date). This makes Gold truly
    daily.
    """
    sales         = _read_silver("sales_enriched", snapshot_date)
    price_actions = _read_silver("price_actions", snapshot_date)

    # Sales aggregate: sum by (event date, product)
    sales_agg = defaultdict(lambda: {
        "total_sales": 0, "total_revenue": 0.0, "prices": [],
        "product_name": "", "category": "",
    })
    for sale in sales:
        event_date = sale.get("sale_date") or snapshot_date
        pid        = sale["product_id"]
        key        = (event_date, pid)
        sales_agg[key]["total_sales"]   += int(sale.get("quantity", 1))
        sales_agg[key]["total_revenue"] += float(sale.get("revenue", 0))
        sales_agg[key]["prices"].append(float(sale.get("price_at_sale", 0)))
        sales_agg[key]["product_name"]   = sale.get("product_name", "")
        sales_agg[key]["category"]       = sale.get("category", "")

    # Price change counts: by (event date, product)
    price_agg = defaultdict(lambda: {"drops": 0, "recoveries": 0, "total": 0})
    for action in price_actions:
        event_date = action.get("action_date") or snapshot_date
        pid        = action["product_id"]
        key        = (event_date, pid)
        price_agg[key]["total"] += 1
        if action.get("direction") == "DOWN":
            price_agg[key]["drops"] += 1
        elif action.get("direction") == "UP":
            price_agg[key]["recoveries"] += 1

    # Union all (date, product) keys, then group by event date
    all_keys = set(sales_agg.keys()) | set(price_agg.keys())
    by_date  = defaultdict(list)
    for key in all_keys:
        event_date, pid = key
        s  = sales_agg[key]
        pc = price_agg[key]
        prices = s["prices"]
        by_date[event_date].append({
            "date":              event_date,
            "product_id":        pid,
            "product_name":      s["product_name"],
            "category":          s["category"],
            "total_sales":       s["total_sales"],
            "total_revenue":     round(s["total_revenue"], 2),
            "avg_price":         round(sum(prices) / len(prices), 2) if prices else 0.0,
            "min_price":         min(prices) if prices else 0.0,
            "max_price":         max(prices) if prices else 0.0,
            "price_changes":     pc["total"],
            "price_drops":       pc["drops"],
            "price_recoveries":  pc["recoveries"],
        })

    return _write_gold_by_event_date("daily_product_metrics", by_date)


def build_agent_performance(snapshot_date: str) -> int:
    """
    gold_agent_performance: the agent's DAILY decision summary.

    Question: "on July 8, how many discount decisions did it make for PROD-002?
               What was the average discount %? How many bundles did it apply?"

    Grouping key is (action_date, product_id). This table is strong in a portfolio
    demo — you can now show whether the agent is learning as a REAL time series
    (each day in its own partition).
    """
    price_actions = _read_silver("price_actions", snapshot_date)

    perf = defaultdict(lambda: {
        "total_decisions": 0, "price_drops": 0, "price_recoveries": 0,
        "bundle_discounts": 0, "escalations": 0, "drop_pcts": [],
        "product_name": "", "category": "",
    })

    for action in price_actions:
        event_date = action.get("action_date") or snapshot_date
        pid        = action["product_id"]
        key        = (event_date, pid)
        perf[key]["product_name"] = action.get("product_name", "")
        perf[key]["category"]     = action.get("category", "")
        perf[key]["total_decisions"] += 1

        direction = action.get("direction", "")
        if direction == "DOWN":
            perf[key]["price_drops"] += 1
            pct = abs(float(action.get("price_change_pct", 0)))
            if pct > 0:
                perf[key]["drop_pcts"].append(pct)
        elif direction == "UP":
            perf[key]["price_recoveries"] += 1

        action_type = str(action.get("action", "")).lower()
        if "bundle" in action_type:
            perf[key]["bundle_discounts"] += 1
        if "escalat" in action_type:
            perf[key]["escalations"] += 1

    by_date = defaultdict(list)
    for key, p in perf.items():
        event_date, pid = key
        drops = p["drop_pcts"]
        by_date[event_date].append({
            "date":             event_date,
            "product_id":       pid,
            "product_name":     p["product_name"],
            "category":         p["category"],
            "total_decisions":  p["total_decisions"],
            "price_drops":      p["price_drops"],
            "price_recoveries": p["price_recoveries"],
            "bundle_discounts": p["bundle_discounts"],
            "escalations":      p["escalations"],
            "avg_drop_pct":     round(sum(drops) / len(drops), 2) if drops else 0.0,
        })

    return _write_gold_by_event_date("agent_performance", by_date)


def build_bundle_effectiveness(snapshot_date: str) -> int:
    """
    gold_bundle_effectiveness: the sales impact of bundle discounts.

    Question: "on July 8, how many times was a bundle discount applied to the
               AirPods Pro 3? What was the average discount %? How many units sold
               that day?"

    Grouping key is (action_date, product_id). Can be used to visualize the results
    of epsilon-greedy learning day by day.
    HIGH = 3+ sales/day, MEDIUM = 1-2, LOW = 0.
    """
    price_actions = _read_silver("price_actions", snapshot_date)
    sales         = _read_silver("sales_enriched", snapshot_date)

    bundle_actions = [a for a in price_actions if "bundle" in str(a.get("action", "")).lower()]

    # (event date, product) → that day's total sales for that product
    sales_by_key = defaultdict(int)
    for sale in sales:
        event_date = sale.get("sale_date") or snapshot_date
        sales_by_key[(event_date, sale["product_id"])] += int(sale.get("quantity", 1))

    # (event date, product) → bundle actions applied to that product that day
    bundles_by_key = defaultdict(list)
    for action in bundle_actions:
        event_date = action.get("action_date") or snapshot_date
        bundles_by_key[(event_date, action["product_id"])].append(action)

    by_date = defaultdict(list)
    for key, product_bundles in bundles_by_key.items():
        event_date, pid = key
        discount_pcts = [abs(float(b.get("price_change_pct", 0))) for b in product_bundles
                         if float(b.get("price_change_pct", 0)) != 0]
        sales_count  = sales_by_key.get(key, 0)
        avg_discount = round(sum(discount_pcts) / len(discount_pcts), 2) if discount_pcts else 0.0

        by_date[event_date].append({
            "date":                 event_date,
            "product_id":           pid,
            "product_name":         product_bundles[0].get("product_name", ""),
            "bundle_triggers":      len(product_bundles),
            "avg_discount_pct":     avg_discount,
            "sales_after_discount": sales_count,
            "effectiveness":        "HIGH" if sales_count >= 3 else "MEDIUM" if sales_count >= 1 else "LOW",
        })

    return _write_gold_by_event_date("bundle_effectiveness", by_date)


# ── Main function ─────────────────────────────────────────────────────────────

def run_gold(snapshot_date: str = None) -> int:
    """
    snapshot_date: which Silver partition to read (default today).
    Output: each table is written to partitions by the rows' OWN event date.
    """
    snapshot_date = snapshot_date or today
    print(f"\n=== Silver → Gold Aggregate (snapshot read: {snapshot_date}, writing by event date) ===")
    n1 = build_daily_product_metrics(snapshot_date)
    n2 = build_agent_performance(snapshot_date)
    n3 = build_bundle_effectiveness(snapshot_date)
    total = n1 + n2 + n3
    print(f"\n✅ Gold complete — {total} total rows written")
    return total


if __name__ == "__main__":
    run_gold()
