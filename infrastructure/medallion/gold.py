"""
gold.py — Silver → Gold aggregation.

Medallion Architecture — Gold katmanı:
  İş sorularına göre önceden hesaplanmış, aggregate edilmiş veri.
  Silver'dan okur, Gold'a yazar.
  Athena bu tabloları sorgularken büyük hesaplamalar yapmak zorunda kalmaz.

Üretilen tablolar:
  gold/daily_product_metrics/  — Ürün başına GÜNLÜK satış + fiyat özeti
  gold/agent_performance/      — Agent'ın GÜNLÜK karar kalitesi
  gold/bundle_effectiveness/   — Bundle indirimlerinin sonuçları

═══════════════════════════════════════════════════════════════════════════════
EVENT-DATE PARTITIONING (neden GROUP BY sale_date/action_date?)
───────────────────────────────────────────────────────────────────────────────
export_to_s3.py her çalıştığında DynamoDB'yi TAM tarar (full scan). Yani "bugün"
partition'ı (date=BUGÜN) sadece bugünkü değil, TÜM geçmiş satışları içerir —
tıpkı her gece bütün günlüğünü baştan fotokopileyip "bugün" klasörüne koymak gibi.

Bu yüzden Gold'u snapshot tarihine (partition adı) göre gruplamak YANLIŞTIR:
"date=BUGÜN" Gold satırı, o günün değil TÜM zamanların toplamını verirdi ve
7 günü toplayınca eski satışlar tekrar tekrar sayılırdı (double-count).

DOĞRU yol: her Silver satırının KENDİ gerçek olay tarihine bak (sales için
sale_date, price_actions için action_date — ikisi de Silver'da hazır) ve ona göre
grupla + o olay tarihine göre partition'a yaz. Böylece her satış TAM 1 kez sayılır
ve haftalık rapor artık Silver yerine doğrudan Gold'u okuyabilir. Full-refresh ama
idempotent: aynı çalıştırma tüm olay-tarihi partition'larını baştan yazar.
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


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def _read_silver(table: str, date: str) -> list:
    """Silver katmanından NDJSON okur."""
    key = f"silver/{table}/date={date}/data.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        lines = response["Body"].read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]
    except s3.exceptions.NoSuchKey:
        print(f"  ⚠️  Silver bulunamadı: {key} (önce silver.py çalıştırılmalı)")
        return []
    except Exception as e:
        print(f"  ❌ Silver okuma hatası ({key}): {e}")
        return []


def _write_gold(table: str, records: list, date: str):
    """Gold katmanına NDJSON yazar (verilen olay tarihinin partition'ına)."""
    key = f"gold/{table}/date={date}/data.json"
    body = "\n".join(json.dumps(r, default=str) for r in records)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"  ✅ {len(records)} rows → s3://{BUCKET}/{key}")


def _write_gold_by_event_date(table: str, records_by_date: dict) -> int:
    """
    records_by_date: {event_date: [record, ...]} — her olay tarihini KENDİ
    partition'ına yazar. Full-refresh: her partition baştan yazılır (idempotent).
    """
    total = 0
    for event_date in sorted(records_by_date):
        records = records_by_date[event_date]
        _write_gold(table, records, event_date)
        total += len(records)
    return total


# ── Gold aggregation'lar ──────────────────────────────────────────────────────

def build_daily_product_metrics(snapshot_date: str) -> int:
    """
    gold_daily_product_metrics: Ürün başına GÜNLÜK özet.

    Soru: "8 Temmuz'da hangi ürün kaç adet sattı, kaç lira gelir üretti,
           kaç kez fiyat değişti?"

    Gruplama anahtarı (event_date, product_id) — snapshot değil, satırın KENDİ
    tarihi (sales → sale_date, price_actions → action_date). Böylece Gold gerçekten
    günlük olur.
    """
    sales         = _read_silver("sales_enriched", snapshot_date)
    price_actions = _read_silver("price_actions", snapshot_date)

    # Satış aggregate: (olay tarihi, ürün) bazında topla
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

    # Fiyat değişimi sayıları: (olay tarihi, ürün) bazında
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

    # Tüm (tarih, ürün) anahtarlarını birleştir, sonra olay tarihine göre grupla
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
    gold_agent_performance: Agent'ın GÜNLÜK karar özeti.

    Soru: "8 Temmuz'da PROD-002 için kaç indirim kararı aldı?
           Ortalama indirim yüzdesi ne? Kaç bundle uyguladı?"

    Gruplama anahtarı (action_date, product_id). Bu tablo portfolio demosunda
    güçlü — agent'ın öğrenip öğrenmediğini artık GERÇEK bir zaman serisi olarak
    gösterebilirsin (her gün kendi partition'ında).
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
    gold_bundle_effectiveness: Bundle indirimlerinin satışa etkisi.

    Soru: "8 Temmuz'da AirPods Pro 3'e kaç kez bundle indirimi uygulandı?
           Ortalama indirim yüzdesi ne? O gün kaç adet sattı?"

    Gruplama anahtarı (action_date, product_id). Epsilon-greedy öğrenmenin
    sonuçlarını gün gün görselleştirmek için kullanılabilir.
    HIGH = günde 3+ satış, MEDIUM = 1-2, LOW = 0.
    """
    price_actions = _read_silver("price_actions", snapshot_date)
    sales         = _read_silver("sales_enriched", snapshot_date)

    bundle_actions = [a for a in price_actions if "bundle" in str(a.get("action", "")).lower()]

    # (olay tarihi, ürün) → o gün o ürünün toplam satışı
    sales_by_key = defaultdict(int)
    for sale in sales:
        event_date = sale.get("sale_date") or snapshot_date
        sales_by_key[(event_date, sale["product_id"])] += int(sale.get("quantity", 1))

    # (olay tarihi, ürün) → o gün o ürüne uygulanan bundle aksiyonları
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


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def run_gold(snapshot_date: str = None) -> int:
    """
    snapshot_date: hangi Silver partition'ını okuyacağımız (varsayılan bugün).
    Çıktı: her tablo, satırların KENDİ olay tarihine göre partition'lara yazılır.
    """
    snapshot_date = snapshot_date or today
    print(f"\n=== Silver → Gold Aggregate (snapshot okundu: {snapshot_date}, event-date'e göre yazılıyor) ===")
    n1 = build_daily_product_metrics(snapshot_date)
    n2 = build_agent_performance(snapshot_date)
    n3 = build_bundle_effectiveness(snapshot_date)
    total = n1 + n2 + n3
    print(f"\n✅ Gold complete — {total} total rows written")
    return total


if __name__ == "__main__":
    run_gold()
