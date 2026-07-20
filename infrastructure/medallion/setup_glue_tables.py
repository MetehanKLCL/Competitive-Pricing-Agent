"""
setup_glue_tables.py — Medallion katmanları için Athena tablolarını oluşturur.

Bu script TEK SEFER çalıştırılır. Var olan tabloları siler ve yeniden oluşturur.

Oluşturulan tablolar (heweso_analytics DB'de):

  BRONZE katmanı (ham veri, güncellendi — Hive partition + yeni path):
    bronze_sales, bronze_audit, bronze_competitors, bronze_products

  SILVER katmanı (temizlenmiş + join edilmiş, YENİ):
    silver_sales_enriched, silver_price_actions, silver_competitor_gaps

  GOLD katmanı (aggregate, YENİ):
    gold_daily_product_metrics, gold_agent_performance, gold_bundle_effectiveness

  Mevcut tablolar (eski araçlarla uyumluluk için korundu):
    sales, audit_log, competitors, products → artık bronze/ path'e işaret eder

Partition projection nedir:
  Athena, her yeni tarih için manuel olarak "MSCK REPAIR TABLE" çalıştırmak yerine
  tarih aralığını bilirse otomatik olarak ilgili klasörü bulur.
  Burada 2026-01-01'den TODAY'e kadar tüm tarihleri otomatik tarar.

Çalıştırma:
  python3 infrastructure/medallion/setup_glue_tables.py
"""

import os
import time

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION   = os.getenv("AWS_REGION", "eu-central-1")
BUCKET       = "heweso-data-lake"
DATABASE     = "heweso_analytics"
WORKGROUP    = "heweso"
RESULTS_PATH = f"s3://{BUCKET}/athena-results/"

athena = boto3.client("athena", region_name=AWS_REGION)


# ── Athena DDL çalıştırıcı ────────────────────────────────────────────────────

def run_ddl(sql: str, description: str):
    """Athena'da DDL çalıştırır, tamamlanana kadar bekler."""
    print(f"\n  → {description}")
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": RESULTS_PATH},
        WorkGroup=WORKGROUP,
    )
    execution_id = response["QueryExecutionId"]

    # Tamamlanana kadar bekle (max 60 saniye)
    for _ in range(60):
        time.sleep(1)
        status = athena.get_query_execution(QueryExecutionId=execution_id)
        state  = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            print(f"     ✅ OK")
            return True
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            print(f"     ❌ {state}: {reason}")
            return False

    print("     ⏳ Timeout — 60 saniye geçti")
    return False


def drop_table(table_name: str):
    run_ddl(f"DROP TABLE IF EXISTS {DATABASE}.{table_name}", f"DROP {table_name}")


# ── Partition projection config (tüm tablolar için ortak) ─────────────────────
# Athena bu config sayesinde date=YYYY-MM-DD klasörlerini otomatik tarar.
# Yeni gün eklendiğinde MSCK REPAIR TABLE gerekmez.

PARTITION_PROPS = """
  'projection.enabled' = 'true',
  'projection.date.type' = 'date',
  'projection.date.range' = '2026-01-01,NOW',
  'projection.date.format' = 'yyyy-MM-dd',
  'projection.date.interval' = '1',
  'projection.date.interval.unit' = 'DAYS'
"""


# ── BRONZE TABLOLARI ──────────────────────────────────────────────────────────

def create_bronze_sales():
    drop_table("bronze_sales")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.bronze_sales (
      sale_id       STRING,
      timestamp     STRING,
      product_id    STRING,
      quantity      DOUBLE,
      price_at_sale DOUBLE,
      customer_id   STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/sales/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/sales/date=${{date}}/'
    )
    """, "CREATE bronze_sales")


def create_bronze_audit():
    drop_table("bronze_audit")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.bronze_audit (
      log_id              STRING,
      timestamp           STRING,
      product_id          STRING,
      action              STRING,
      old_value           STRING,
      new_value           STRING,
      reason              STRING,
      agent_decision      STRING,
      bundle_discount_pct DOUBLE
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/audit/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/audit/date=${{date}}/'
    )
    """, "CREATE bronze_audit")


def create_bronze_competitors():
    drop_table("bronze_competitors")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.bronze_competitors (
      product_id      STRING,
      competitor_name STRING,
      price           DOUBLE,
      url             STRING,
      last_checked    STRING,
      undercut_since  STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/competitors/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/competitors/date=${{date}}/'
    )
    """, "CREATE bronze_competitors")


def create_bronze_products():
    drop_table("bronze_products")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.bronze_products (
      product_id        STRING,
      name              STRING,
      current_price     DOUBLE,
      base_price        DOUBLE,
      min_price         DOUBLE,
      category          STRING,
      bundle_parent     STRING,
      bundle_accessory  STRING,
      updated_at        STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/products/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/products/date=${{date}}/'
    )
    """, "CREATE bronze_products")


# ── MEVCUT TABLOLARI GÜNCELLE (eski araç uyumluluğu) ─────────────────────────
# analyze_price_elasticity.py, get_time_context.py gibi araçlar
# heweso_analytics.sales ve heweso_analytics.audit_log sorgular.
# Bu tablolar artık bronze/ path'e işaret eder ama isimler aynı kalır.

def update_legacy_sales():
    drop_table("sales")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.sales (
      sale_id       STRING,
      timestamp     STRING,
      product_id    STRING,
      quantity      DOUBLE,
      price_at_sale DOUBLE,
      customer_id   STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/sales/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/sales/date=${{date}}/'
    )
    """, "UPDATE sales → bronze/sales/")


def update_legacy_audit():
    drop_table("audit_log")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.audit_log (
      log_id         STRING,
      timestamp      STRING,
      product_id     STRING,
      action         STRING,
      old_value      STRING,
      new_value      STRING,
      reason         STRING,
      agent_decision STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/bronze/audit/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/bronze/audit/date=${{date}}/'
    )
    """, "UPDATE audit_log → bronze/audit/")


# ── SILVER TABLOLARI ──────────────────────────────────────────────────────────

def create_silver_sales_enriched():
    drop_table("silver_sales_enriched")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.silver_sales_enriched (
      sale_id       STRING,
      timestamp     STRING,
      sale_date     STRING,
      sale_hour     INT,
      product_id    STRING,
      product_name  STRING,
      category      STRING,
      quantity      DOUBLE,
      price_at_sale DOUBLE,
      revenue       DOUBLE,
      customer_id   STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/silver/sales_enriched/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/silver/sales_enriched/date=${{date}}/'
    )
    """, "CREATE silver_sales_enriched")


def create_silver_price_actions():
    drop_table("silver_price_actions")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.silver_price_actions (
      log_id           STRING,
      timestamp        STRING,
      action_date      STRING,
      action_hour      INT,
      product_id       STRING,
      product_name     STRING,
      category         STRING,
      action           STRING,
      old_price        DOUBLE,
      new_price        DOUBLE,
      price_change_pct DOUBLE,
      direction        STRING,
      bundle_discount_pct DOUBLE,
      reason           STRING,
      agent_decision   STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/silver/price_actions/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/silver/price_actions/date=${{date}}/'
    )
    """, "CREATE silver_price_actions")


def create_silver_competitor_gaps():
    drop_table("silver_competitor_gaps")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.silver_competitor_gaps (
      product_id       STRING,
      product_name     STRING,
      category         STRING,
      competitor       STRING,
      our_price        DOUBLE,
      competitor_price DOUBLE,
      price_gap        DOUBLE,
      gap_pct          DOUBLE,
      we_are_cheaper   BOOLEAN,
      undercut_since   STRING,
      last_checked     STRING,
      snapshot_date    STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/silver/competitor_gaps/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/silver/competitor_gaps/date=${{date}}/'
    )
    """, "CREATE silver_competitor_gaps")


# ── GOLD TABLOLARI ────────────────────────────────────────────────────────────

def create_gold_daily_product_metrics():
    drop_table("gold_daily_product_metrics")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.gold_daily_product_metrics (
      product_id       STRING,
      product_name     STRING,
      category         STRING,
      total_sales      BIGINT,
      total_revenue    DOUBLE,
      avg_price        DOUBLE,
      min_price        DOUBLE,
      max_price        DOUBLE,
      price_changes    INT,
      price_drops      INT,
      price_recoveries INT
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/gold/daily_product_metrics/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/gold/daily_product_metrics/date=${{date}}/'
    )
    """, "CREATE gold_daily_product_metrics")


def create_gold_agent_performance():
    drop_table("gold_agent_performance")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.gold_agent_performance (
      product_id       STRING,
      product_name     STRING,
      category         STRING,
      total_decisions  INT,
      price_drops      INT,
      price_recoveries INT,
      bundle_discounts INT,
      escalations      INT,
      avg_drop_pct     DOUBLE
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/gold/agent_performance/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/gold/agent_performance/date=${{date}}/'
    )
    """, "CREATE gold_agent_performance")


def create_gold_bundle_effectiveness():
    drop_table("gold_bundle_effectiveness")
    run_ddl(f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {DATABASE}.gold_bundle_effectiveness (
      product_id           STRING,
      product_name         STRING,
      bundle_triggers      INT,
      avg_discount_pct     DOUBLE,
      sales_after_discount INT,
      effectiveness        STRING
    )
    PARTITIONED BY (date STRING)
    ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
    LOCATION 's3://{BUCKET}/gold/bundle_effectiveness/'
    TBLPROPERTIES (
      {PARTITION_PROPS},
      'storage.location.template' = 's3://{BUCKET}/gold/bundle_effectiveness/date=${{date}}/'
    )
    """, "CREATE gold_bundle_effectiveness")


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def setup_all():
    print("=" * 60)
    print("Medallion Architecture — Athena Tablo Kurulumu")
    print("=" * 60)

    print("\n📦 BRONZE tabloları (ham veri, Hive partition):")
    create_bronze_sales()
    create_bronze_audit()
    create_bronze_competitors()
    create_bronze_products()

    print("\n🔄 Mevcut tablolar güncelleniyor (eski araç uyumluluğu):")
    update_legacy_sales()
    update_legacy_audit()

    print("\n🥈 SILVER tabloları (temizlenmiş + join):")
    create_silver_sales_enriched()
    create_silver_price_actions()
    create_silver_competitor_gaps()

    print("\n🥇 GOLD tabloları (aggregate + iş soruları):")
    create_gold_daily_product_metrics()
    create_gold_agent_performance()
    create_gold_bundle_effectiveness()

    print("\n" + "=" * 60)
    print("✅ Kurulum tamamlandı!")
    print("   Sonraki adım: python3 infrastructure/export_to_s3.py")
    print("   Ardından:     python3 infrastructure/medallion/silver.py")
    print("   Ardından:     python3 infrastructure/medallion/gold.py")
    print("=" * 60)


if __name__ == "__main__":
    setup_all()
