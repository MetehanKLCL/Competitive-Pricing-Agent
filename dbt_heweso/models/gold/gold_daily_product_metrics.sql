-- gold_daily_product_metrics — Gold: DAILY sales + price summary per product (by event date).
-- What: aggregates sales and price actions per (event_date, product_id).
-- Why:  Python equivalent is infrastructure/medallion/gold.py -> build_daily_product_metrics().
--
-- IMPORTANT: we group by the row's own EVENT date (sale_date/action_date), NOT
-- the snapshot (partition) date. Because Bronze is a full-scan, grouping by the
-- snapshot would cause cumulative/double-counting. See the long note atop gold.py.

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
