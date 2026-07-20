-- Singular test: (date, product_id) gold_daily_product_metrics'te benzersiz olmalı.
-- Event-date fix sonrası ürün başına birden çok gün satırı var; ama gün+ürün ikilisi
-- tekil kalmalı (yoksa çift-sayım geri gelmiş demektir).
-- dbt kuralı: bu sorgu 0 satır dönerse test GEÇER, satır dönerse BAŞARISIZ.
select
    date,
    product_id,
    count(*) as n
from {{ ref('gold_daily_product_metrics') }}
group by date, product_id
having count(*) > 1
