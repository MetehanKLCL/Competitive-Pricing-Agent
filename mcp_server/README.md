# mcp_server — What, Why, How

This document explains why the MCP integration exists, what we added, and how to test it.

---

## Why it exists

The project already has 14 tools (`tools/*.py`), but they were only defined in Bedrock's
own tool-calling format (`TOOL_DEFINITIONS` in `agent/bedrock_agent.py`). That format
works **only with Bedrock's `converse()` API** — no other AI client (Claude Desktop,
Claude Code) could use these tools at all.

**MCP (Model Context Protocol):** a protocol that lets AI clients connect to tools in a
standard way. A USB analogy: before USB, every device had its own cable; USB made it
"one standard, everything plugs in." MCP does the same for AI + tools.

`mcp_server/server.py` exposes those same 14 functions over the MCP standard **without
copying any of them**. Now any MCP-capable client (Claude Desktop, Claude Code, other
tools in the future) can connect to them.

**The main pricing agent (`agent/bedrock_agent.py`) did not change at all.** It still
uses its own Bedrock-native tool calling and keeps running autonomously 24/7 in the
Lambda. MCP is a separate access layer **added to** the existing system, not one that
**changes** it.

---

## File map

```
Competitive-Pricing-Agent/
├── requirements.txt        ← mcp[cli] added
├── mcp_server/
│   ├── README.md            ← this file
│   ├── __init__.py          ← empty; marks this as a Python package
│   └── server.py            ← the code that announces the 14 tools over MCP
```

---

## `requirements.txt` — what we installed

```
mcp[cli]>=1.2.0
```

Anthropic's official Python MCP library. The `[cli]` extra brings command-line
tools for testing/debugging (such as the MCP Inspector). Installed with `pip install` —
a local package install only, touching no AWS resources.

---

## `mcp_server/server.py` — line by line

```python
from tools import (
    query_sales as _query_sales,
    check_competitors as _check_competitors,
    ...
)

mcp = FastMCP("heweso-pricing-tools")

@mcp.tool()
def query_sales(product_id: str, minutes: int = 60) -> dict:
    """Fetches sales for a product in the last N minutes, plus current/min/base price."""
    return _query_sales(product_id, minutes)
```

**The import block:** we import the existing 14 functions and give each an
underscore-prefixed alias like `as _query_sales`. Why? Because below we define a **new
function with the same name** — the alias keeps the original from colliding with it.

**`mcp = FastMCP("heweso-pricing-tools")`** — creates the MCP server itself. The string
is just a label; a connecting client sees the server by this name.

**The `@mcp.tool()` decorator — the most important part.** This line means "announce
this function as an MCP tool." FastMCP auto-generates a JSON schema by inspecting:
- **type hints** (`product_id: str, minutes: int = 60`) → "takes two parameters, one
  string, one integer, the second optional"
- **the docstring** (`"""Fetches sales..."""`) → the client reads this to understand
  "when should I call this tool"

This is analogous to writing Bedrock's `TOOL_DEFINITIONS` JSON by hand — except here
it's **automatic**, generated from Python type hints.

**`return _query_sales(...)`** — delegates the real work to the original function. These
wrapper functions contain **no new computation**; all of it still lives in `tools/*.py`.
This same pattern repeats for all 14 tools.

**The startup code at the bottom:**
```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```
`transport="stdio"` = "talk over terminal stdin/stdout." Claude Desktop or Claude Code
runs this script in the background and exchanges messages with it over stdin/stdout — no
network port needed, the simplest possible connection.

Because it's inside the `if __name__ == "__main__":` block, simply **importing** the
file (for a sanity check) does not run this line — the server only truly starts when you
run `python3 -m mcp_server.server`.

---

## What we verified

Without actually starting the server (so the terminal wouldn't block), we only checked
"did the 14 tools register correctly":

```python
tools = await mcp.list_tools()
```

The output listed 14 tool names, all correct — proof that the `@mcp.tool()` decorators
ran without error. No AWS resource was contacted in this step; it only confirmed the
Python objects were set up correctly.

---

## How to connect / test

### Connecting to Claude Code (the easiest path) — VERIFIED

In a plain terminal (outside this chat), in the project folder:
```bash
claude mcp add heweso-pricing -e PYTHONPATH="<project-root>" -- /opt/anaconda3/bin/python3 -m mcp_server.server
```
(Replace `<project-root>` with the absolute path to this repo, and the Python path with
your own interpreter from `which python3`.)

**Why the full path + PYTHONPATH instead of bare `python3`:** on the first attempt we
registered it with `claude mcp add heweso-pricing -- python3 -m mcp_server.server`, and
the connection failed (`✘ Failed to connect`). The reason: Claude Code starts this
server outside the project folder, from a different Python environment — bare `python3`
can't see the packages in the conda `base` env (`mcp`, `boto3`, `dotenv`) and can't find
the `mcp_server` module either.

The fix: find the full path with `which python3` (e.g. `/opt/anaconda3/bin/python3`), and
pin "where to look for modules" to the project root with `-e PYTHONPATH=<project-root>`.
Run `claude mcp list` and you should see `✔ Connected` next to `heweso-pricing` — if you
see `✘ Failed to connect`, repeat this step.

This command **calls no AI model** — it just writes a config entry that says "know about
this MCP server" (think `git remote add`). Zero cost.

Then, in any Claude Code chat:
> "Call the check_sales_trend tool from the heweso-pricing MCP server for PROD-001"

Claude actually calls it, pulls data from DynamoDB, and shows the result — without
touching Bedrock at all. **Tested and working** — `check_sales_trend` was called and
returned `NO_DATA` (the correct result while the simulation was off).

**Cost note:** the tool call itself (a DynamoDB read) is essentially free. The chat
itself is part of your existing Claude Code plan. The `run_analytics` tool sends a query
to Athena — billed by data scanned (the same order of magnitude as running a query by
hand in the Athena console: cents).

### Connecting to Claude Desktop

In `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "heweso-pricing": {
      "command": "/opt/anaconda3/bin/python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "<project-root>",
      "env": { "PYTHONPATH": "<project-root>" }
    }
  }
}
```
(The same absolute-Python + PYTHONPATH gotcha applies as for Claude Code.)

### MCP Inspector (a visual debug UI)

```bash
npx @modelcontextprotocol/inspector python3 -m mcp_server.server
```
A UI opens in the browser where you can try each tool one at a time, entering its
parameters by hand — think of it as Postman for MCP.

---

## Is it automated yet?

No — like dbt, this is a **local, on-demand capability**. It isn't deployed to AWS and
has no EventBridge rule. It has no effect on the main pricing agent's 24/7 autonomous
operation; it's a completely separate, optional access path.
