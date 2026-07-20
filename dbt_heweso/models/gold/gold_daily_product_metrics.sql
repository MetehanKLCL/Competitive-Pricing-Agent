-- Gold: Ürün başına GÜNLÜK satış + fiyat özeti (event-date bazlı)
-- Python karşılığı: infrastructure/medallion/gold.py -> build_daily_product_metrics()
--
-- ÖNEMLİ: snapshot (partition) tarihine göre DEĞİL, satırın kendi OLAY tarihine
-- (sale_date/action_date) göre gruplarız. Bronze full-scan olduğu için snapshot'a
-- göre gruplamak kümülatif/çift-sayıma yol açardı. Bkz. gold.py başındaki uzun not.

{{ config(materialized='table') }}

with sales_agg as (
    select
        sale_date,
        product_id,
        max(product_name)            as product_name,
        max(category)                as category,
        count(*)                     as total_sales,
        round(sum(revenue), 2)       as total_revenue,
        round(avg(price_at_sale), 2) as avg_price,
        min(price_at_sale)           as min_price,
        max(price_at_sale)           as max_price
    from {{ ref('silver_sales_enriched') }}
    group by sale_date, product_id
),

price_agg as (
    select
        action_date,
        product_id,
        count(*)                                            as price_changes,
        sum(case when direction = 'DOWN' then 1 else 0 end) as price_drops,
        sum(case when direction = 'UP' then 1 else 0 end)   as price_recoveries
    from {{ ref('silver_price_actions') }}
    group by action_date, product_id
)

select
    coalesce(s.sale_date, pr.action_date)   as date,
    coalesce(s.product_id, pr.product_id)   as product_id,
    s.product_name,
    s.category,
    coalesce(s.total_sales, 0)              as total_sales,
    coalesce(s.total_revenue, 0.0)          as total_revenue,
    coalesce(s.avg_price, 0.0)              as avg_price,
    coalesce(s.min_price, 0.0)              as min_price,
    coalesce(s.max_price, 0.0)              as max_price,
    coalesce(pr.price_changes, 0)           as price_changes,
    coalesce(pr.price_drops, 0)             as price_drops,
    coalesce(pr.price_recoveries, 0)        as price_recoveries
from sales_agg s
full outer join price_agg pr
    on s.product_id = pr.product_id
    and s.sale_date = pr.action_date
