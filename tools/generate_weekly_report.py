"""
generate_weekly_report — Builds a weekly HTML analytics report from GOLD tables.

Neden artık Gold (eskiden Silver'dı):
  Gold event-date'e göre partition'landığı için (bkz. gold.py başındaki not),
  her `date=` partition'ı artık gerçekten O GÜNÜN verisini içerir — kümülatif
  değil. Yani N günü toplamak güvenli, çift-sayım yok. Bu, Medallion mimarisinin
  amaçladığı akış: raporlar Gold'dan beslenir. "Son N gün" penceresini de
  `date` partition kolonuna göre süzeriz (partition pruning — Athena sadece
  ilgili günleri tarar, ucuz).

  (Tarihçe: Gold kümülatifken rapor Silver'ı okuyup timestamp'i elle parse
  ediyordu — bu bir workaround'du. Gold düzeldiği için kaldırıldı.)

Tüm SAYISAL hesaplamalar SQL/Python'da yapılır (Nova Lite matematik
hatası yapabildiği için — bkz. decide_price.py). AI sadece rapor
metnini yorumlar, sayı üretmez.
"""

from datetime import datetime, timezone

from .run_analytics import run_analytics

DATABASE = "heweso_analytics"


# Not: Gold zaten (date, product_id) bazında günlük aggregate. Haftalık rapor için
# günleri ürün bazında toplarız (sum). `date` partition kolonu 'YYYY-MM-DD' string
# olduğu için son N gün filtresi leksikografik karşılaştırmayla doğru çalışır ve
# Athena sadece ilgili partition'ları tarar (partition pruning).
def _cutoff(days: int) -> str:
    # 'date >= cutoff' için son N günün başlangıç tarihi (YYYY-MM-DD)
    return f"cast(date_add('day', -{days}, current_date) as varchar)"


def _sales_summary_sql(days: int) -> str:
    return f"""
    SELECT
        product_id,
        max(product_name) as product_name,
        max(category) as category,
        sum(total_sales) as total_sales,
        round(sum(total_revenue), 2) as total_revenue,
        round(avg(avg_price), 2) as avg_price
    FROM {DATABASE}.gold_daily_product_metrics
    WHERE date >= {_cutoff(days)}
    GROUP BY product_id
    ORDER BY total_revenue DESC
    """


def _price_actions_summary_sql(days: int) -> str:
    return f"""
    SELECT
        product_id,
        max(product_name) as product_name,
        sum(total_decisions) as total_decisions,
        sum(price_drops) as price_drops,
        sum(price_recoveries) as price_recoveries,
        sum(bundle_discounts) as bundle_discounts,
        sum(escalations) as escalations,
        round(avg(avg_drop_pct), 2) as avg_drop_pct
    FROM {DATABASE}.gold_agent_performance
    WHERE date >= {_cutoff(days)}
    GROUP BY product_id
    ORDER BY total_decisions DESC
    """


def _bundle_summary_sql(days: int) -> str:
    return f"""
    SELECT
        product_id,
        max(product_name) as product_name,
        sum(bundle_triggers) as bundle_triggers,
        round(avg(avg_discount_pct), 2) as avg_discount_pct
    FROM {DATABASE}.gold_bundle_effectiveness
    WHERE date >= {_cutoff(days)}
    GROUP BY product_id
    """


def _rows_to_dicts(result: dict) -> list:
    if not result["success"]:
        return []
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]


def _fmt(val, default="0"):
    return val if val not in (None, "", "None") else default


def generate_weekly_report(days: int = 7) -> dict:
    """
    Son N günün satış, fiyat aksiyonu ve bundle özetini Gold'dan çeker,
    HTML rapor üretir.

    Returns:
        {
            "success": bool,
            "html": str,             # tam HTML rapor (email'e gömülür)
            "stats_summary": str,    # AI narrative'e verilecek düz metin özet
            "total_revenue": float,
            "total_sales": int,
            "total_price_changes": int,
            "period_days": int,
        }
    """
    sales_rows  = _rows_to_dicts(run_analytics(_sales_summary_sql(days), max_rows=20))
    action_rows = _rows_to_dicts(run_analytics(_price_actions_summary_sql(days), max_rows=20))
    bundle_rows = _rows_to_dicts(run_analytics(_bundle_summary_sql(days), max_rows=20))

    total_revenue = round(sum(float(_fmt(r.get("total_revenue"), 0)) for r in sales_rows), 2)
    total_sales   = sum(int(_fmt(r.get("total_sales"), 0)) for r in sales_rows)
    total_changes = sum(int(_fmt(r.get("total_decisions"), 0)) for r in action_rows)
    total_escal   = sum(int(_fmt(r.get("escalations"), 0)) for r in action_rows)

    html = _build_html(sales_rows, action_rows, bundle_rows, days, total_revenue, total_sales, total_changes)

    stats_summary = (
        f"Last {days} days: {total_sales} sales, ${total_revenue} revenue, "
        f"{total_changes} price actions ({total_escal} escalations). "
        f"Products: " + ", ".join(
            f"{r.get('product_name')} (${_fmt(r.get('total_revenue'))})" for r in sales_rows
        )
    )

    return {
        "success": True,
        "html": html,
        "stats_summary": stats_summary,
        "total_revenue": total_revenue,
        "total_sales": total_sales,
        "total_price_changes": total_changes,
        "period_days": days,
    }


def _build_html(sales_rows, action_rows, bundle_rows, days, total_revenue, total_sales, total_changes) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def sales_table_rows():
        if not sales_rows:
            return "<tr><td colspan='5'>No sales in this period.</td></tr>"
        return "".join(
            f"<tr><td>{r.get('product_name')}</td><td>{r.get('category')}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('total_sales'))}</td>"
            f"<td style='text-align:right'>${_fmt(r.get('total_revenue'))}</td>"
            f"<td style='text-align:right'>${_fmt(r.get('avg_price'))}</td></tr>"
            for r in sales_rows
        )

    def actions_table_rows():
        if not action_rows:
            return "<tr><td colspan='6'>No price actions in this period.</td></tr>"
        return "".join(
            f"<tr><td>{r.get('product_name')}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('total_decisions'))}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('price_drops'))}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('price_recoveries'))}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('bundle_discounts'))}</td>"
            f"<td style='text-align:right;color:{'#c0392b' if int(_fmt(r.get('escalations'))) else '#333'}'>"
            f"{_fmt(r.get('escalations'))}</td></tr>"
            for r in action_rows
        )

    def bundle_table_rows():
        if not bundle_rows:
            return "<tr><td colspan='3'>No bundle discounts triggered in this period.</td></tr>"
        return "".join(
            f"<tr><td>{r.get('product_name')}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('bundle_triggers'))}</td>"
            f"<td style='text-align:right'>{_fmt(r.get('avg_discount_pct'))}%</td></tr>"
            for r in bundle_rows
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Heweso Weekly Analytics Report</title></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:24px;color:#222">
  <h2 style="color:#2c3e50">📊 Heweso Weekly Analytics Report</h2>
  <p style="color:#888">Period: last {days} days — generated {today}</p>

  <div style="display:flex;gap:16px;margin:20px 0">
    <div style="flex:1;background:#f4f8fb;padding:14px;border-radius:6px;text-align:center">
      <div style="font-size:22px;font-weight:bold;color:#2c3e50">{total_sales}</div>
      <div style="font-size:12px;color:#888">Total Sales</div>
    </div>
    <div style="flex:1;background:#f4f8fb;padding:14px;border-radius:6px;text-align:center">
      <div style="font-size:22px;font-weight:bold;color:#27ae60">${total_revenue}</div>
      <div style="font-size:12px;color:#888">Total Revenue</div>
    </div>
    <div style="flex:1;background:#f4f8fb;padding:14px;border-radius:6px;text-align:center">
      <div style="font-size:22px;font-weight:bold;color:#2980b9">{total_changes}</div>
      <div style="font-size:12px;color:#888">Price Actions</div>
    </div>
  </div>

  <!-- AI_INSIGHT -->

  <h3>Sales by Product</h3>
  <table style="width:100%;border-collapse:collapse" cellpadding="6">
    <tr style="background:#2c3e50;color:white">
      <th style="text-align:left">Product</th><th style="text-align:left">Category</th>
      <th style="text-align:right">Sales</th><th style="text-align:right">Revenue</th>
      <th style="text-align:right">Avg Price</th>
    </tr>
    {sales_table_rows()}
  </table>

  <h3>Agent Price Actions</h3>
  <table style="width:100%;border-collapse:collapse" cellpadding="6">
    <tr style="background:#2c3e50;color:white">
      <th style="text-align:left">Product</th><th style="text-align:right">Decisions</th>
      <th style="text-align:right">Drops</th><th style="text-align:right">Recoveries</th>
      <th style="text-align:right">Bundles</th><th style="text-align:right">Escalations</th>
    </tr>
    {actions_table_rows()}
  </table>

  <h3>Bundle Discount Effectiveness</h3>
  <table style="width:100%;border-collapse:collapse" cellpadding="6">
    <tr style="background:#2c3e50;color:white">
      <th style="text-align:left">Product</th><th style="text-align:right">Triggers</th>
      <th style="text-align:right">Avg Discount</th>
    </tr>
    {bundle_table_rows()}
  </table>

  <p style="color:#888;font-size:12px;margin-top:24px">
    This report was automatically generated by the Heweso autonomous pricing agent's analytics reporter.
  </p>
</body>
</html>"""


if __name__ == "__main__":
    result = generate_weekly_report(days=7)
    print(result["stats_summary"])
