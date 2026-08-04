"""
mcp_server/server.py — Exposes all 14 Heweso pricing tools via MCP.

MCP (Model Context Protocol): a standard protocol that lets AI clients
(Claude Desktop, Claude Code, etc.) discover and call tools — much like USB
standardizes devices.

This file does NOT rewrite the existing tools/*.py functions — it "exposes"
them via a thin MCP wrapper. The logic always lives in tools/; here we only have
the name + type info + docstring (FastMCP auto-generates the JSON schema from them).

The main pricing agent (agent/bedrock_agent.py) never uses this file — it keeps
using its own Bedrock native tool-calling format. MCP is a separate access layer
ADDED to the existing system, not one that CHANGES it.

Run locally (stdio transport):
    python3 -m mcp_server.server

To connect to Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "heweso-pricing": {
          "command": "python3",
          "args": ["-m", "mcp_server.server"],
          "cwd": "/Users/metehankilicli/Desktop/DE-Projects/Competitive-Pricing-Agent"
        }
      }
    }

To connect to Claude Code (from the terminal):
    claude mcp add heweso-pricing -- python3 -m mcp_server.server

For debug/test (MCP Inspector, opens a visual UI in the browser):
    npx @modelcontextprotocol/inspector python3 -m mcp_server.server
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from tools import (
    query_sales as _query_sales,
    check_competitors as _check_competitors,
    update_price as _update_price,
    log_action as _log_action,
    check_outcome as _check_outcome,
    check_sales_trend as _check_sales_trend,
    run_analytics as _run_analytics,
    send_email as _send_email,
    escalate as _escalate,
    decide_price as _decide_price,
    check_competitor_pattern as _check_competitor_pattern,
    analyze_price_elasticity as _analyze_price_elasticity,
    get_time_context as _get_time_context,
    check_bundle_trigger as _check_bundle_trigger,
)

mcp = FastMCP("heweso-pricing-tools")


# ── SENSING ──────────────────────────────────────────────────────────────────

@mcp.tool()
def query_sales(product_id: str, minutes: int = 60) -> dict:
    """Fetches sales for a product in the last N minutes, plus current/min/base price."""
    return _query_sales(product_id, minutes)


@mcp.tool()
def check_sales_trend(product_id: str, window_minutes: int = 30) -> dict:
    """Compares last window vs previous window sales velocity. Returns OK/WARNING/CRITICAL/SURGE/NO_DATA."""
    return _check_sales_trend(product_id, window_minutes)


@mcp.tool()
def check_competitors(product_id: str) -> list:
    """Returns all competitor prices for a product from DynamoDB, sorted cheapest first."""
    return _check_competitors(product_id)


@mcp.tool()
def check_competitor_pattern(product_id: str) -> dict:
    """Determines if a competitor's lower price is a flash sale (<60min) or a structural change (>180min)."""
    return _check_competitor_pattern(product_id)


@mcp.tool()
def get_time_context(product_id: str, test_hour: Optional[int] = None) -> dict:
    """Returns traffic_ratio for the current hour based on historical Athena sales data (Silver layer)."""
    return _get_time_context(product_id, test_hour)


# ── DECISION ─────────────────────────────────────────────────────────────────

@mcp.tool()
def decide_price(
    product_id: str,
    mode: str,
    traffic_ratio: Optional[float] = None,
    preferred_drop_pct: Optional[float] = None,
    bundle_discount_pct: Optional[float] = None,
) -> dict:
    """Calculates the price decision — all math done here, not by the calling model. mode: 'crisis' | 'recovery' | 'bundle'."""
    return _decide_price(product_id, mode, traffic_ratio, preferred_drop_pct, bundle_discount_pct)


@mcp.tool()
def analyze_price_elasticity(product_id: str) -> dict:
    """Analyzes historical price drops vs sales (Silver layer) to find which discount % worked best, with confidence scoring."""
    return _analyze_price_elasticity(product_id)


@mcp.tool()
def check_outcome(product_id: str) -> dict:
    """Checks whether the last price change actually brought sales back. Returns SUCCESS/FAILED/PENDING/NO_RECENT_CHANGE."""
    return _check_outcome(product_id)


@mcp.tool()
def check_bundle_trigger(product_id: str) -> dict:
    """For accessory products (PROD-002, PROD-004), checks if the bundle-parent phone is surging and picks a discount % via epsilon-greedy."""
    return _check_bundle_trigger(product_id)


# ── ACTION ───────────────────────────────────────────────────────────────────

@mcp.tool()
def update_price(product_id: str, new_price: float, reason: str) -> dict:
    """Updates the product's current_price in DynamoDB. Never allows going below min_price."""
    return _update_price(product_id, new_price, reason)


@mcp.tool()
def log_action(
    product_id: str = "UNKNOWN",
    action: str = "NO_ACTION",
    reason: str = "",
    old_value: str = "N/A",
    new_value: str = "N/A",
    agent_decision: str = "",
) -> dict:
    """Writes an action record to the AuditLog table (DynamoDB)."""
    return _log_action(product_id, action, reason, old_value, new_value, agent_decision)


@mcp.tool()
def send_email(subject: str, body: str) -> dict:
    """Sends a plain-text/HTML email via Amazon SES. Always goes to the verified
    admin address (SES_RECIPIENT_EMAIL) — recipient cannot be chosen by the caller."""
    return _send_email(subject, body)


@mcp.tool()
def escalate(product_id: str, reason: str, context: str = "") -> dict:
    """Sends a priority escalation email and logs it when the automated pricing strategy has failed."""
    return _escalate(product_id, reason, context)


# ── ANALYTICS ────────────────────────────────────────────────────────────────

@mcp.tool()
def run_analytics(sql: str, max_rows: int = 20) -> dict:
    """Runs a read-only SQL query against Athena (heweso_analytics database — Bronze/Silver/Gold tables)."""
    return _run_analytics(sql, max_rows)


if __name__ == "__main__":
    mcp.run(transport="stdio")
