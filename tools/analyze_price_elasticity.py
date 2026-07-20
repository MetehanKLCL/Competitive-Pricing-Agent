"""
analyze_price_elasticity — Learns price elasticity from historical decisions.

Queries Athena Silver tables (silver_price_actions + silver_sales_enriched):
  - For each price drop (direction=DOWN), sums REVENUE in the following 60 minutes
  - Groups by discount percentage to find which drop drove the most revenue
  - Recommends the optimal discount percentage

Reward = revenue (price_at_sale × quantity), NOT unit count. A -5% drop that
sells 3 cheap units can earn less than a -2% drop that sells 2 expensive units;
optimizing for revenue captures that, optimizing for count does not.

Example output:
  -5% drop → avg $2,400 revenue (2 samples)
  -10% drop → avg $1,800 revenue (1 sample)
  Recommendation: -5% drove more revenue — prefer it
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from .run_analytics import run_analytics

load_dotenv()


def analyze_price_elasticity(product_id: str) -> dict:
    """
    Analyzes historical price changes and their sales impact.

    Returns:
        {
            "success": bool,
            "product_id": str,
            "elasticity_data": [
                {
                    "drop_pct": float,          # % indirim (negatif)
                    "avg_revenue_after": float, # sonraki 60dk ortalama gelir
                    "sample_count": int,
                    "effective": bool,          # gelir > 0 ise
                }
            ],
            "recommendation": str,
            "optimal_drop_pct": float | None,
        }
    """
    # Silver katmanını kullanıyoruz:
    #   - price_change_pct ve direction Silver'da zaten hesaplı (REGEXP gerekmez)
    #   - sale_id Silver'da mevcut (join için)
    #
    # date = {today} filtresi — Hive partition pruning:
    #   Bronze her gün DynamoDB'yi TAM tarar (incremental değil), yani en son
    #   partition (bugün) zaten tüm geçmişi içeriyor. Bu filtre olmadan Athena
    #   partition projection range'indeki (2026-01-01,NOW) TÜM günlere bakıp
    #   binlerce gereksiz S3 LIST isteği atıyordu — gerçek fatura sebebiydi.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sql = f"""
    WITH price_drops AS (
        SELECT
            timestamp AS drop_time,
            ROUND(price_change_pct, 1) AS drop_pct
        FROM heweso_analytics.silver_price_actions
        WHERE product_id = '{product_id}'
          AND direction = 'DOWN'
          AND date = '{today}'
    ),
    revenue_after AS (
        SELECT
            p.drop_pct,
            p.drop_time,
            COALESCE(SUM(s.revenue), 0) AS revenue_sum
        FROM price_drops p
        LEFT JOIN heweso_analytics.silver_sales_enriched s
            ON s.product_id = '{product_id}'
            AND s.date = '{today}'
            AND s.timestamp >= p.drop_time
            AND s.timestamp <= date_add('minute', 60, from_iso8601_timestamp(p.drop_time))
        GROUP BY p.drop_pct, p.drop_time
    )
    SELECT
        drop_pct,
        ROUND(AVG(revenue_sum), 2) AS avg_revenue,
        COUNT(*) AS sample_count
    FROM revenue_after
    GROUP BY drop_pct
    ORDER BY drop_pct DESC
    """

    result = run_analytics(sql, max_rows=20)

    if not result["success"] or not result["rows"]:
        return {
            "success": False,
            "product_id": product_id,
            "elasticity_data": [],
            "recommendation": "Not enough historical data to analyze price elasticity.",
            "optimal_drop_pct": None,
        }

    elasticity_data = []
    best_drop_pct   = None
    best_revenue    = 0.0
    best_sample_cnt = 0

    for row in result["rows"]:
        try:
            drop_pct    = float(row[0])
            avg_revenue = float(row[1])
            sample_cnt  = int(row[2])
            effective   = avg_revenue > 0

            elasticity_data.append({
                "drop_pct":          drop_pct,
                "avg_revenue_after": avg_revenue,
                "sample_count":      sample_cnt,
                "effective":         effective,
            })

            if effective and avg_revenue > best_revenue:
                best_revenue    = avg_revenue
                best_drop_pct   = drop_pct
                best_sample_cnt = sample_cnt
        except (ValueError, TypeError):
            continue

    # Güven skoru: kaç örnekten öğrenildi?
    if best_drop_pct is None:
        confidence      = "none"
        confidence_note = "No revenue-positive price drop in history. Fall back to competitor match."
        rec             = "Historical data available but no revenue-positive price drop found yet. Match competitor price."
    elif best_sample_cnt < 3:
        confidence      = "low"
        confidence_note = (
            f"Only {best_sample_cnt} sample(s) — too few to trust. "
            f"Ignore elasticity recommendation, match competitor price instead."
        )
        rec = (
            f"Insufficient data ({best_sample_cnt} sample(s)). "
            f"Do NOT apply elasticity target — match competitor price instead."
        )
        best_drop_pct = None  # model'e geçirilmeyecek
    elif best_sample_cnt < 10:
        confidence      = "medium"
        confidence_note = (
            f"{best_sample_cnt} samples — moderate confidence. "
            f"Apply elasticity but prefer competitor if gap is small."
        )
        rec = (
            f"Based on {best_sample_cnt} price change(s): "
            f"a {abs(best_drop_pct):.1f}% drop led to avg ${best_revenue:,.2f} revenue in the following 60 min. "
            f"Medium confidence — apply if competitor gap allows."
        )
    else:
        confidence      = "high"
        confidence_note = (
            f"{best_sample_cnt} samples — high confidence. "
            f"Elasticity recommendation is reliable."
        )
        rec = (
            f"Based on {best_sample_cnt} price change(s): "
            f"a {abs(best_drop_pct):.1f}% drop led to avg ${best_revenue:,.2f} revenue in the following 60 min. "
            f"High confidence — apply elasticity target."
        )

    return {
        "success":          True,
        "product_id":       product_id,
        "elasticity_data":  elasticity_data,
        "recommendation":   rec,
        "optimal_drop_pct": best_drop_pct,
        "confidence":       confidence,
        "confidence_note":  confidence_note,
    }


if __name__ == "__main__":
    for pid in ["PROD-001", "PROD-002", "PROD-003"]:
        r = analyze_price_elasticity(pid)
        print(f"\n{pid}: {r['recommendation']}")
        for d in r.get("elasticity_data", []):
            print(f"  {d['drop_pct']:+.1f}% → avg ${d['avg_revenue_after']:,.2f} revenue (n={d['sample_count']}) {'✅' if d['effective'] else '❌'}")
