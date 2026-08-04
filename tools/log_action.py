"""
log_action — Writes every agent action to the AuditLog table.
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AUDIT_TABLE = os.getenv("DYNAMODB_AUDIT_TABLE", "heweso-audit-log")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(AUDIT_TABLE)


def log_action(
    product_id: str = "UNKNOWN",
    action: str = "NO_ACTION",
    reason: str = "",
    old_value: str = "N/A",
    new_value: str = "N/A",
    agent_decision: str = "",
    bundle_discount_pct: float = None,
) -> dict:
    """
    Writes a record to the AuditLog table.

    action examples: "PRICE_UPDATE", "EMAIL_SENT", "NO_ACTION", "SALES_CHECK"

    bundle_discount_pct: STRUCTURED field for the bundle discount rate. Written
      ONLY when this log records a bundle discount. Downstream (Silver, the
      epsilon-greedy learner in check_bundle_trigger) reads this typed number
      directly instead of REGEXP-parsing it back out of the `reason` text.
      The value is injected from code by the bundle guard (bedrock_agent.py),
      not trusted to the model.

    Returns:
        {
            "log_id": str,
            "timestamp": str,
        }
    """
    log_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    item = {
        "log_id": log_id,
        "timestamp": timestamp,
        "product_id": product_id,
        "action": action,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "agent_decision": agent_decision,
    }

    # Structured field only added on bundle logs. If None it is never written,
    # so other audit records don't bloat. DynamoDB needs Decimal, not float.
    if bundle_discount_pct is not None:
        item["bundle_discount_pct"] = Decimal(str(bundle_discount_pct))

    _table.put_item(Item=item)

    return {
        "log_id": log_id,
        "timestamp": timestamp,
    }


if __name__ == "__main__":
    result = log_action(
        product_id="PROD-001",
        action="PRICE_UPDATE",
        old_value="24999",
        new_value="23499",
        reason="Matching Trendyol price",
        agent_decision="Competitor undercut us, above min_price, update applied.",
    )
    print(result)
