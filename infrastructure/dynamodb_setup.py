"""
DynamoDB table setup and test data seeding.

Tables created:
- heweso-products
- heweso-sales
- heweso-competitor-prices
- heweso-audit-log
"""

import boto3
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
PRODUCTS_TABLE = os.getenv("DYNAMODB_PRODUCTS_TABLE", "heweso-products")
SALES_TABLE = os.getenv("DYNAMODB_SALES_TABLE", "heweso-sales")
COMPETITORS_TABLE = os.getenv("DYNAMODB_COMPETITORS_TABLE", "heweso-competitor-prices")
AUDIT_TABLE = os.getenv("DYNAMODB_AUDIT_TABLE", "heweso-audit-log")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
client = boto3.client("dynamodb", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(table_name: str) -> bool:
    try:
        client.describe_table(TableName=table_name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


def _wait_active(table_name: str) -> None:
    print(f"  Waiting for '{table_name}' to become active...", end=" ", flush=True)
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    print("ready.")


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_products_table() -> None:
    """
    Products table:
      PK: product_id (String)
    """
    if _table_exists(PRODUCTS_TABLE):
        print(f"[SKIP] '{PRODUCTS_TABLE}' already exists.")
        return

    dynamodb.create_table(
        TableName=PRODUCTS_TABLE,
        KeySchema=[
            {"AttributeName": "product_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "product_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    _wait_active(PRODUCTS_TABLE)
    print(f"[OK] '{PRODUCTS_TABLE}' created.")


def create_sales_table() -> None:
    """
    Sales table:
      PK: sale_id (String)
      SK: timestamp (String)
    """
    if _table_exists(SALES_TABLE):
        print(f"[SKIP] '{SALES_TABLE}' already exists.")
        return

    dynamodb.create_table(
        TableName=SALES_TABLE,
        KeySchema=[
            {"AttributeName": "sale_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "sale_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
            {"AttributeName": "product_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "product_id-timestamp-index",
                "KeySchema": [
                    {"AttributeName": "product_id", "KeyType": "HASH"},
                    {"AttributeName": "timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    _wait_active(SALES_TABLE)
    print(f"[OK] '{SALES_TABLE}' created.")


def create_competitors_table() -> None:
    """
    CompetitorPrices table:
      PK: product_id (String)
      SK: competitor_name (String)
    """
    if _table_exists(COMPETITORS_TABLE):
        print(f"[SKIP] '{COMPETITORS_TABLE}' already exists.")
        return

    dynamodb.create_table(
        TableName=COMPETITORS_TABLE,
        KeySchema=[
            {"AttributeName": "product_id", "KeyType": "HASH"},
            {"AttributeName": "competitor_name", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "product_id", "AttributeType": "S"},
            {"AttributeName": "competitor_name", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    _wait_active(COMPETITORS_TABLE)
    print(f"[OK] '{COMPETITORS_TABLE}' created.")


def create_audit_table() -> None:
    """
    AuditLog table:
      PK: log_id (String)
      SK: timestamp (String)
    """
    if _table_exists(AUDIT_TABLE):
        print(f"[SKIP] '{AUDIT_TABLE}' already exists.")
        return

    dynamodb.create_table(
        TableName=AUDIT_TABLE,
        KeySchema=[
            {"AttributeName": "log_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "log_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    _wait_active(AUDIT_TABLE)
    print(f"[OK] '{AUDIT_TABLE}' created.")


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_products() -> None:
    """Loads sample products into the Products table."""
    table = dynamodb.Table(PRODUCTS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    products = [
        {
            "product_id": "PROD-001",
            "name": "iPhone 17 Pro",
            "current_price": Decimal("1099"),
            "base_price": Decimal("1099"),
            "min_price": Decimal("899"),
            "category": "smartphone",
            "bundle_accessory": "PROD-002",
            "updated_at": now,
        },
        {
            "product_id": "PROD-002",
            "name": "AirPods Pro 3",
            "current_price": Decimal("279"),
            "base_price": Decimal("279"),
            "min_price": Decimal("219"),
            "category": "audio",
            "bundle_parent": "PROD-001",
            "updated_at": now,
        },
        {
            "product_id": "PROD-003",
            "name": "Samsung Galaxy S25",
            "current_price": Decimal("899"),
            "base_price": Decimal("899"),
            "min_price": Decimal("729"),
            "category": "smartphone",
            "bundle_accessory": "PROD-004",
            "updated_at": now,
        },
        {
            "product_id": "PROD-004",
            "name": "Samsung Galaxy Buds3 Pro",
            "current_price": Decimal("229"),
            "base_price": Decimal("229"),
            "min_price": Decimal("179"),
            "category": "audio",
            "bundle_parent": "PROD-003",
            "updated_at": now,
        },
    ]

    with table.batch_writer() as batch:
        for product in products:
            batch.put_item(Item=product)

    print(f"[OK] {len(products)} products loaded into '{PRODUCTS_TABLE}'.")


PRODUCT_PRICES = {
    "PROD-001": Decimal("1099"),
    "PROD-002": Decimal("279"),
    "PROD-003": Decimal("899"),
    "PROD-004": Decimal("229"),
}


def clear_sales() -> None:
    """Deletes all sales records for all products."""
    table = dynamodb.Table(SALES_TABLE)
    total = 0
    for product_id in PRODUCT_PRICES:
        response = table.query(
            IndexName="product_id-timestamp-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("product_id").eq(product_id),
        )
        items = response.get("Items", [])
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"sale_id": item["sale_id"], "timestamp": item["timestamp"]})
        total += len(items)
    print(f"[OK] {total} old sales records deleted (all products).")


def seed_sales(healthy: bool = True) -> None:
    """
    Loads sample sales records for all products.

    healthy=True  → sales within last 60 minutes (normal state)
    healthy=False → no sales in last 60 minutes (crisis scenario)
    """
    clear_sales()
    table = dynamodb.Table(SALES_TABLE)
    now = datetime.now(timezone.utc)

    if healthy:
        offsets_per_product = {
            "PROD-001": [5, 12, 25, 38],
            "PROD-002": [8, 22, 45],
            "PROD-003": [10, 28, 50],
            "PROD-004": [15, 40],
        }
        label = "healthy (sales within last 60 min)"
    else:
        offsets_per_product = {
            "PROD-001": [90, 115, 140, 165],
            "PROD-002": [95, 120, 150],
            "PROD-003": [100, 130, 155],
            "PROD-004": [105, 135],
        }
        label = "crisis (no sales in last 60 min)"

    items = []
    for product_id, offsets in offsets_per_product.items():
        price = PRODUCT_PRICES[product_id]
        for minutes_ago in offsets:
            sale_time = now - timedelta(minutes=minutes_ago)
            items.append({
                "sale_id": str(uuid.uuid4()),
                "timestamp": sale_time.isoformat(),
                "product_id": product_id,
                "quantity": Decimal(str(random.randint(1, 3))),
                "price_at_sale": price,
                "customer_id": f"CUST-{uuid.uuid4().hex[:6].upper()}",
            })

    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    print(f"[OK] {len(items)} sales records loaded into '{SALES_TABLE}' ({label}).")


def clear_competitors() -> None:
    """Deletes all competitor price records."""
    table = dynamodb.Table(COMPETITORS_TABLE)
    response = table.scan()
    items = response.get("Items", [])
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={
                "product_id": item["product_id"],
                "competitor_name": item["competitor_name"],
            })
    print(f"[OK] {len(items)} competitor records deleted.")


def seed_competitors() -> None:
    """Loads sample competitor prices into the CompetitorPrices table."""
    clear_competitors()
    table = dynamodb.Table(COMPETITORS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    competitors = [
        # PROD-001: iPhone 17 Pro (our price: $1099)
        {"product_id": "PROD-001", "competitor_name": "Amazon",    "price": Decimal("1059"), "url": "https://amazon.com/iphone-17-pro",   "last_checked": now},
        {"product_id": "PROD-001", "competitor_name": "Best Buy",  "price": Decimal("1079"), "url": "https://bestbuy.com/iphone-17-pro",  "last_checked": now},
        {"product_id": "PROD-001", "competitor_name": "MediaMarkt","price": Decimal("1089"), "url": "https://mediamarkt.com/iphone-17-pro","last_checked": now},
        # PROD-002: AirPods Pro 3 (our price: $279)
        {"product_id": "PROD-002", "competitor_name": "Amazon",    "price": Decimal("259"),  "url": "https://amazon.com/airpods-pro-3",   "last_checked": now},
        {"product_id": "PROD-002", "competitor_name": "Best Buy",  "price": Decimal("269"),  "url": "https://bestbuy.com/airpods-pro-3",  "last_checked": now},
        {"product_id": "PROD-002", "competitor_name": "MediaMarkt","price": Decimal("274"),  "url": "https://mediamarkt.com/airpods-pro-3","last_checked": now},
        # PROD-003: Samsung Galaxy S25 (our price: $899)
        {"product_id": "PROD-003", "competitor_name": "Amazon",    "price": Decimal("869"),  "url": "https://amazon.com/galaxy-s25",      "last_checked": now},
        {"product_id": "PROD-003", "competitor_name": "Best Buy",  "price": Decimal("879"),  "url": "https://bestbuy.com/galaxy-s25",     "last_checked": now},
        {"product_id": "PROD-003", "competitor_name": "MediaMarkt","price": Decimal("889"),  "url": "https://mediamarkt.com/galaxy-s25",  "last_checked": now},
        # PROD-004: Samsung Galaxy Buds3 Pro (our price: $229)
        {"product_id": "PROD-004", "competitor_name": "Amazon",    "price": Decimal("219"),  "url": "https://amazon.com/galaxy-buds3-pro",    "last_checked": now},
        {"product_id": "PROD-004", "competitor_name": "Best Buy",  "price": Decimal("224"),  "url": "https://bestbuy.com/galaxy-buds3-pro",   "last_checked": now},
        {"product_id": "PROD-004", "competitor_name": "MediaMarkt","price": Decimal("226"),  "url": "https://mediamarkt.com/galaxy-buds3-pro","last_checked": now},
    ]

    with table.batch_writer() as batch:
        for item in competitors:
            batch.put_item(Item=item)

    print(f"[OK] {len(competitors)} competitor prices loaded into '{COMPETITORS_TABLE}'.")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def setup_all_tables() -> None:
    print("\n=== Creating DynamoDB Tables ===")
    create_products_table()
    create_sales_table()
    create_competitors_table()
    create_audit_table()


def seed_all(crisis_mode: bool = False) -> None:
    print(f"\n=== Loading Test Data (crisis_mode={crisis_mode}) ===")
    seed_products()
    seed_sales(healthy=not crisis_mode)
    seed_competitors()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Heweso DynamoDB setup script")
    parser.add_argument(
        "--crisis",
        action="store_true",
        help="Load crisis scenario sales data (no sales in last 60 min)",
    )
    parser.add_argument(
        "--tables-only",
        action="store_true",
        help="Create tables only, skip test data",
    )
    args = parser.parse_args()

    setup_all_tables()

    if not args.tables_only:
        seed_all(crisis_mode=args.crisis)

    print("\n[DONE] Setup complete.")
