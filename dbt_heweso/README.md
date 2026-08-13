# dbt_heweso — Ne, Neden, Nasıl

Bu dosya dbt projesinin neden var olduğunu, hangi dosyanın ne işe yaradığını
ve komutları çalıştırınca arka planda ne olduğunu anlatır.

---

## Bu proje neden var

Ana pricing agent (Bedrock, `agent/bedrock_agent.py`) 7/24 otonom çalışıyor,
EventBridge her dakika tetikliyor — bu hiç değişmedi, dbt bu döngüye hiç girmiyor.

Ayrıca **Bronze → Silver → Gold** dönüşümü zaten Python ile otomatik çalışıyordu
(`infrastructure/medallion/silver.py`, `gold.py`, Lambda saat başı tetikliyor).
`dbt_heweso/` bu dönüşümün **SQL ile yazılmış paralel versiyonu** — aynı işi
Python yerine SQL ile, Athena'nın içinde yapıyor. Şu an manuel çalıştırılıyor
(`dbt run`), Ağustos'ta GitHub Actions kurulunca otomatikleşecek.

Python versiyonu hâlâ **canlı sistem** — Lambda'da otomatik çalışan asıl bu.
dbt versiyonu paralel bir gösterim/tooling katmanı, dbt'nin endüstri
standardı olduğunu göstermek için.

---

## Dosya haritası

```
Competitive-Pricing-Agent/
├── requirements.txt              ← dbt-core, dbt-athena-community eklendi
├── .gitignore                    ← dbt_heweso/target, logs, dbt_packages eklendi
├── dbt_heweso/                   ← BU PROJE
│   ├── README.md                  ← bu dosya
│   ├── dbt_project.yml            ← proje kimliği, hangi profili kullanacağı
│   └── models/
│       ├── sources.yml            ← Bronze tablolarını tanıtır (dbt bunlara dokunmaz)
│       ├── silver/
│       │   ├── silver_sales_enriched.sql
│       │   ├── silver_price_actions.sql
│       │   ├── silver_competitor_gaps.sql
│       │   └── schema.yml         ← Silver testleri
│       └── gold/
│           ├── gold_daily_product_metrics.sql
│           ├── gold_agent_performance.sql
│           ├── gold_bundle_effectiveness.sql
│           └── schema.yml         ← Gold testleri
└── (proje dışında) ~/.dbt/profiles.yml   ← Athena bağlantı ayarları
```

---

## `requirements.txt` — ne indirdik

```
dbt-core>=1.8.0
dbt-athena-community>=1.8.0
```

- **dbt-core:** dbt'nin kendisi. `dbt run`, `dbt test` komutlarını çalıştıran
  motor. Jinja şablon işleme, bağımlılık grafiği (DAG) çözme, test çalıştırma
  mantığı burada — hiçbir veritabanına özel değil.
- **dbt-athena-community:** "adapter". dbt-core tek başına Athena'yı bilmiyor,
  bu paket "Athena'ya nasıl bağlanılır, nasıl SQL gönderilir, nasıl tablo
  oluşturulur" bilgisini ekliyor. Snowflake kullansaydık `dbt-snowflake`
  kurardık. **dbt-core = motor, adapter = hangi arabaya takıldığı.**

---

## `~/.dbt/profiles.yml` — bağlantı bilgisi

```yaml
heweso:
  target: dev
  outputs:
    dev:
      type: athena
      region_name: eu-central-1
      s3_staging_dir: s3://heweso-data-lake/athena-results/
      s3_data_dir: s3://heweso-data-lake/dbt/
      s3_data_naming: schema_table
      work_group: heweso
      database: awsdatacatalog
      schema: heweso_analytics
      threads: 4
```

- **`heweso:`** — profil adı, `dbt_project.yml`'deki `profile: 'heweso'` ile eşleşir.
- **`type: athena`** — hangi adapter kullanılacak.
- **`s3_staging_dir`** — Athena sorgu **sonuçlarının** geçici yazıldığı yer
  (Athena Console'da elle ayarladığın yerle aynı).
- **`s3_data_dir`** — dbt'nin oluşturduğu tabloların **gerçek verisinin**
  yazıldığı yer. Bronze/Silver/Gold klasörlerinden ayrı, yeni bir `/dbt/` klasörü.
- **`work_group: heweso`** — CLAUDE.md'de tanımlı Athena workgroup.
- **`database: awsdatacatalog`** — AWS'nin sabit ismi (Glue Data Catalog).
- **`schema: heweso_analytics`** — asıl veritabanı (Glue database).
- **Kimlik doğrulama belirtmedik** → dbt otomatik olarak `~/.aws/credentials`
  dosyasındaki `[default]` profilini kullanıyor — `export_to_s3.py`'nin
  yaptığı gibi.

Bu dosya proje klasörünün **dışında** durur çünkü credential içerebilir,
git'e karışmasın diye best practice budur.

---

## `dbt_project.yml` — proje kimliği

```yaml
name: 'heweso_pricing'
profile: 'heweso'
model-paths: ["models"]
models:
  heweso_pricing:
    +materialized: table
```

- **`profile: 'heweso'`** — hangi bağlantıyı kullanacağını söyler.
- **`model-paths: ["models"]`** — SQL dosyalarının nerede aranacağını söyler.
- **`+materialized: table`** — **materialization** kavramı:
  - `view` = her sorguda anlık hesaplanır (kaydedilmez, taze ama yavaş)
  - `table` = bir kere hesaplanır, gerçek tabloya yazılır (hızlı okunur,
    ama `dbt run` demeden güncellenmez)

  Biz `table` seçtik çünkü Gold sürekli sorgulanacak (dashboard, elasticity
  analizi) — her seferinde yeniden hesaplamak yavaş olurdu.

---

## `models/sources.yml` — Bronze'u tanıtma

Bu dosya hiçbir tablo oluşturmaz — bir "adres defteri". `setup_glue_tables.py`
zaten `bronze_sales`, `bronze_products` gibi tabloları Athena'da kurmuştu
(boto3 ile, ayrı bir adımda). Bu dosya dbt'ye "bu isimde tablolar zaten var,
sen sadece SELECT ile oku, asla CREATE/DROP yapma" diyor.

SQL modelinde `{{ source('bronze', 'bronze_sales') }}` yazınca, dbt bunu
derleme (compile) anında gerçek isme çevirir:
```
awsdatacatalog.heweso_analytics.bronze_sales
```

Neden direkt tablo adını yazmıyoruz? İleride veritabanı adı değişirse
(örn. `dev`/`prod` ayrı şemalar), tek satır (`sources.yml`) değiştirilir,
6 SQL dosyasının hiçbirine dokunulmaz.

---

## Bir Silver modeli — satır satır (`silver_price_actions.sql`)

```sql
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
    a.log_id, a.timestamp, a.date as action_date,
    hour(from_iso8601_timestamp(a.timestamp)) as action_hour,
    a.product_id, p.name as product_name, p.category, a.action,
    try_cast(a.old_value as double) as old_price,
    try_cast(a.new_value as double) as new_price,
    round(
        (try_cast(a.new_value as double) - try_cast(a.old_value as double))
        / nullif(try_cast(a.old_value as double), 0) * 100, 2
    ) as price_change_pct,
    case
        when try_cast(a.new_value as double) < try_cast(a.old_value as double) then 'DOWN'
        when try_cast(a.new_value as double) > try_cast(a.old_value as double) then 'UP'
        else 'SAME'
    end as direction,
    a.reason, a.agent_decision
from price_actions a
left join products p on a.product_id = p.product_id
```

**Satır satır:**
- `{{ config(...) }}` — bu dosyaya özel materialization ayarı.
- `with audit as (...)` = **CTE** (Common Table Expression). "Bu SQL'e geçici
  bir isim ver, aşağıda kullanayım." Bir çeşit değişken gibi düşün.
  `WHERE date = cast(current_date as varchar)` = "sadece bugünün Bronze
  partition'ını al" — Bronze her gün DynamoDB'nin **tamamını** o günün
  partition'ına yazdığı için, tarih filtresi olmadan aynı satırlar defalarca
  tekrar edip join patlamasına (duplicate satırlar) yol açardı.
- `price_actions` CTE'si — audit log'daki fiyatla ilgili aksiyonları
  filtreler **VE** `product_id`'si gerçek bir üründe olanları alır
  (`in (select product_id from products)`). **Data quality gate tam burada** —
  Python'daki `if a.get("product_id") in product_map` satırının SQL karşılığı.
- Ana `SELECT` — `price_actions` ile `products`'ı `product_id` üzerinden
  birleştirir (JOIN), `price_change_pct` ve `direction` (UP/DOWN/SAME) hesaplar.

Bu SQL'in **tamamı tek bir Athena sorgusu**. dbt başına
`CREATE TABLE heweso_analytics.silver_price_actions AS` ekler, Athena'ya
gönderir, Athena çalıştırır, sonucu yeni bir tablo olarak kaydeder.

---

## `schema.yml` — testler nasıl çalışıyor

Bu dosyalarda SQL yazmıyoruz. `dbt test` çalıştırınca dbt bunları **kendisi
SQL'e çevirip çalıştırıyor.** 4 tip test kullandık:

| Test | Ne demek | Arkada üretilen mantık |
|---|---|---|
| `unique` | Bu kolonda tekrar eden değer olmamalı | `GROUP BY x HAVING COUNT(*) > 1` — satır dönerse FAIL |
| `not_null` | Bu kolon hiç boş olmamalı | `WHERE x IS NULL` — satır dönerse FAIL |
| `relationships` | Bu kolondaki her değer başka tabloda gerçekten var mı | `WHERE product_id NOT IN (SELECT product_id FROM bronze_products)` |
| `accepted_values` | Bu kolon sadece belirtilen değerleri alabilir | `WHERE direction NOT IN ('UP','DOWN','SAME')` |

`dbt test` çıktısında `14 of 14 PASS` görmüştük — 3 Silver + 3 Gold modelde
toplam 14 test, her biri bu 4 tipin bir kombinasyonu.

---

## Komutları çalıştırınca arka planda ne oluyor

**`dbt debug`** — sadece bağlantı testi. `profiles.yml`'i okur, Athena'ya
küçük bir sorgu gönderir, cevap gelirse "All checks passed."

**`dbt run`**
1. `models/` altındaki tüm `.sql` dosyalarını okur
2. `{{ ref() }}` ve `{{ source() }}` referanslarına bakarak bağımlılık
   grafiğini (DAG) çizer:
   ```
   bronze_sales, bronze_products
        ↓
   silver_sales_enriched
        ↓
   gold_daily_product_metrics
   ```
3. Bu sıraya göre her SQL'i gerçek isimlerle derler (Jinja → SQL)
4. Her birini Athena'ya `CREATE TABLE ... AS SELECT ...` olarak gönderir
5. Sonuç: `1 of 6 OK created sql table model...` gibi çıktılar

**`dbt test`** — `schema.yml`'lerdeki her testi SQL'e çevirir, Athena'da
çalıştırır, satır sayısı 0 mı diye bakar, PASS/FAIL raporlar.

**`dbt parse`** — hiçbir AWS bağlantısı kurmadan, sadece dosyaların
söz dizimini (syntax) kontrol eder. Hızlı, local, ücretsiz.

---

## Veri akışı özeti

```
DynamoDB (canlı)
   ↓ Python (export_to_s3.py) — Lambda saat başı otomatik
Bronze (S3, ham JSON, Hive partition: date=YYYY-MM-DD)
   ↓ dbt SQL modelleri — "dbt run" dediğinde
Silver (Athena tablo, temiz + join + data quality gate)
   ↓ dbt SQL modelleri
Gold (Athena tablo, aggregate — dashboard/raporlama burayı sorgular)
   ↓ dbt test — kalite kontrolü, her run sonrası
```

**Bir sorun olursa nereye bakılır:**
- Yanlış hesaplama / eksik join → `models/silver/*.sql` veya `models/gold/*.sql`
- "Bu kolon hep dolu olmalıydı ama boş geliyor" gibi veri kalite sorunu →
  `schema.yml`'lere test ekle, `dbt test` ile yakala
- Bağlantı hatası ("Access Denied" vs.) → `~/.dbt/profiles.yml`
- "Hangi tablo hangisine bağımlı" → `{{ ref() }}` / `{{ source() }}`
  çağrılarını SQL dosyalarında ara

---

## Şu an otomatik mi çalışıyor?

**Hayır, henüz değil.** `dbt run` ve `dbt test` şu an elle çalıştırılıyor.
Python tabanlı Bronze→Silver→Gold pipeline (`infrastructure/medallion/`)
zaten Lambda'da otomatik çalışıyor ve canlı sistem budur.

Ağustos'ta proje GitHub'a taşınınca, `dbt run && dbt test` bir GitHub
Actions cron job'una bağlanabilir (örn. günde bir kez) — böylece dbt de
otomatikleşir, elle çalıştırmaya gerek kalmaz. Bu, gerçek şirketlerde de
yaygın pattern: dbt genelde canlı uygulamanın içinde değil, ayrı bir
scheduler'da (Airflow, dbt Cloud, GitHub Actions) çalışır.
