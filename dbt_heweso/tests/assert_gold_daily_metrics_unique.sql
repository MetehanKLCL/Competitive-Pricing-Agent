-- Singular test: (date, product_id) must be unique in gold_daily_product_metrics.
-- After the event-date fix there are multiple day rows per product; but the
-- day+product pair must stay unique (otherwise double-counting has come back).
-- dbt rule: if this query returns 0 rows the test PASSES, if it returns rows it FAILS.
select
    date,
    product_id,
    count(*) as n
from {{ ref('gold_daily_product_metrics') }}
group by date, product_id
having count(*) > 1
