"""
check_bundle_trigger — Aksesuar için parent telefon satışlarını kontrol eder.

Mantık:
  - Her aksesuarın bir parent telefonu var (PROD-002 → PROD-001 gibi)
  - Parent telefon SURGE yapıyorsa → aksesuar için bundle fırsatı var
  - Agent bu bilgiyle aksesuar fiyatını proaktif indirebilir
"""

import os
import random
import boto3
from datetime import datetime, timezone
from dotenv import load_dotenv

BUNDLE_RATES       = [5, 7, 9, 11]   # denenecek indirim oranları (%)
EXPLORATION_PROB   = 0.30             # %30 keşif, %70 en iyi bilinen oranı kullan
MIN_BUNDLE_SAMPLES = 3               # bir oranı "exploit" etmeden önce en az bu kadar
                                     # kez denenmiş olmalı (confidence gate) — tek şanslı
                                     # örnek en iyi ilan edilip kral olmasın

load_dotenv()

AWS_REGION     = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def check_bundle_trigger(product_id: str) -> dict:
    """
    Bu ürün bir aksesuarsa, parent telefonunun satış durumuna bakar.
    Parent telefon SURGE yapıyorsa bundle fırsatı döner.

    Args:
        product_id: Aksesuar ürün ID (PROD-002, PROD-004)

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

    # Parent telefon bilgisi
    parent = _dynamodb.Table(PRODUCTS_TABLE) \
        .get_item(Key={"product_id": parent_id}).get("Item", {})
    parent_name = parent.get("name", parent_id)

    # Parent telefonun SURGE olup olmadığını TEK KAYNAKTAN öğren: check_sales_trend.
    # Eskiden burada ayrı bir 30/30 dk sayımı + gevşek 1.5x eşiği vardı; bu,
    # check_sales_trend'in 2x tanımıyla çelişiyordu. Artık "surge nedir" tanımı
    # sistemde tek yerde — min-hacim koruması (MIN_SURGE_COUNT) da otomatik miras alınır.
    from .check_sales_trend import check_sales_trend
    parent_trend = check_sales_trend(parent_id, window_minutes=30)

    recent      = parent_trend["current_count"]
    prev        = parent_trend["previous_count"]
    is_surge    = parent_trend["trend"] == "SURGE"
    surge_ratio = round(recent / prev, 2) if prev > 0 else None

    # Epsilon-greedy discount seçimi
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
    Geçmiş bundle indirimlerinden öğrenerek optimal oranı seçer.
    Yeterli veri yoksa veya exploration modundaysa rastgele dener.

    Returns: (discount_pct, strategy) — strategy: "exploit" | "explore" | "random"
    """
    from .run_analytics import run_analytics

    # date = today filtresi — Hive partition pruning:
    #   Bronze her gün TAM tarar (incremental değil), en son partition (bugün)
    #   zaten tüm geçmişi içeriyor. Filtre olmadan Athena partition projection
    #   range'indeki (2026-01-01,NOW) TÜM günlere bakıyordu — gereksiz S3 maliyeti.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # YAPISAL ALAN (REGEXP DEĞİL): oran artık Silver'ın typed bundle_discount_pct
    # kolonundan okunuyor — kaynakta (log_action) yazıldığı için reason metnini
    # ayrıştırmaya gerek yok. Gelir de Silver'ın hazır `revenue` alanından geliyor
    # (analyze_price_elasticity ile aynı desen). Reward = gelir, adet değil.
    # n_pulls = o oranın kaç kez uygulandığı → confidence gate için.
    # bundle_discount_pct IS NOT NULL → alanı olmayan eski kayıtlar yok sayılır.
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
            # Confidence gate: en iyi oranı ancak yeterince denenmişse (n_pulls >= MIN)
            # "exploit" et. Aksi halde tek şanslı örneğe güvenmeyip keşfe devam.
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
