-- Silver: Satış verisi + ürün bilgisi (join edilmiş, revenue hesaplı)
-- Python karşılığı: infrastructure/medallion/silver.py -> transform_sales_enriched()

{{ config(materialized='table') }}

with sales as (
    select * from {{ source('bronze', 'bronze_sales') }}
    where date = cast(current_date as varchar)
),

products as (
    select * from {{ source('bronze', 'bronze_products') }}
    where date = cast(current_date as varchar)
)

select
    s.sale_id,
    s.timestamp,
    -- sale_date = satışın GERÇEK olay tarihi (timestamp'in ilk 10 karakteri),
    -- Bronze partition kolonu s.date DEĞİL. s.date = snapshot (fotokopi) günü;
    -- Bronze full-scan olduğu için o gün tüm geçmişi içerir. Gold'u doğru
    -- (event-date) partition'layabilmek için olay tarihini timestamp'ten alıyoruz.
    substr(s.timestamp, 1, 10)                       as sale_date,
    hour(from_iso8601_timestamp(s.timestamp))        as sale_hour,
    s.product_id,
    coalesce(p.name, 'Unknown')                      as product_name,
    coalesce(p.category, 'unknown')                  as category,
    s.quantity,
    s.price_at_sale,
    round(s.quantity * s.price_at_sale, 2)           as revenue,   -- türetilmiş alan
    s.customer_id
from sales s
left join products p on s.product_id = p.product_id
