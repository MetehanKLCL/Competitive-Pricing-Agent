-- Singular test: (date, product_id) gold_agent_performance'ta benzersiz olmalı.
-- 0 satır dönerse test GEÇER, satır dönerse BAŞARISIZ.
select
    date,
    product_id,
    count(*) as n
from {{ ref('gold_agent_performance') }}
group by date, product_id
having count(*) > 1
