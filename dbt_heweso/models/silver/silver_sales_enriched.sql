-- silver_sales_enriched — Silver: sales data + product info.
-- What: joins sales with products and computes revenue (quantity * price_at_sale).
-- Why:  agent tools (elasticity, time context) query this; Python equivalent is
--       infrastructure/medallion/silver.py -> transform_sales_enriched().

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
    -- sale_date = the sale's REAL event date (first 10 chars of timestamp),
    -- NOT the Bronze partition column s.date. s.date = the snapshot (photocopy)
    -- day; since Bronze is a full-scan, that day holds all history. We take the
    -- event date from the timestamp so Gold can partition correctly (by event date).
    substr(s.timestamp, 1, 10)                       as sale_date,
    hour(from_iso8601_timestamp(s.timestamp))        as sale_hour,
    s.product_id,
    coalesce(p.name, 'Unknown')                      as product_name,
    coalesce(p.category, 'unknown')                  as category,
    s.quantity,
    s.price_at_sale,
    round(s.quantity * s.price_at_sale, 2)           as revenue,   -- derived field
    s.customer_id
from sales s
left join products p on s.product_id = p.product_id
