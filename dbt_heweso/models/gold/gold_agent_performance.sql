-- gold_agent_performance — Gold: the agent's DAILY decision summary (drops, bundles, escalations).
-- What: aggregates price actions per (action_date, product_id) into decision counts.
-- Why:  Python equivalent is infrastructure/medallion/gold.py -> build_agent_performance().
--
-- By event date: action_date = the action's real event date (not the snapshot).

{{ config(materialized='table') }}

select
    action_date                                                        as date,
    product_id,
    max(product_name)                                                  as product_name,
    max(category)                                                      as category,
    count(*)                                                            as total_decisions,
    sum(case when direction = 'DOWN' then 1 else 0 end)                as price_drops,
    sum(case when direction = 'UP' then 1 else 0 end)                  as price_recoveries,
    sum(case when lower(action) like '%bundle%' then 1 else 0 end)     as bundle_discounts,
    sum(case when lower(action) like '%escalat%' then 1 else 0 end)    as escalations,
    round(avg(case when direction = 'DOWN' then abs(price_change_pct) end), 2) as avg_drop_pct
from {{ ref('silver_price_actions') }}
group by action_date, product_id
