-- Gold: Bundle indirimlerinin satışa etkisi (epsilon-greedy öğrenme sonuçları)
-- Python karşılığı: infrastructure/medallion/gold.py -> build_bundle_effectiveness()
--
-- Event-date bazlı: bundle aksiyonu ile o günkü satışlar aynı OLAY tarihinde
-- (action_date = sale_date) eşleşir; snapshot tarihine göre değil.

{{ config(materialized='table') }}

with bundle_actions as (
    select *
    from {{ ref('silver_price_actions') }}
    where lower(action) like '%bundle%'
),

sales as (
    select
        sale_date,
        product_id,
        sum(quantity) as sales_count
    from {{ ref('silver_sales_enriched') }}
    group by sale_date, product_id
)

select
    b.action_date                                                  as date,
    b.product_id,
    max(b.product_name)                                            as product_name,
    count(*)                                                        as bundle_triggers,
    round(avg(abs(b.price_change_pct)), 2)                        as avg_discount_pct,
    coalesce(max(s.sales_count), 0)                                as sales_after_discount,
    case
        when coalesce(max(s.sales_count), 0) >= 3 then 'HIGH'
        when coalesce(max(s.sales_count), 0) >= 1 then 'MEDIUM'
        else 'LOW'
    end                                                              as effectiveness
from bundle_actions b
left join sales s
    on b.product_id = s.product_id
    and b.action_date = s.sale_date
group by b.action_date, b.product_id
