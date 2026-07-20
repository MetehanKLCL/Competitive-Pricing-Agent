# Heweso — Autonomous Competitive Pricing Agent

An always-on AI agent that prices e-commerce products autonomously: it **observes** sales
and competitor data, **reasons** about what to do, **acts** (changes prices, emails, escalates),
then **evaluates the outcome and learns** from it. Built for a fictional Turkish e-commerce
platform ("Heweso") as a portfolio piece in agentic data engineering.

> **One sentence:** When a phone starts selling fast, the agent automatically discounts its
> accessories; when sales stall, it checks competitors, learns from history, and either drops
> the price or escalates to a human.

This is **not** a traditional ETL pipeline. A traditional pipeline moves data. This one closes
the loop: *sense → reason → act → evaluate → learn.* That loop is what makes it "agentic."

---

## Architecture

```
EventBridge (schedule, cost-guarded)
        │
        ▼
AWS Lambda (Python 3.12)  ──►  Amazon Bedrock (Nova Lite)
        │                       ReAct loop · 14 tools
        │
        ▼
┌───────────────────────────────────────────────┐
│ 14 TOOLS                                       │
│  SENSE   check_sales_trend · query_sales ·     │
│          check_competitors · get_time_context ·│
│          check_competitor_pattern             │
│  DECIDE  decide_price · analyze_price_elasticity│
│          check_outcome · check_bundle_trigger  │
│  ACT     update_price · log_action ·           │
│          send_email · escalate                 │
│  ANALYZE run_analytics                          │
└───────────────────────────────────────────────┘
        │                         │
        ▼                         ▼
   DynamoDB (4 tables)        Amazon SES
        │
        ▼
   S3 data lake  ──►  Athena / Glue  (Medallion: Bronze → Silver → Gold)
```

### The five subsystems

| # | Subsystem | What it does | Status |
|---|-----------|--------------|--------|
| 1 | **Live pricing agent** | Bedrock Nova Lite, ReAct loop, 14 tools | Deployed on Lambda |
| 2 | **Medallion pipeline** | DynamoDB → S3 Bronze/Silver/Gold, hourly, inside the Lambda | Automated |
| 3 | **dbt project** | SQL rebuild of Silver/Gold in an isolated schema, with data-quality tests | Manual (`dbt run && dbt test`) |
| 4 | **Weekly analytics report** | Reads Gold, builds an HTML report, AI writes the narrative, SES emails it | Ready |
| 5 | **MCP server** | Exposes all 14 tools over Model Context Protocol for any MCP client | Local dev tool |

The agent's decision-making brain (subsystem 1) was built first; 2–5 are the data-engineering
and tooling layer built *around* it.

---

## Tech stack

| Layer | Tools |
|-------|-------|
| Compute | AWS Lambda (Python 3.12) |
| AI / Agent | Amazon Bedrock (Nova Lite), ReAct pattern, Model Context Protocol (MCP) |
| Orchestration | Amazon EventBridge |
| Transactional store | Amazon DynamoDB (4 tables) |
| Analytics | Amazon S3 (data lake) · Athena · AWS Glue Data Catalog |
| Transformation | Python (Medallion) + dbt (SQL, parallel implementation, tested) |
| Notifications | Amazon SES |
| Frontend | FastAPI · Server-Sent Events · vanilla-JS dashboard |
| Methods | Epsilon-greedy (multi-armed bandit), Hive partitioning, data-quality gates |

---

## Key engineering decisions

**Math lives in code, not in the model.** Nova Lite makes arithmetic mistakes on simple
comparisons. Every price calculation is done in Python (`decide_price`); the model only calls
the tool and follows the result.

**Guardrails, not just prompts.** With an unreliable model, "the prompt says so" is never enough
for anything touching money, data, or outbound communication. Critical rules are enforced in code:
a price guard forces `update_price` to use the value `decide_price` returned; a bundle guard
injects the chosen discount even if the model forgets it; `send_email` always sends to the
verified address (the recipient can't be chosen by any caller); `run_analytics` accepts read-only
`SELECT`/`WITH` only; `update_price` clamps to the `[min_price, base_price]` band.

**Event-date vs snapshot-date partitioning.** Bronze is a full DynamoDB scan, so each day's
partition contains *all history up to that day*. Aggregating Gold by the partition date was
cumulative and double-counted across days. Gold now groups by each row's **real event date**
(`sale_date` / `action_date`, already derived in Silver) and partitions by it — so each day's
Gold row is genuinely that day's activity, and the weekly report can read Gold directly.

**Structured fields over text parsing.** The bundle discount rate used to be recovered from a
free-text `reason` string with a regex. It's now written at the source as a typed
`bundle_discount_pct` audit field (injected by the bundle guard, not trusted to the model) and
flows Bronze → Silver → Glue, so the learner reads a real column instead of parsing prose.

**dbt tests: singular over `dbt_utils`, deliberately.** Composite `(date, product_id)` uniqueness
needs a multi-column test. Rather than add the `dbt_utils` dependency, this project uses
hand-written **singular tests** — zero dependency, works on any dbt version. That's a scale
judgment (YAGNI at 3 Gold tables); at ~15–20+ tables I'd switch to
`dbt_utils.unique_combination_of_columns` for the DRY win. Knowing *when* to use each is the point.

**Data-driven, not rule-based.** `get_time_context` used to return labels like `PEAK`/`HOLD`
(hard rules). It now returns a raw `traffic_ratio` number and lets the model reason. That shift —
from fixed rules to signals the model weighs — is the essence of an agentic system.

---

## The learning layer

- **Price elasticity** (`analyze_price_elasticity`): for each past discount, sums the **revenue**
  (not unit count) in the following 60 minutes, grouped by discount %, with confidence scoring
  based on sample size. Low confidence → ignore and just match the competitor.
- **Bundle pricing via epsilon-greedy** (`check_bundle_trigger`): a multi-armed bandit over
  discount rates `[5, 7, 9, 11]%`. 70% exploit the best-known rate, 30% explore — with a
  **confidence gate** so a lucky single sample can't be crowned "best."
- **Flash-sale vs structural** (`check_competitor_pattern`): a competitor cheaper for <60 min is a
  flash sale (wait); >180 min is structural (match). Detected via an `undercut_since` timestamp.

---

## Data layer (Medallion + dbt)

```
Bronze  raw DynamoDB export, never mutated
Silver  cleaned, joined, derived fields, data-quality gate (drops invalid product_ids)
Gold    pre-aggregated business metrics, partitioned by event date
```

Two parallel implementations of Silver/Gold exist on purpose: a **Python** pipeline (the live one,
runs hourly inside the Lambda) and a **dbt** project (SQL, in an isolated Glue schema, with 18
automated data-quality tests: `unique`, `not_null`, `relationships`, `accepted_values`, plus
custom singular composite-key tests). The dbt version demonstrates the same transformations with
an industry-standard tool and never collides with the live tables.

---

## Known limitations & tradeoffs

Honesty about a system's weak points is part of understanding it.

- **Full-scan Bronze, not incremental/CDC.** A deliberate simplicity tradeoff for this data volume.
  The production-correct version (DynamoDB Streams / watermarked incremental ingestion) is the
  planned pre-open-source upgrade.
- **Elasticity is observational, not a true A/B test.** No control group, so correlation isn't
  cleanly causation. A real experiment (or the bandit approach used for bundles) would be stronger.
- **Confidence scoring uses fixed sample-count thresholds**, not a full statistical test. A pragmatic
  shortcut; the rigorous version computes a standard error / confidence interval per discount rate.
- **Nova Lite** intermittently throws `ModelErrorException` (~20% of runs) and occasionally forgets
  tool parameters — the guardrails absorb this, and the agent retries on the next trigger.
- **Market simulation uses random competitor prices**, not real scraping (the biggest gap between
  demo and product).

---

## Repository structure

```
├── agent/            system_prompt.py · bedrock_agent.py (ReAct loop + guards) · report_agent.py
├── tools/            the 14 tools, each independently testable
├── infrastructure/   dynamodb_setup.py · export_to_s3.py · medallion/{silver,gold,setup_glue_tables}.py
├── dbt_heweso/       dbt project (models/silver, models/gold, tests/) — SQL Medallion + tests
├── lambda/           handler.py (agent + hourly pipeline) · analytics_handler.py (weekly report)
├── mcp_server/       server.py — 14 tools exposed over MCP
├── frontend/         FastAPI dashboard (SSE, live sales, agent terminal)
├── CONCEPTS.md       plain-language explanations of every technical concept used
└── INTERVIEW_PREP.md project story + design tradeoffs in STAR form
```

---

## Running locally

```bash
# 1. Configure credentials (never committed)
cp .env.example .env    # fill in AWS + SES values

# 2. Seed a clean dataset
python3 -c "from infrastructure.dynamodb_setup import seed_all; seed_all(crisis_mode=False)"

# 3. Refresh the data lake (Bronze → Silver → Gold)
python3 infrastructure/export_to_s3.py
python3 infrastructure/medallion/silver.py
python3 infrastructure/medallion/gold.py

# 4. (optional) Run the dbt layer
cd dbt_heweso && dbt run && dbt test

# 5. Start the dashboard
uvicorn frontend.api:app --port 8000 --reload   # → http://localhost:8000
```

---

*Built as an internship / portfolio project to demonstrate agentic data engineering on AWS.*
