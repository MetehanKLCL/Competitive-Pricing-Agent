"""
analytics_handler.py — Lambda entry point for the weekly analytics reporter.

INDEPENDENT of the main pricing agent (handler.py), triggered by its own separate
Lambda + EventBridge rule (e.g. once a week). Its purpose is not to make pricing
decisions, but to summarize the last N days of data and email it to the manager.

Flow:
  1. generate_weekly_report() → pulls numbers from Gold, builds HTML (Python/SQL, no math-error risk)
  2. generate_report_insight() → asks Bedrock for a 2-4 sentence commentary (produces no numbers, only narrates)
  3. send_email() → sends the HTML report to the manager
"""

import json
import os
import sys

# Lambda runtime: code runs under /var/task.
# Local test: the script's parent folder (the project root) is added to the path.
sys.path.insert(0, "/var/task")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.generate_weekly_report import generate_weekly_report
from tools.send_email import send_email
from agent.report_agent import generate_report_insight

REPORT_DAYS = int(os.getenv("REPORT_PERIOD_DAYS", "7"))


def lambda_handler(event, context):
    print(f"[ANALYTICS] Generating {REPORT_DAYS}-day report...")

    report = generate_weekly_report(days=REPORT_DAYS)
    if not report["success"]:
        print("[ANALYTICS] Report generation failed.")
        return {"statusCode": 500, "body": json.dumps({"error": "report generation failed"})}

    insight = generate_report_insight(report["stats_summary"])
    insight_html = (
        f'<div style="background:#fff8e1;border-left:4px solid #f39c12;padding:12px 16px;margin:16px 0">'
        f'<strong>Insight:</strong> {insight}</div>'
    ) if insight else ""

    final_html = report["html"].replace("<!-- AI_INSIGHT -->", insight_html)

    subject = f"Heweso Weekly Report — {report['total_sales']} sales, ${report['total_revenue']} revenue"
    result = send_email(
        subject=subject,
        body=report["stats_summary"],
        html_override=final_html,
    )

    print(f"[ANALYTICS] Email result: {result}")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "report_stats": report["stats_summary"],
            "insight": insight,
            "email_sent": result.get("success", False),
        }, ensure_ascii=False),
    }


if __name__ == "__main__":
    print(lambda_handler({}, None))
