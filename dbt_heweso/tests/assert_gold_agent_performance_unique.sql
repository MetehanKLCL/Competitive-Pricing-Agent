-- Singular test: (date, product_id) must be unique in gold_agent_performance.
-- If it returns 0 rows the test PASSES, if it returns rows it FAILS.
select
    date,
    product_id,
    count(*) as n
from {{ ref('gold_agent_performance') }}
group by date, product_id
having count(*) > 1
