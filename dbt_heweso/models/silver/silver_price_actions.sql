-- Silver: Fiyat değişikliklerini filtreleyip zenginleştirir
-- Python karşılığı: infrastructure/medallion/silver.py -> transform_price_actions()
--
-- Data quality gate: product_id gerçek bir üründe yoksa (ör. Nova Lite'ın
-- log_action çağrısında product_id'yi unutup "UNKNOWN" default'una düşmesi)
-- bu kayıt Silver'a hiç girmez. Bronze'da ham hâliyle durmaya devam eder.

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
    -- action_date = fiyat aksiyonunun GERÇEK olay tarihi (timestamp'in ilk 10
    -- karakteri), Bronze partition kolonu a.date DEĞİL (o snapshot/fotokopi günü).
    -- Gold'u doğru event-date partition'layabilmek için burada düzeltiyoruz.
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
    )                                                   as price_change_pct,   -- türetilmiş alan
    case
        when try_cast(a.new_value as double) < try_cast(a.old_value as double) then 'DOWN'
        when try_cast(a.new_value as double) > try_cast(a.old_value as double) then 'UP'
        else 'SAME'
    end                                                 as direction,           -- türetilmiş alan
    try_cast(a.bundle_discount_pct as double)           as bundle_discount_pct, -- yapısal alan (REGEXP yerine kaynaktan)
    a.reason,
    a.agent_decision
from price_actions a
left join products p on a.product_id = p.product_id
