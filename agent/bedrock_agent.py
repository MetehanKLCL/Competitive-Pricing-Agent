"""
bedrock_agent.py — The ReAct loop that drives Amazon Bedrock (Nova Lite).

What it does:
  - Declares the 14 tool specs (toolConfig) and the converse() loop that lets the
    model reason → call a tool → observe → repeat (max 10 iterations).
  - Enforces the code-side guards: the price guard (update_price must use
    decide_price's exact new_price) and the bundle guard (inject the epsilon-greedy
    discount into decide_price/log_action even if the model forgot it).
  - Streams thinking/tool/result events to an optional log callback for the UI.

Why it exists / how it fits:
  This is subsystem (1), the live pricing brain. system_prompt.py is the playbook;
  this file is the engine that runs it and calls the tools/*.py functions for real.
"""

import json
import os

import boto3
from dotenv import load_dotenv

from agent.system_prompt import SYSTEM_PROMPT
from tools import (
    check_competitors,
    check_outcome,
    check_sales_trend,
    log_action,
    query_sales,
    run_analytics,
    send_email,
    update_price,
    escalate,
    decide_price,
    check_competitor_pattern,
    analyze_price_elasticity,
    get_time_context,
    check_bundle_trigger,
)

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")

_bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

TOOL_DEFINITIONS = [
    {
        "toolSpec": {
            "name": "query_sales",
            "description": "Queries DynamoDB for sales in the last X minutes. Returns status='critical' if no sales.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "minutes": {"type": "integer"},
                    },
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "check_competitors",
            "description": "Fetches competitor prices from DynamoDB, sorted cheapest first.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "update_price",
            "description": "Updates product price in DynamoDB. Never goes below min_price.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "new_price": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["product_id", "new_price", "reason"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "log_action",
            "description": "Records every action taken into the AuditLog table.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "action": {"type": "string"},
                        "old_value": {"type": "string"},
                        "new_value": {"type": "string"},
                        "reason": {"type": "string"},
                        "agent_decision": {"type": "string"},
                    },
                    "required": ["product_id", "action", "reason"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "check_outcome",
            "description": (
                "Checks whether the last price change for a product actually brought sales back. "
                "Returns outcome: SUCCESS (sales recovered), FAILED (no sales after change), "
                "PENDING (too early), or NO_RECENT_CHANGE. "
                "Use this in RECOVERY mode (healthy sales) to evaluate past decisions."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "check_sales_trend",
            "description": (
                "Compares sales velocity: last 30 min vs previous 30 min. "
                "Returns trend: OK (stable), WARNING (>50% drop), CRITICAL (>80% drop), SURGE (>100% increase). "
                "Use this FIRST in every run to detect problems before they become full crises."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id":      {"type": "string"},
                        "window_minutes":  {"type": "integer", "description": "Comparison window in minutes (default 30)"},
                    },
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "run_analytics",
            "description": (
                "Runs a SQL query on Athena against the heweso_analytics database. "
                "Use this to analyze agent performance, crisis history, revenue impact, etc. "
                "Tables: heweso_analytics.audit_log, heweso_analytics.sales, "
                "heweso_analytics.competitors, heweso_analytics.products"
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL query to run on Athena"},
                        "max_rows": {"type": "integer", "description": "Max rows to return (default 20)"},
                    },
                    "required": ["sql"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "send_email",
            "description": "Sends a summary report email to the admin via Amazon SES.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["subject", "body"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "escalate",
            "description": (
                "Sends a priority escalation email and logs ESCALATION when automated "
                "pricing strategy has failed and human intervention is needed. "
                "Use when: check_outcome returns FAILED, or when the same product "
                "has failed multiple consecutive times."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "reason":     {"type": "string", "description": "Why escalation is triggered"},
                        "context":    {"type": "string", "description": "Analytics context, failure history"},
                    },
                    "required": ["product_id", "reason"],
                }
            },
        }
    },

    {
        "toolSpec": {
            "name": "decide_price",
            "description": (
                "Calculates price decision math. Returns competitor_gap_pct (how much cheaper/expensive "
                "competitor is), traffic_ratio context, and action recommendation. "
                "Pass traffic_ratio from get_time_context so you can weigh demand vs competitor gap. "
                "mode='crisis' = should we lower price? mode='recovery' = should we raise price? "
                "mode='bundle' = proactively discount an accessory because its parent phone is surging "
                "(use bundle_discount_pct from check_bundle_trigger). "
                "You make the final judgment — this tool gives you the numbers."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id":          {"type": "string"},
                        "mode":                {"type": "string", "description": "'crisis', 'recovery', or 'bundle'"},
                        "traffic_ratio":       {"type": "number", "description": "traffic_ratio from get_time_context (optional but recommended)"},
                        "preferred_drop_pct":  {"type": "number", "description": "optimal_drop_pct from analyze_price_elasticity (negative float, e.g. -5.0). Omit if elasticity returned no data."},
                        "bundle_discount_pct": {"type": "number", "description": "For mode='bundle' only: selected_discount_pct from check_bundle_trigger (e.g. 9). Auto-injected by the bundle guard if omitted."},
                    },
                    "required": ["product_id", "mode"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "check_competitor_pattern",
            "description": (
                "Analyzes how long a competitor has been undercutting our price. "
                "Returns: FLASH_SALE (<60min, wait), MONITOR (60-180min), "
                "STRUCTURAL (>180min, act), or NOT_UNDERCUT. "
                "Use this BEFORE decide_price in crisis mode to avoid reacting to flash sales."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "analyze_price_elasticity",
            "description": (
                "Analyzes historical price changes to learn how much discount actually drives sales. "
                "Returns optimal_drop_pct: the discount percentage that historically worked best. "
                "Use this in crisis mode to decide HOW MUCH to discount, not just whether to discount."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                }
            },
        }
    },

    {
        "toolSpec": {
            "name": "get_time_context",
            "description": (
                "Returns traffic context for this hour: traffic_ratio (current hour sales / hourly average), "
                "traffic_level ('high'/'medium'/'low'), and a context note. "
                "Pass traffic_ratio to decide_price so math and judgment can be combined. "
                "Call this BEFORE any price decision in crisis mode."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "Product to analyze historical sales pattern for"
                        }
                    },
                    "required": ["product_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "check_bundle_trigger",
            "description": (
                "Checks if this product is an accessory with a bundle parent phone. "
                "If the parent phone is surging, returns bundle_opportunity=True and selected_discount_pct "
                "(chosen via epsilon-greedy learning from historical data). "
                "Pass selected_discount_pct to decide_price as bundle_discount_pct. "
                "Only call for PROD-002 (AirPods Pro 3) and PROD-004 (Samsung Galaxy Buds3 Pro)."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                }
            },
        }
    },
]


def _execute_tool(tool_name: str, tool_input: dict, price_update_log: list, log_fn=None, test_hour: int = None,
                  _decide_price_result: dict = None, _bundle_discount_pct: float = None) -> str:
    print(f"  [TOOL] {tool_name}({tool_input})")
    if log_fn:
        log_fn({"type": "tool_call", "name": tool_name, "input": tool_input})

    if tool_name == "query_sales":
        result = query_sales(**tool_input)
    elif tool_name == "check_outcome":
        result = check_outcome(**tool_input)
    elif tool_name == "check_sales_trend":
        result = check_sales_trend(**tool_input)
    elif tool_name == "run_analytics":
        result = run_analytics(**tool_input)
    elif tool_name == "check_competitors":
        result = check_competitors(**tool_input)
    elif tool_name == "decide_price":
        # Bundle mode: inject selected_discount_pct even if the model forgot it
        if tool_input.get("mode") == "bundle" and _bundle_discount_pct is not None:
            if "bundle_discount_pct" not in tool_input:
                print(f"  [BUNDLE GUARD] Injecting bundle_discount_pct={_bundle_discount_pct}")
                tool_input = {**tool_input, "bundle_discount_pct": _bundle_discount_pct}
        result = decide_price(**tool_input)
    elif tool_name == "check_competitor_pattern":
        result = check_competitor_pattern(**tool_input)
    elif tool_name == "analyze_price_elasticity":
        result = analyze_price_elasticity(**tool_input)
    elif tool_name == "update_price":
        # The model sometimes passes its own price instead of decide_price.new_price.
        # If decide_price ran in this session, force its new_price.
        if _decide_price_result and _decide_price_result.get("new_price") is not None:
            correct_price = _decide_price_result["new_price"]
            if tool_input.get("new_price") != correct_price:
                print(f"  [GUARD] Price corrected: {tool_input.get('new_price')} → {correct_price}")
                tool_input = {**tool_input, "new_price": correct_price}
        result = update_price(**tool_input)
        if result.get("success"):
            price_update_log.append(result)
    elif tool_name == "log_action":
        # Bundle guard (log side): inject the discount rate FROM CODE as a
        # structured field. We don't rely on the model to pass it. We only add it
        # if the log is genuinely a bundle action ("bundle" appears in
        # action/reason) — so the field doesn't leak into non-bundle records.
        # Downstream can now read this number directly instead of scraping it out
        # of the reason text with REGEXP.
        if _bundle_discount_pct is not None and "bundle_discount_pct" not in tool_input:
            blob = f"{tool_input.get('action', '')} {tool_input.get('reason', '')}".lower()
            if "bundle" in blob:
                print(f"  [BUNDLE GUARD] Injecting bundle_discount_pct={_bundle_discount_pct} into log_action")
                tool_input = {**tool_input, "bundle_discount_pct": _bundle_discount_pct}
        result = log_action(**tool_input)
    elif tool_name == "send_email":
        # The recipient guard now lives in a single source: tools/send_email.py
        # always forces the recipient to the verified address in .env. No stripping
        # needed here — even if the model invents a recipient, the tool ignores it.
        if price_update_log:
            result = send_email(**tool_input)
        else:
            result = {"blocked": "No price update made — email skipped."}
    elif tool_name == "escalate":
        result = escalate(**tool_input)
    elif tool_name == "check_bundle_trigger":
        result = check_bundle_trigger(**tool_input)
    elif tool_name == "get_time_context":
        if test_hour is not None and "test_hour" not in tool_input:
            tool_input = {**tool_input, "test_hour": test_hour}
        result = get_time_context(**tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}

    print(f"  [RESULT] {result}")
    if log_fn:
        log_fn({"type": "tool_result", "name": tool_name, "result": result})
    return json.dumps(result, ensure_ascii=False)


def run_agent(product_id: str, trigger_reason: str = "No sales detected", log_fn=None, test_hour: int = None) -> str:
    def _emit(event):
        if log_fn:
            log_fn(event)

    print(f"\n{'='*50}")
    print(f"AGENT STARTED — Product: {product_id} | Reason: {trigger_reason}")
    print(f"{'='*50}\n")
    _emit({"type": "start", "product_id": product_id, "reason": trigger_reason})

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        f"Product ID: {product_id}\n"
                        f"Trigger reason: {trigger_reason}\n"
                        f"Please analyze the situation and take the appropriate action."
                    )
                }
            ],
        }
    ]

    max_iterations = 10
    final_response = ""
    price_update_log = []
    decide_price_result = None   # keep decide_price output to guard update_price
    bundle_discount_pct = None   # selected rate from check_bundle_trigger

    for i in range(max_iterations):
        print(f"--- Turn {i + 1} ---")
        _emit({"type": "turn", "turn": i + 1})

        response = _bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": TOOL_DEFINITIONS},
        )

        stop_reason = response["stopReason"]
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        if stop_reason == "end_turn":
            for block in assistant_message["content"]:
                if "text" in block:
                    final_response = block["text"]
                    print(f"\nAGENT RESULT:\n{final_response}")
                    _emit({"type": "final", "text": final_response})
            break

        if stop_reason == "tool_use":
            tool_results = []
            for block in assistant_message["content"]:
                if "text" in block and block["text"].strip():
                    _emit({"type": "thinking", "text": block["text"].strip()})
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    output = _execute_tool(
                        tool_use["name"], tool_use["input"], price_update_log, log_fn=log_fn, test_hour=test_hour,
                        _decide_price_result=decide_price_result,
                        _bundle_discount_pct=bundle_discount_pct,
                    )
                    import json as _json
                    if tool_use["name"] == "decide_price":
                        try:
                            decide_price_result = _json.loads(output)
                        except Exception:
                            pass
                    if tool_use["name"] == "check_bundle_trigger":
                        try:
                            bt = _json.loads(output)
                            if bt.get("bundle_opportunity") and bt.get("selected_discount_pct"):
                                bundle_discount_pct = float(bt["selected_discount_pct"])
                        except Exception:
                            pass
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"text": output}],
                            }
                        }
                    )
            messages.append({"role": "user", "content": tool_results})

    _emit({"type": "done"})
    return final_response


if __name__ == "__main__":
    run_agent("PROD-001", trigger_reason="No sales for 60 minutes")
