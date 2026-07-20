-- Silver: Rakip fiyatları vs bizim fiyatlarımız (fark hesaplı)
-- Python karşılığı: infrastructure/medallion/silver.py -> transform_competitor_gaps()

{{ config(materialized='table') }}

with competitors as (
    select * from {{ source('bronze', 'bronze_competitors') }}
    where date = cast(current_date as varchar)
),

products as (
    select * from {{ source('bronze', 'bronze_products') }}
    where date = cast(current_date as varchar)
)

select
    c.product_id,
    p.name                                                       as product_name,
    p.category,
    c.competitor_name                                            as competitor,
    p.current_price                                              as our_price,
    c.price                                                       as competitor_price,
    round(p.current_price - c.price, 2)                          as price_gap,    -- pozitif = biz pahalıyız
    round((p.current_price - c.price) / nullif(c.price, 0) * 100, 2) as gap_pct,
    p.current_price < c.price                                    as we_are_cheaper,
    c.undercut_since,
    c.last_checked,
    c.date                                                        as snapshot_date
from competitors c
left join products p on c.product_id = p.product_id
