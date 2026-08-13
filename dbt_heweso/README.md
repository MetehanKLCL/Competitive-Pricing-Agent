# dbt_heweso — What, Why, How

This document explains why the dbt project exists, what each file does, and what
happens behind the scenes when you run the commands.

---

## Why this project exists

The main pricing agent (Bedrock, `agent/bedrock_agent.py`) runs autonomously 24/7,
triggered every minute by EventBridge — that never changed, and dbt is not part of
that loop.

The **Bronze → Silver → Gold** transformation also already ran automatically in
Python (`infrastructure/medallion/silver.py`, `gold.py`, triggered hourly inside the
Lambda). `dbt_heweso/` is a **parallel version of that same transformation written in
SQL** — the same work, done in SQL inside Athena instead of in Python. It is currently
run manually (`dbt run`); see "Is it automated yet?" below.

The Python version is still the **live system** — it's the one running automatically in
the Lambda. The dbt version is a parallel demonstration/tooling layer, built to show
fluency with dbt, the industry standard.

---

## File map

```
Competitive-Pricing-Agent/
├── requirements.txt              ← dbt-core, dbt-athena-community added
├── .gitignore                    ← dbt_heweso/target, logs, dbt_packages added
├── dbt_heweso/                   ← THIS PROJECT
│   ├── README.md                  ← this file
│   ├── dbt_project.yml            ← project identity, which profile it uses
│   └── models/
│       ├── sources.yml            ← declares the Bronze tables (dbt never writes them)
│       ├── silver/
│       │   ├── silver_sales_enriched.sql
│       │   ├── silver_price_actions.sql
│       │   ├── silver_competitor_gaps.sql
│       │   └── schema.yml         ← Silver tests
│       └── gold/
│           ├── gold_daily_product_metrics.sql
│           ├── gold_agent_performance.sql
│           ├── gold_bundle_effectiveness.sql
│           └── schema.yml         ← Gold tests
└── (outside the project) ~/.dbt/profiles.yml   ← Athena connection settings
```

---

## `requirements.txt` — what we installed

```
dbt-core>=1.8.0
dbt-athena-community>=1.8.0
```

- **dbt-core:** dbt itself. The engine that runs `dbt run` / `dbt test`. Jinja
  templating, dependency-graph (DAG) resolution, and test execution all live here —
  none of it is database-specific.
- **dbt-athena-community:** the *adapter*. dbt-core on its own doesn't know Athena;
  this package teaches it "how to connect to Athena, how to send SQL, how to create a
  table." If we used Snowflake we'd install `dbt-snowflake` instead. **dbt-core = the
  engine, the adapter = which car it's bolted into.**

---

## `~/.dbt/profiles.yml` — the connection

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

- **`heweso:`** — the profile name; matches `profile: 'heweso'` in `dbt_project.yml`.
- **`type: athena`** — which adapter to use.
- **`s3_staging_dir`** — where Athena writes **query results** (the same location you
  set by hand in the Athena console).
- **`s3_data_dir`** — where the **actual data** of the tables dbt creates is written.
  A new `/dbt/` folder, kept separate from the Bronze/Silver/Gold folders.
- **`work_group: heweso`** — the Athena workgroup defined for the project.
- **`database: awsdatacatalog`** — AWS's fixed name for the Glue Data Catalog.
- **`schema: heweso_analytics`** — the actual database (Glue database).
- **No credentials specified** → dbt automatically falls back to the `[default]`
  profile in `~/.aws/credentials`, just like `export_to_s3.py` does.

This file lives **outside** the project folder because it can contain credentials —
keeping it out of git is the best-practice default.

---

## `dbt_project.yml` — project identity

```yaml
name: 'heweso_pricing'
profile: 'heweso'
model-paths: ["models"]
models:
  heweso_pricing:
    +materialized: table
```

- **`profile: 'heweso'`** — tells dbt which connection to use.
- **`model-paths: ["models"]`** — where to look for the SQL files.
- **`+materialized: table`** — the **materialization** concept:
  - `view` = recomputed on every query (not stored; always fresh, but slower)
  - `table` = computed once, written to a real table (fast to read, but not refreshed
    until you run `dbt run` again)

  We chose `table` because Gold is queried continuously (dashboard, elasticity
  analysis) — recomputing it every time would be slow.

---

## `models/sources.yml` — declaring Bronze

This file creates no tables — it's an "address book." `setup_glue_tables.py` already
created the `bronze_sales`, `bronze_products` (etc.) tables in Athena (via boto3, in a
separate step). This file tells dbt: "tables with these names already exist; just read
them with SELECT, never CREATE/DROP them."

When a SQL model says `{{ source('bronze', 'bronze_sales') }}`, dbt resolves it at
compile time to the real name:

```
awsdatacatalog.heweso_analytics.bronze_sales
```

Why not just hard-code the table name? If the database name ever changes (e.g.
separate `dev`/`prod` schemas), you edit a single line (`sources.yml`) and touch none
of the 6 SQL files.

---

## A Silver model, line by line (`silver_price_actions.sql`)

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

**Line by line:**
- `{{ config(...) }}` — a per-file materialization setting.
- `with audit as (...)` = a **CTE** (Common Table Expression). "Give this SQL a
  temporary name I can reuse below." Think of it like a variable.
  `WHERE date = cast(current_date as varchar)` = "only take today's Bronze partition" —
  because Bronze writes **all of DynamoDB** into each day's partition, without the date
  filter the same rows would repeat over and over and blow up the join with duplicates.
- the `price_actions` CTE — filters the audit log to price-related actions **and** keeps
  only rows whose `product_id` belongs to a real product
  (`in (select product_id from products)`). **The data-quality gate is right here** — the
  SQL equivalent of the Python `if a.get("product_id") in product_map` line.
- the main `SELECT` — joins `price_actions` with `products` on `product_id`, and
  computes `price_change_pct` and `direction` (UP/DOWN/SAME).

This entire SQL is **a single Athena query**. dbt prepends
`CREATE TABLE heweso_analytics.silver_price_actions AS`, sends it to Athena, Athena
runs it, and the result is saved as a new table.

---

## `schema.yml` — how the tests work

We write no SQL in these files. When you run `dbt test`, dbt **compiles them into SQL
and runs them itself.** We use 4 test types:

| Test | Meaning | Logic generated under the hood |
|---|---|---|
| `unique` | no repeated value in this column | `GROUP BY x HAVING COUNT(*) > 1` — any row returned = FAIL |
| `not_null` | this column is never empty | `WHERE x IS NULL` — any row returned = FAIL |
| `relationships` | every value in this column really exists in another table | `WHERE product_id NOT IN (SELECT product_id FROM bronze_products)` |
| `accepted_values` | this column may only take the listed values | `WHERE direction NOT IN ('UP','DOWN','SAME')` |

The `dbt test` output shows `18 of 18 PASS` — across 3 Silver + 3 Gold models, each test
a combination of these 4 types (plus custom singular composite-key tests under
`tests/`).

---

## What happens behind the scenes when you run the commands

**`dbt debug`** — a connection check only. Reads `profiles.yml`, sends a small query to
Athena, and if it answers, prints "All checks passed."

**`dbt run`**
1. Reads every `.sql` file under `models/`
2. Draws the dependency graph (DAG) from the `{{ ref() }}` and `{{ source() }}`
   references:
   ```
   bronze_sales, bronze_products
        ↓
   silver_sales_enriched
        ↓
   gold_daily_product_metrics
   ```
3. Compiles each SQL to real names in that order (Jinja → SQL)
4. Sends each to Athena as `CREATE TABLE ... AS SELECT ...`
5. Result: output lines like `1 of 6 OK created sql table model...`

**`dbt test`** — compiles each test in the `schema.yml` files into SQL, runs it on
Athena, checks whether the row count is 0, and reports PASS/FAIL.

**`dbt parse`** — checks only the files' syntax, with no AWS connection at all. Fast,
local, free.

---

## Data-flow summary

```
DynamoDB (live)
   ↓ Python (export_to_s3.py) — Lambda, automatic, hourly
Bronze (S3, raw JSON, Hive partitioned: date=YYYY-MM-DD)
   ↓ dbt SQL models — when you run "dbt run"
Silver (Athena table, cleaned + joined + data-quality gate)
   ↓ dbt SQL models
Gold (Athena table, aggregated — the dashboard/reporting queries this)
   ↓ dbt test — quality check, after every run
```

**Where to look when something's wrong:**
- Wrong calculation / missing join → `models/silver/*.sql` or `models/gold/*.sql`
- "This column should always be filled but it's coming back empty" (a data-quality
  issue) → add a test to the `schema.yml` files and catch it with `dbt test`
- Connection error ("Access Denied" etc.) → `~/.dbt/profiles.yml`
- "Which table depends on which" → search the `{{ ref() }}` / `{{ source() }}` calls in
  the SQL files

---

## Is it automated yet?

**No, not yet.** `dbt run` and `dbt test` are currently run by hand. The Python-based
Bronze→Silver→Gold pipeline (`infrastructure/medallion/`) already runs automatically in
the Lambda, and that is the live system.

The planned automation is **AWS-native** (to keep the whole stack AWS-native, not
GitHub Actions): a **container-image Lambda** — dbt's dependencies are too heavy for a
zip package — triggered by an **EventBridge** schedule (e.g. once a day), so dbt runs on
a cron without manual intervention. This mirrors how real companies run dbt: not inside
the live application, but on a separate scheduler (Airflow, dbt Cloud, or here
EventBridge).
