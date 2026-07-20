"""
silver.py — Bronze → Silver dönüşümü.

Medallion Architecture — Silver katmanı:
  Temizlenmiş, join edilmiş, türetilmiş alanlar eklenmiş veri.
  Bronze'dan okur, Silver'a yazar.

Üretilen tablolar:
  silver/sales_enriched/     — Sales + Product join, revenue hesaplı
  silver/price_actions/      — Audit log'dan fiyat değişimleri, zenginleştirilmiş
  silver/competitor_gaps/    — Rakip fiyatlar vs bizim fiyatlarımız, fark hesaplı
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


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def _read_bronze(table: str, date: str) -> list:
    """Bronze katmanından NDJSON okur."""
    key = f"bronze/{table}/date={date}/data.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        lines = response["Body"].read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]
    except s3.exceptions.NoSuchKey:
        print(f"  ⚠️  Bronze bulunamadı: {key} (henüz export yapılmamış olabilir)")
        return []
    except Exception as e:
        print(f"  ❌ Bronze okuma hatası ({key}): {e}")
        return []


def _write_silver(table: str, records: list, date: str):
    """Silver katmanına NDJSON yazar."""
    key = f"silver/{table}/date={date}/data.json"
    body = "\n".join(json.dumps(r, default=str) for r in records)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"  ✅ {len(records)} rows → s3://{BUCKET}/{key}")


def _parse_ts(ts: str, fallback_date: str):
    """ISO timestamp'i parse eder, hata varsa fallback döner."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.hour
    except Exception:
        return fallback_date, 0


def _is_price_action(action: dict) -> bool:
    """Audit log kaydının fiyat değişikliği olup olmadığını kontrol eder."""
    keywords = ["price", "discount", "bundle", "recovery", "crisis"]
    return any(kw in str(action.get("action", "")).lower() for kw in keywords)


# ── Silver dönüşümleri ────────────────────────────────────────────────────────

def transform_sales_enriched(date: str) -> int:
    """
    silver_sales_enriched: Satış verisi + ürün bilgisi.

    Bronze sales sadece product_id tutar. Biz product_id → name, category join edip
    revenue (gelir = quantity × price_at_sale) hesaplıyoruz.

    Neden önemli: Gold katmanında "iPhone 17 Pro bugün kaç lira gelir üretti?" sorusunu
    doğrudan cevaplayabiliriz — her seferinde join yapmak gerekmez.
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
            "revenue":      round(qty * price, 2),   # türetilmiş alan
            "customer_id":  sale.get("customer_id"),
        })

    _write_silver("sales_enriched", enriched, date)
    return len(enriched)


def transform_price_actions(date: str) -> int:
    """
    silver_price_actions: Fiyat değişikliklerini zenginleştirir.

    Audit log'da her şey var: escalation, skip, fiyat değişimi vs.
    Biz sadece fiyat değişimlerini filtreler, price_change_pct ve direction hesaplarız.

    direction: DOWN (indirim), UP (kurtarma/recovery), SAME
    price_change_pct: -9.1 (yüzde 9.1 indirim yapıldı)
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
            "price_change_pct": change_pct,   # türetilmiş alan
            "direction":      direction,        # türetilmiş alan
            # Yapısal alan: bundle indirim oranı. Kaynakta (log_action) yazıldığı
            # için artık reason metninden REGEXP'le kazımaya gerek yok. Bundle
            # olmayan / eski kayıtlarda yok → None (öğrenici NULL'ları yok sayar).
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
    silver_competitor_gaps: Rakip fiyatlar vs bizim fiyatlarımız.

    Her rakip-ürün çifti için fiyat farkı hesaplar.
    gap_pct: pozitif = biz daha pahalıyız, negatif = biz daha ucuzuz.
    we_are_cheaper: biz rakipten ucuz muyuz?

    Neden önemli: "Kaç üründe rakipten pahalıyız?" sorusunu tek SQL ile cevaplayabilirsin.
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
            "price_gap":        gap,           # türetilmiş: pozitif = biz pahalıyız
            "gap_pct":          gap_pct,       # türetilmiş: yüzde fark
            "we_are_cheaper":   our_price < comp_price,
            "undercut_since":   comp.get("undercut_since"),
            "last_checked":     comp.get("last_checked"),
            "snapshot_date":    date,
        })

    _write_silver("competitor_gaps", enriched, date)
    return len(enriched)


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

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
