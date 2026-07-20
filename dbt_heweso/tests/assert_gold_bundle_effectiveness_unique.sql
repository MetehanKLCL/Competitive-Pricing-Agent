-- Singular test: (date, product_id) gold_bundle_effectiveness'te benzersiz olmalı.
-- 0 satır dönerse test GEÇER, satır dönerse BAŞARISIZ.
select
    date,
    product_id,
    count(*) as n
from {{ ref('gold_bundle_effectiveness') }}
group by date, product_id
having count(*) > 1
