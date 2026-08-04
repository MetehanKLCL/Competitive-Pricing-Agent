"""
api.py — Heweso Dashboard FastAPI backend.

What it does:
  - Serves REST endpoints the dashboard reads (products, sales, stats, trend,
    price history, audit, competitors, analytics).
  - Runs the demo simulation workers (sales + competitor price random walk) and
    triggers the Bedrock agent, streaming its ReAct events to the UI over SSE.

Why it exists / how it fits:
  This is the local demo/visualization layer only — it wraps the same tools and
  agent used in production so the pricing behavior can be watched live in a browser.
"""

import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")
SALES_TABLE = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")
AUDIT_TABLE = os.getenv("DYNAMODB_AUDIT_TABLE", "heweso-audit-log")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

app = FastAPI(title="Heweso Dashboard")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_agent_logs: dict[str, list] = {}

_sim_thread = None
_sim_stop = threading.Event()
_latest_sale_ts = ""


# ── Products ─────────────────────────────────────────────────────────────────

@app.get("/api/products")
def get_products():
    table = dynamodb.Table(PRODUCTS_TABLE)
    items = table.scan()["Items"]
    return [
        {
            "product_id": i["product_id"],
            "name": i["name"],
            "current_price": float(i["current_price"]),
            "min_price": float(i["min_price"]),
            "category": i.get("category", ""),
            "updated_at": i.get("updated_at", ""),
        }
        for i in sorted(items, key=lambda x: x["product_id"])
    ]


# ── Sales Trend ──────────────────────────────────────────────────────────────

@app.get("/api/trend/{product_id}")
def get_trend(product_id: str):
    from tools.check_sales_trend import check_sales_trend
    return check_sales_trend(product_id)


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(product_id: str = "PROD-001"):
    sales_table = dynamodb.Table(SALES_TABLE)
    products_table = dynamodb.Table(PRODUCTS_TABLE)

    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    cutoff_60 = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()

    all_sales = sales_table.scan()["Items"]
    today_sales = [s for s in all_sales if s["timestamp"] >= today_start]
    today_revenue = sum(
        float(s["price_at_sale"]) * int(s["quantity"]) for s in today_sales
    )
    recent_sales = [s for s in all_sales if s["timestamp"] >= cutoff_60]
    last_sale = max((s["timestamp"] for s in all_sales), default=None)

    product = products_table.get_item(Key={"product_id": product_id}).get("Item", {})

    return {
        "today_revenue": round(today_revenue, 2),
        "today_orders": len(today_sales),
        "current_price": float(product.get("current_price", 0)),
        "product_name": product.get("name", product_id),
        "sales_health": "healthy" if recent_sales else "critical",
        "last_sale": last_sale,
    }


# ── Sales ─────────────────────────────────────────────────────────────────────

@app.get("/api/sales")
def get_sales(limit: int = 50):
    table = dynamodb.Table(SALES_TABLE)
    items = table.scan()["Items"]
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return [
        {
            "sale_id": i["sale_id"],
            "product_id": i["product_id"],
            "quantity": int(i["quantity"]),
            "price_at_sale": float(i["price_at_sale"]),
            "timestamp": i["timestamp"],
        }
        for i in items[:limit]
    ]


@app.get("/api/sales/stream")
def sales_stream():
    def generator():
        global _latest_sale_ts
        seen_ts = _latest_sale_ts

        while True:
            try:
                table = dynamodb.Table(SALES_TABLE)
                items = table.scan()["Items"]
                items.sort(key=lambda x: x["timestamp"])

                new_items = [i for i in items if i["timestamp"] > seen_ts] if seen_ts else []
                for i in new_items:
                    sale = {
                        "sale_id": i["sale_id"],
                        "product_id": i["product_id"],
                        "quantity": int(i["quantity"]),
                        "price_at_sale": float(i["price_at_sale"]),
                        "timestamp": i["timestamp"],
                    }
                    yield f"data: {json.dumps(sale)}\n\n"

                if items:
                    seen_ts = items[-1]["timestamp"]
                    _latest_sale_ts = seen_ts
            except Exception:
                pass
            time.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Price History ────────────────────────────────────────────────────────────

@app.get("/api/price-history/{product_id}")
def get_price_history(product_id: str):
    """Builds price history from the PRICE_UPDATE records in the AuditLog."""
    audit_table = dynamodb.Table(AUDIT_TABLE)
    products_table = dynamodb.Table(PRODUCTS_TABLE)

    # Fetch all PRICE_UPDATE logs
    items = audit_table.scan(
        FilterExpression="product_id = :pid AND #a = :act",
        ExpressionAttributeNames={"#a": "action"},
        ExpressionAttributeValues={":pid": product_id, ":act": "PRICE_UPDATE"},
    )["Items"]

    # Filter to genuine price changes
    changes = []
    for i in items:
        old = i.get("old_value", "")
        new = i.get("new_value", "")
        try:
            old_f = float(str(old).replace("₺", "").replace(",", "").strip())
            new_f = float(str(new).replace("₺", "").replace(",", "").strip())
            if old_f != new_f:
                changes.append({
                    "timestamp": i["timestamp"],
                    "old_price": old_f,
                    "new_price": new_f,
                    "reason": i.get("reason", ""),
                    "direction": "down" if new_f < old_f else "up",
                })
        except (ValueError, TypeError):
            continue

    changes.sort(key=lambda x: x["timestamp"])

    product = products_table.get_item(Key={"product_id": product_id}).get("Item", {})
    base_price = float(product.get("base_price", product.get("current_price", 0)))
    current_price = float(product.get("current_price", 0))

    # Keep only significant price changes (filter out small fluctuations)
    significant = []
    THRESHOLD = 100
    last_price = None
    for c in changes:
        if last_price is None or abs(c["new_price"] - last_price) >= THRESHOLD:
            significant.append(c)
            last_price = c["new_price"]

    # Build the timeline — compute direction by comparing with the previous
    # timeline point, not from the stored old_value (more reliable)
    timeline = []
    if significant:
        timeline.append({
            "timestamp": significant[0]["timestamp"],
            "price": significant[0]["old_price"],
            "event": "start",
        })
        prev_price = significant[0]["old_price"]
        for c in significant:
            direction = "down" if c["new_price"] < prev_price else "up"
            timeline.append({
                "timestamp": c["timestamp"],
                "price": c["new_price"],
                "event": direction,
                "reason": c["reason"],
            })
            prev_price = c["new_price"]
    else:
        timeline.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": current_price,
            "event": "start",
        })

    return {
        "product_id": product_id,
        "current_price": current_price,
        "base_price": base_price,
        "timeline": timeline,
    }


# ── Audit ─────────────────────────────────────────────────────────────────────

@app.get("/api/audit")
def get_audit(limit: int = 50):
    table = dynamodb.Table(AUDIT_TABLE)
    items = table.scan()["Items"]
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return [
        {
            "log_id": i["log_id"],
            "timestamp": i["timestamp"],
            "product_id": i["product_id"],
            "action": i["action"],
            "old_value": i.get("old_value", ""),
            "new_value": i.get("new_value", ""),
            "reason": i.get("reason", ""),
            "agent_decision": i.get("agent_decision", ""),
        }
        for i in items[:limit]
    ]


# ── Competitors ───────────────────────────────────────────────────────────────

@app.get("/api/competitors")
def get_competitors():
    table = dynamodb.Table(COMPETITORS_TABLE)
    items = table.scan()["Items"]
    return [
        {
            "product_id": i["product_id"],
            "competitor": i["competitor_name"],
            "price": float(i["price"]),
            "url": i.get("url", ""),
            "last_checked": i.get("last_checked", ""),
        }
        for i in sorted(items, key=lambda x: (x["product_id"], float(x["price"])))
    ]


# ── Competitor price simulation ──────────────────────────────────────────────

# Starting prices — the simulator does a random walk around these
# min_floor: the simulator can't go below this value (the product's min_price)
_COMP_BASE = {
    "PROD-001": {"Amazon": 1059, "Best Buy": 1079, "MediaMarkt": 1089},
    "PROD-002": {"Amazon": 259,  "Best Buy": 269,  "MediaMarkt": 274},
    "PROD-003": {"Amazon": 869,  "Best Buy": 879,  "MediaMarkt": 889},
    "PROD-004": {"Amazon": 219,  "Best Buy": 224,  "MediaMarkt": 226},
}
_COMP_MIN_FLOOR = {
    "PROD-001": 920,
    "PROD-002": 225,
    "PROD-003": 745,
    "PROD-004": 185,
}
_comp_current: dict[str, dict[str, float]] = {
    pid: {c: float(p) for c, p in comps.items()}
    for pid, comps in _COMP_BASE.items()
}

_comp_sim_thread = None
_comp_sim_stop = threading.Event()


def _competitor_sim_worker():
    """
    Every 30-60 seconds, competitor prices take a ±3% random walk.
    With 10% probability a competitor opens an 8-15% flash sale (lasts 60-120s).
    A price cannot move more than 20% away from its base price.
    """
    table = dynamodb.Table(COMPETITORS_TABLE)
    flash_timers: dict[str, float] = {}  # "PROD-001:Trendyol" → end time

    while not _comp_sim_stop.is_set():
        now = time.time()

        for pid, competitors in _comp_current.items():
            base = _COMP_BASE[pid]
            for comp_name, price in competitors.items():
                key = f"{pid}:{comp_name}"
                base_price = base[comp_name]

                # If the flash sale expired, return to normal
                if key in flash_timers and now > flash_timers[key]:
                    _comp_current[pid][comp_name] = float(base_price) * random.uniform(0.97, 1.03)
                    del flash_timers[key]
                    continue

                # Active flash sale — don't change the price
                if key in flash_timers:
                    continue

                # Start a flash sale with 10% probability
                if random.random() < 0.10:
                    discount = random.uniform(0.08, 0.15)
                    new_price = float(base_price) * (1 - discount)
                    duration = random.uniform(60, 120)
                    flash_timers[key] = now + duration
                else:
                    # Normal random walk ±3%
                    change = random.uniform(-0.03, 0.03)
                    new_price = price * (1 + change)

                # Bound: between min_floor and 120% of the base price
                floor = _COMP_MIN_FLOOR.get(pid, float(base_price) * 0.85)
                new_price = max(floor, min(new_price, float(base_price) * 1.20))
                new_price = round(new_price / 10) * 10  # round to 10

                _comp_current[pid][comp_name] = new_price

                # Write to DynamoDB
                try:
                    table.update_item(
                        Key={"product_id": pid, "competitor_name": comp_name},
                        UpdateExpression="SET price = :p, last_checked = :t",
                        ExpressionAttributeValues={
                            ":p": Decimal(str(int(new_price))),
                            ":t": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception:
                    pass

        _comp_sim_stop.wait(random.uniform(30, 60))


@app.post("/api/demo/competitors/start")
def competitor_sim_start():
    global _comp_sim_thread
    if _comp_sim_thread and _comp_sim_thread.is_alive():
        return {"status": "already_running"}
    _comp_sim_stop.clear()
    _comp_sim_thread = threading.Thread(target=_competitor_sim_worker, daemon=True)
    _comp_sim_thread.start()
    return {"status": "started"}


@app.post("/api/demo/competitors/stop")
def competitor_sim_stop():
    _comp_sim_stop.set()
    return {"status": "stopped"}


@app.get("/api/demo/competitors/status")
def competitor_sim_status():
    running = bool(_comp_sim_thread and _comp_sim_thread.is_alive() and not _comp_sim_stop.is_set())
    return {"running": running, "current_prices": _comp_current}


# ── Sales simulation ──────────────────────────────────────────────────────────

def _simulation_worker():
    products_table = dynamodb.Table(PRODUCTS_TABLE)
    sales_table = dynamodb.Table(SALES_TABLE)

    while not _sim_stop.is_set():
        products = products_table.scan()["Items"]
        if not products:
            _sim_stop.wait(3)
            continue

        # Bundle-aware weights: more sales if an accessory's price has dropped
        weights = []
        for p in products:
            base = float(p.get("base_price", p["current_price"]))
            curr = float(p["current_price"])
            discount_ratio = (base - curr) / base if base > 0 else 0
            # Accessory + discount → higher weight, normal product → 1x
            is_accessory = "bundle_parent" in p
            w = 1.0
            if is_accessory and discount_ratio > 0.03:
                w = 1.0 + (discount_ratio * 8)  # 7% discount → ~1.56x weight
            weights.append(w)

        product = random.choices(products, weights=weights, k=1)[0]
        qty = random.randint(1, 2)
        sales_table.put_item(
            Item={
                "sale_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "product_id": product["product_id"],
                "quantity": qty,
                "price_at_sale": product["current_price"],
                "customer_id": f"CUST-{random.randint(1000, 9999)}",
            }
        )
        _sim_stop.wait(random.uniform(2.5, 5.0))


@app.post("/api/demo/simulate/start")
def demo_simulate_start():
    global _sim_thread
    if _sim_thread and _sim_thread.is_alive():
        return {"status": "already_running"}
    _sim_stop.clear()
    _sim_thread = threading.Thread(target=_simulation_worker, daemon=True)
    _sim_thread.start()
    return {"status": "started"}


@app.post("/api/demo/simulate/stop")
def demo_simulate_stop():
    _sim_stop.set()
    return {"status": "stopped"}


@app.post("/api/demo/crisis")
def demo_crisis():
    from infrastructure.dynamodb_setup import seed_products, seed_sales
    _sim_stop.set()
    seed_products()       # reset prices back to base
    seed_sales(healthy=False)   # stop sales
    # NOTE: seed_competitors is not called — undercut_since is preserved
    return {"status": "ok", "message": "Crisis data loaded"}


@app.post("/api/demo/healthy")
def demo_healthy():
    from infrastructure.dynamodb_setup import seed_all
    seed_all(crisis_mode=False)
    return {"status": "ok", "message": "Healthy data loaded"}


# ── Analytics ────────────────────────────────────────────────────────────────

@app.get("/api/analytics/revenue-impact")
def get_revenue_impact():
    """
    Computes the revenue impact of the agent's price decisions.

    Logic:
    - Crisis: 0 sales × any price = $0
    - The agent lowers the price → sales come in
    - Without those sales it would be $0 → the agent's contribution = those sales' revenue

    Method:
    - PRICE_UPDATE events in the audit log = agent interventions
    - Sales that arrive after each intervention (after that timestamp) = contribution
    """
    audit_table   = dynamodb.Table(AUDIT_TABLE)
    sales_table   = dynamodb.Table(SALES_TABLE)
    products_table = dynamodb.Table(PRODUCTS_TABLE)

    # Get every product's base_price
    products = {p["product_id"]: p for p in products_table.scan()["Items"]}

    # Find genuine price drops (new < old, both numeric)
    audit_items = audit_table.scan(
        FilterExpression="#a = :a",
        ExpressionAttributeNames={"#a": "action"},
        ExpressionAttributeValues={":a": "PRICE_UPDATE"},
    )["Items"]

    drops = []
    for item in audit_items:
        try:
            old = float(str(item.get("old_value","")).replace("TL","").replace("₺","").strip())
            new = float(str(item.get("new_value","")).replace("TL","").replace("₺","").strip())
            if new < old and new > 0 and old > 0:
                drops.append({
                    "product_id": item["product_id"],
                    "timestamp": item["timestamp"],
                    "old_price": old,
                    "new_price": new,
                })
        except (ValueError, TypeError):
            continue

    drops.sort(key=lambda x: x["timestamp"])

    # Fetch all sales
    all_sales = sales_table.scan()["Items"]

    # For each drop, find the sales that came after it
    impact_by_product = {}
    for drop in drops:
        pid = drop["product_id"]
        ts  = drop["timestamp"]
        if pid not in impact_by_product:
            impact_by_product[pid] = {
                "product_id": pid,
                "product_name": products.get(pid, {}).get("name", pid),
                "price_drops": 0,
                "agent_enabled_revenue": 0.0,
                "agent_enabled_orders": 0,
                "avg_discount_pct": 0.0,
                "drops": [],
            }
        impact_by_product[pid]["price_drops"] += 1

        sales_after = [
            s for s in all_sales
            if s["product_id"] == pid and s["timestamp"] >= ts
        ]
        revenue = sum(float(s["price_at_sale"]) * int(s["quantity"]) for s in sales_after)
        impact_by_product[pid]["agent_enabled_revenue"] += revenue
        impact_by_product[pid]["agent_enabled_orders"]  += len(sales_after)
        base = float(products.get(pid, {}).get("base_price", drop["old_price"]))
        discount_pct = round((base - drop["new_price"]) / base * 100, 1) if base > 0 else 0
        impact_by_product[pid]["drops"].append({
            "timestamp": ts,
            "old_price": drop["old_price"],
            "new_price": drop["new_price"],
            "discount_pct": discount_pct,
            "orders_after": len(sales_after),
            "revenue_after": round(revenue, 2),
        })

    result = list(impact_by_product.values())
    total_impact = sum(r["agent_enabled_revenue"] for r in result)
    total_orders = sum(r["agent_enabled_orders"] for r in result)
    total_drops  = sum(r["price_drops"] for r in result)

    return {
        "summary": {
            "total_agent_revenue": round(total_impact, 2),
            "total_orders_enabled": total_orders,
            "total_price_drops": total_drops,
        },
        "by_product": sorted(result, key=lambda x: x["agent_enabled_revenue"], reverse=True),
    }


@app.get("/api/analytics/summary")
def get_analytics_summary():
    """The agent analyzes its own decisions — via Athena."""
    from tools.run_analytics import run_analytics

    queries = {
        "actions": """
            SELECT
              CASE
                WHEN action = 'PRICE_UPDATE'   THEN 'Price Updated'
                WHEN action LIKE '%EMAIL%'      THEN 'Email Attempted'
                WHEN action LIKE '%OUTCOME%'    THEN 'Outcome Logged'
                WHEN action = 'SALES_CHECK'     THEN 'Sales Check'
                ELSE action
              END as action_label,
              COUNT(*) as count
            FROM heweso_analytics.audit_log
            WHERE action != 'NO_ACTION'
              AND action NOT LIKE '%NO_%'
              AND action != 'SUCCESS'
            GROUP BY 1
            ORDER BY count DESC
            LIMIT 6
        """,
        "price_changes": """
            SELECT product_id,
                   COUNT(*) as changes,
                   MIN(CAST(new_value AS double)) as min_price,
                   MAX(CAST(new_value AS double)) as max_price
            FROM heweso_analytics.audit_log
            WHERE action = 'PRICE_UPDATE'
              AND new_value NOT LIKE '%TL%'
              AND new_value != 'N/A'
            GROUP BY product_id
        """,
        "revenue_today": """
            SELECT product_id,
                   COUNT(*) as orders,
                   SUM(quantity * price_at_sale) as revenue
            FROM heweso_analytics.sales
            GROUP BY product_id
            ORDER BY revenue DESC
        """,
        "crisis_count": """
            SELECT
              SUM(CASE WHEN action = 'PRICE_UPDATE' THEN 1 ELSE 0 END) as price_updates,
              SUM(CASE WHEN action LIKE '%EMAIL%' AND action NOT LIKE '%FAIL%'
                            AND action NOT LIKE '%BLOCK%' AND action NOT LIKE '%ERROR%'
                       THEN 1 ELSE 0 END) as emails_sent,
              COUNT(*) as total_actions
            FROM heweso_analytics.audit_log
        """,
    }

    results = {}
    for key, sql in queries.items():
        r = run_analytics(sql.strip(), max_rows=10)
        results[key] = r

    return results


@app.post("/api/analytics/export")
def trigger_export():
    """Triggers the DynamoDB → S3 export."""
    from infrastructure.export_to_s3 import run_export
    count = run_export()
    return {"status": "ok", "rows_exported": count}


# ── Agent trigger + SSE ───────────────────────────────────────────────────────

@app.post("/api/demo/trigger")
def demo_trigger(product_id: str = "PROD-001", test_hour: int = None, reason: str = None):
    run_id = str(uuid.uuid4())[:8]
    _agent_logs[run_id] = []

    def _run():
        from agent.bedrock_agent import run_agent

        def on_event(event):
            _agent_logs[run_id].append(event)

        trigger_reason = reason or "Manual demo trigger"
        if test_hour is not None:
            trigger_reason = f"Manual demo — simulated hour: {test_hour:02d}:00"

        try:
            run_agent(
                product_id,
                trigger_reason=trigger_reason,
                log_fn=on_event,
                test_hour=test_hour,
            )
        except Exception as e:
            _agent_logs[run_id].append({"type": "error", "text": str(e)})
        finally:
            _agent_logs[run_id].append({"type": "done"})

    threading.Thread(target=_run, daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/agent/stream/{run_id}")
def agent_stream(run_id: str):
    def event_generator():
        sent = 0
        while True:
            logs = _agent_logs.get(run_id, [])
            while sent < len(logs):
                event = logs[sent]
                sent += 1
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    return
            time.sleep(0.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Static files ──────────────────────────────────────────────────────────────

app.mount(
    "/",
    StaticFiles(directory=os.path.dirname(__file__), html=True),
    name="static",
)
