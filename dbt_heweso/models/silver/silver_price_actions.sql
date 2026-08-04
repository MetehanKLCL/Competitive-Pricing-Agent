-- silver_price_actions — Silver: filters and enriches price changes.
-- What: keeps only price-related audit rows and computes price_change_pct/direction.
-- Why:  feeds elasticity/bundle learning; Python equivalent is
--       infrastructure/medallion/silver.py -> transform_price_actions().
--
-- Data quality gate: if product_id doesn't match a real product (e.g. Nova Lite
-- forgetting product_id in a log_action call and falling back to the "UNKNOWN"
-- default), this row never enters Silver. It still remains raw in Bronze.

{{ config(materialized='table') }}

with audit as (
    select * from {{ source('bronze', 'bronze_audit') }}
    where date = cast(current_date as varchar)
),

products as (
    select * from {{ source('bronze', 'bronze_products') }}
    where date = cast(current_date as varchar)
),

price_actions as (
    select *
    from audit
    where (
        lower(action) like '%price%'
        or lower(action) like '%discount%'
        or lower(action) like '%bundle%'
        or lower(action) like '%recovery%'
        or lower(action) like '%crisis%'
    )
    and product_id in (select product_id from products)   -- data quality gate
)

select
    a.log_id,
    a.timestamp,
    -- action_date = the price action's REAL event date (first 10 chars of the
    -- timestamp), NOT the Bronze partition column a.date (that snapshot/photocopy
    -- day). We fix it here so Gold can partition correctly by event date.
    substr(a.timestamp, 1, 10)                        as action_date,
    hour(from_iso8601_timestamp(a.timestamp))          as action_hour,
    a.product_id,
    p.name                                             as product_name,
    p.category,
    a.action,
    try_cast(a.old_value as double)                    as old_price,
    try_cast(a.new_value as double)                     as new_price,
    round(
        (try_cast(a.new_value as double) - try_cast(a.old_value as double))
        / nullif(try_cast(a.old_value as double), 0) * 100, 2
    )                                                   as price_change_pct,   -- derived field
    case
        when try_cast(a.new_value as double) < try_cast(a.old_value as double) then 'DOWN'
        when try_cast(a.new_value as double) > try_cast(a.old_value as double) then 'UP'
        else 'SAME'
    end                                                 as direction,           -- derived field
    try_cast(a.bundle_discount_pct as double)           as bundle_discount_pct, -- structured field (from source, not REGEXP)
    a.reason,
    a.agent_decision
from price_actions a
left join products p on a.product_id = p.product_id
