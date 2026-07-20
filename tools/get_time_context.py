"""
get_time_context — Saatlik satış örüntüsünü gerçek veriden öğrenir.

Hardcode kural yok. Athena'daki geçmiş satış verisine bakarak
şu anki saatin bu ürün için peak mi off-peak mi olduğunu ÖLÇER.

Önemli: bu tool bir KARAR (HOLD/AGGRESSIVE gibi) dönmez — ham bir sinyal döner
ve kararı modele bırakır. Bu, kural-tabanlı sistemle veri-tabanlı sistem
arasındaki farktır (bkz. CLAUDE.md "raw numbers not labels").

Mantık:
  - Geçmişteki satışları saat bazında grupla (Silver: silver_sales_enriched)
  - Şu anki saatin satış sayısını ve genel ortalamayı hesapla
  - traffic_ratio = bu_saat / genel_ortalama  (ham sayı)
  - traffic_ratio >= 1.5 → traffic_level="high"  (doğal talep yüksek)
  - traffic_ratio <= 0.3 → traffic_level="low"   (doğal talep düşük)
  - arada              → traffic_level="medium"
  - Özel gün varsa     → traffic_level="campaign" (traffic_ratio hesaplanmaz)
  - Veri yoksa         → traffic_level="unknown"/"no_data"
"""

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TZ_TURKEY = timezone(timedelta(hours=3))

SPECIAL_DAYS: dict[tuple[int, int], str] = {
    (1,  1):  "New Year's Day",
    (2, 14):  "Valentine's Day",
    (5, 12):  "Mother's Day",
    (6, 15):  "Father's Day",
    (10, 29): "Republic Day",
    (11, 11): "Singles' Day",
    (11, 29): "Black Friday",
    (12, 24): "Christmas Eve",
    (12, 25): "Christmas Day",
    (12, 31): "New Year's Eve",
}


def get_time_context(product_id: str, test_hour: int = None) -> dict:
    """
    Gerçek satış verisine dayanarak şu anki saatin
    bu ürün için ne anlama geldiğini döner.

    Args:
        product_id: Hangi ürünün satış örüntüsüne bakılacak

    Returns:
        {
            "local_time":        str,
            "hour":              int,
            "special_day":       str | None,
            "traffic_ratio":     float | None,  # bu_saat / genel_ortalama (ham sinyal)
            "traffic_level":     "high" | "medium" | "low" | "campaign" | "unknown",
            "current_hour_sales": float,  # bu saatin geçmiş ortalaması
            "overall_avg_sales":  float,  # tüm saatlerin ortalaması
            "data_points":        int,    # kaç satış kaydı analiz edildi
            "context":           str,     # modele verilen düz-metin bağlam
        }
    """
    from .run_analytics import run_analytics

    now     = datetime.now(TZ_TURKEY)
    hour    = test_hour if test_hour is not None else now.hour
    weekday = now.weekday()
    special = SPECIAL_DAYS.get((now.month, now.day))

    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    local_str = f"{now.strftime('%Y-%m-%d %H:%M')} ({day_names[weekday]})"

    # Özel günse direkt dön — traffic oranı yerine kampanya bağlamı ver
    if special:
        return {
            "local_time":         local_str,
            "hour":               hour,
            "special_day":        special,
            "traffic_ratio":      None,
            "traffic_level":      "campaign",
            "current_hour_sales": None,
            "overall_avg_sales":  None,
            "data_points":        0,
            "context": (
                f"Today is {special}. Campaign day — consumer intent is high, "
                f"price sensitivity is elevated. Competitor gaps matter more than usual."
            ),
        }

    # Silver katmanını kullanıyoruz:
    #   - sale_hour Silver'da zaten hesaplı, SQL'de timestamp parse etmeye gerek yok
    #
    # date = today filtresi — Hive partition pruning:
    #   Bronze her gün TAM tarar (incremental değil), en son partition (bugün)
    #   zaten tüm geçmişi içeriyor. Filtre olmadan Athena partition projection
    #   range'indeki (2026-01-01,NOW) TÜM günlere bakıyordu — gereksiz S3 maliyeti.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sql = f"""
    SELECT
        sale_hour,
        COUNT(*) AS sale_count
    FROM heweso_analytics.silver_sales_enriched
    WHERE product_id = '{product_id}'
      AND date = '{today}'
    GROUP BY sale_hour
    ORDER BY sale_hour
    """

    result = run_analytics(sql, max_rows=24)

    if not result["success"] or not result["rows"]:
        return {
            "local_time":         local_str,
            "hour":               hour,
            "special_day":        None,
            "traffic_ratio":      None,
            "traffic_level":      "unknown",
            "current_hour_sales": 0,
            "overall_avg_sales":  0,
            "data_points":        0,
            "context":            "No historical sales data for this product yet. Apply standard pricing rules.",
        }

    # Saat → satış sayısı map'i
    hour_map: dict[int, int] = {}
    for row in result["rows"]:
        try:
            h  = int(row[0])
            ct = int(row[1])
            hour_map[h] = ct
        except (ValueError, TypeError):
            continue

    total_sales  = sum(hour_map.values())
    total_hours  = len(hour_map)
    overall_avg  = total_sales / total_hours if total_hours else 0
    current_val  = hour_map.get(hour, 0)

    if overall_avg == 0:
        traffic_ratio = None
        traffic_level = "unknown"
        context = f"Hour {hour}:00 — no historical sales distribution available."
    else:
        traffic_ratio = round(current_val / overall_avg, 2)
        if traffic_ratio >= 1.5:
            traffic_level = "high"
            context = (
                f"Hour {hour}:00 has {traffic_ratio}x the average traffic for this product "
                f"({current_val:.1f} sales vs {overall_avg:.1f} avg). Natural demand is high."
            )
        elif traffic_ratio <= 0.3:
            traffic_level = "low"
            context = (
                f"Hour {hour}:00 has {traffic_ratio}x the average traffic for this product "
                f"({current_val:.1f} sales vs {overall_avg:.1f} avg). Natural demand is low."
            )
        else:
            traffic_level = "medium"
            context = (
                f"Hour {hour}:00 has {traffic_ratio}x the average traffic for this product "
                f"({current_val:.1f} sales vs {overall_avg:.1f} avg). Normal demand period."
            )

    return {
        "local_time":         local_str,
        "hour":               hour,
        "special_day":        None,
        "traffic_ratio":      traffic_ratio,
        "traffic_level":      traffic_level,
        "current_hour_sales": round(current_val, 2),
        "overall_avg_sales":  round(overall_avg, 2),
        "data_points":        total_sales,
        "context":            context,
    }


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = get_time_context(pid)
        print(f"{pid}: level={r['traffic_level']} ratio={r['traffic_ratio']} | {r['context'][:80]}")
