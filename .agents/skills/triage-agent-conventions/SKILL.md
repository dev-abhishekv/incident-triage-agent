---
name: triage-agent-conventions
description: Project conventions for the pipeline-triage-agent repo — Pydantic contracts, the TriageStrategy interface, ops.* BigQuery table schemas, tool definition patterns, fault injector structure, and eval runner rules. Use whenever writing, editing, or reviewing any code in this repository, including substrate pipelines, agent tools, strategies, fault injectors, and the eval harness.
---

# Triage Agent — Project Conventions

Conventions for `pipeline-triage-agent`. An agentic data-pipeline incident triage system evaluated against a deterministic baseline.

**Read this before writing any code in this repo.** These contracts are agreed and stable. Do not redesign them mid-project. If something here genuinely doesn't work, say so and ask — do not silently substitute a different shape.

---

## Non-negotiables

1. **Pydantic everywhere at boundaries.** Tool inputs, tool outputs, `Incident`, `TriageResult`. Never `dict` or `Any` crossing a tool or strategy boundary.
2. **`model_config = {"extra": "forbid"}`** on every boundary model.
3. **One `TriageResult` definition** in `triage/contracts.py`, used by the baseline, every agent, and the BigQuery insert. Never redefine it locally.
4. **Every diagnosis method implements `TriageStrategy`.** The baseline is a strategy. LangGraph is a strategy. ADK is a strategy.
5. **Fault injectors are composable** — setup/teardown pairs that assume nothing about starting state.
6. **Never widen a table schema without saying so.** `ops.*` columns are fixed; adding one means re-running evals.

---

## Core contracts (`triage/contracts.py`)

```python
from datetime import date, datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class RootCauseId(StrEnum):
    SCHEMA_ADDITIVE = "schema_additive"
    SCHEMA_RENAME = "schema_rename"
    SCHEMA_TYPE_CHANGE = "schema_type_change"
    SCHEMA_COLUMN_DROPPED = "schema_column_dropped"
    NULL_EXPLOSION = "null_explosion"
    DUPLICATE_KEYS = "duplicate_keys"
    UNIT_CHANGE = "unit_change"
    TIMEZONE_SHIFT = "timezone_shift"
    SENTINEL_VALUES = "sentinel_values"
    MALFORMED_JSON = "malformed_json"
    UPSTREAM_EMPTY = "upstream_empty"
    STALE_PARTITION = "stale_partition"
    UPSTREAM_FAILED_DOWNSTREAM_RAN = "upstream_failed_downstream_ran"
    DOUBLE_LOAD = "double_load"
    CREDENTIAL_EXPIRED = "credential_expired"
    IAM_PERMISSION_DENIED = "iam_permission_denied"
    SOURCE_RATE_LIMITED = "source_rate_limited"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    NETWORK_TIMEOUT = "network_timeout"
    CONFIG_DRIFT = "config_drift"
    UNKNOWN = "unknown"


class Incident(BaseModel):
    model_config = {"extra": "forbid"}

    incident_id: str
    pipeline: str
    stage: str
    run_id: str
    occurred_at: datetime
    partition_date: date
    alert_text: str
    # Ground truth. NEVER pass this to a strategy.
    injected_root_cause: RootCauseId | None = None


class Evidence(BaseModel):
    model_config = {"extra": "forbid"}
    tool: str
    finding: str


class TriageResult(BaseModel):
    model_config = {"extra": "forbid"}

    root_cause_id: RootCauseId
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence]
    blast_radius: list[str] = []
    proposed_remediation: str
    requires_human_approval: bool = True
```

**Critical:** `Incident.injected_root_cause` is ground truth for scoring only. The eval runner strips it before handing the incident to any strategy. If you see it reaching a prompt or a tool, that is a leak and the eval is invalid.

---

## The strategy interface (`triage/strategy.py`)

```python
from typing import Protocol


class TriageStrategy(Protocol):
    name: str          # stable, goes in ops.triage_results.strategy
    routing_policy: str  # "n/a" for baseline; "all_cheap" | "all_premium" | "tiered"

    def diagnose(self, incident: Incident) -> TriageResult: ...
```

Every new diagnosis method is a new class implementing this. The eval runner loops over a list of strategies and knows nothing about LangGraph, ADK, or rules.

---

## Tool pattern (`triage/tools/`)

One module per tool. Pydantic in, Pydantic out. Constraints live in the model, not in defensive code inside the function.

```python
class GetDataProfileInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(description="Fully qualified table, e.g. core.site_daily_summary")
    partition_date: date = Field(description="Partition to profile, ISO format")


class DataProfile(BaseModel):
    model_config = {"extra": "forbid"}
    table: str
    partition_date: date
    row_count: int = Field(ge=0)
    null_rates: dict[str, float]
    distinct_counts: dict[str, int]
    duplicate_key_count: int = Field(ge=0)


def get_data_profile(args: GetDataProfileInput) -> DataProfile:
    """Return the profiled statistics for one partition of one table."""
```

`Field(description=...)` is what the model reads when choosing a tool. Write it for a stranger who has never seen this repo. Do not rely on docstrings alone — both LangGraph and ADK build their function-calling schemas from the Pydantic model.

**The nine tools, fixed:**

| Tool | Returns |
|---|---|
| `get_run_details` | `RunDetails` |
| `get_run_history` | `RunHistory` |
| `get_schema_changes` | `SchemaChanges` |
| `get_data_profile` | `DataProfile` |
| `compare_partitions` | `PartitionDiff` |
| `get_upstream_dependencies` | `UpstreamDeps` |
| `get_freshness` | `Freshness` |
| `search_logs` | `LogLines` |
| `get_recent_config_changes` | `ConfigChanges` |

Tools are read-only. A tool never writes, never mutates, never triggers a run.

---

## BigQuery `ops.*` schemas — fixed

Datasets: `raw`, `core`, `ops`, `triage_eval`.

```sql
ops.run_events(
  run_id STRING, pipeline STRING, stage STRING,
  started_at TIMESTAMP, ended_at TIMESTAMP, status STRING,
  rows_in INT64, rows_out INT64, bytes_processed INT64,
  exit_code INT64, error_type STRING, error_message STRING,
  log_uri STRING, git_sha STRING, config_json JSON
)

ops.schema_history(
  observed_at TIMESTAMP, table STRING, column_name STRING,
  data_type STRING, is_nullable BOOL, schema_version INT64
)

ops.data_profiles(
  run_id STRING, table STRING, partition_date DATE,
  row_count INT64, null_rate_json JSON, distinct_count_json JSON,
  min_max_json JSON, duplicate_key_count INT64, profiled_at TIMESTAMP
)

ops.lineage(
  downstream_table STRING, upstream_table STRING, dependency_type STRING
)

ops.triage_results(
  incident_id STRING, strategy STRING, routing_policy STRING,
  predicted_root_cause_id STRING, confidence FLOAT64,
  evidence_json JSON, proposed_remediation STRING,
  latency_ms INT64, input_tokens INT64, output_tokens INT64,
  cost_usd FLOAT64, run_seq INT64
)

ops.agent_traces(
  incident_id STRING, strategy STRING, step_no INT64, model STRING,
  tool_called STRING, input_tokens INT64, output_tokens INT64,
  latency_ms INT64, cost_usd FLOAT64
)
```

`strategy`, `routing_policy` and `run_seq` exist from day one even when only two strategies exist. Partition `ops.run_events` and `ops.data_profiles` by date. Never `SELECT *` — free-tier bytes-scanned matters.

---

## Fault injectors (`eval/faults/`)

```python
class Fault(Protocol):
    root_cause_id: RootCauseId
    name: str

    def setup(self, ctx: FaultContext) -> None: ...
    def teardown(self, ctx: FaultContext) -> None: ...
```

Rules:
- Operate only against the `triage_eval` dataset. Never touch `raw` or `core`.
- `teardown` must fully restore state; it runs even if `setup` raised.
- Assume another fault may already be active. No "reset everything first".
- `setup` returns nothing; the injected ground truth is recorded by the harness, not the fault.

---

## Eval runner rules (`eval/runner.py`)

- Loop: `for strategy in strategies: for incident in incidents: for seq in range(3)`.
- Three repeats always. LLM output is non-deterministic; single runs are noise. Report mean and spread.
- Strip `injected_root_cause` before calling `diagnose`.
- Catch `ValidationError` separately from other exceptions and record it distinctly — a validation failure is a bug in our code, not a finding about the agent.
- Write one row per (incident, strategy, run_seq) to `ops.triage_results`. Never aggregate in Python; aggregate in SQL.
- Cost is computed from `config/pricing.yaml`, never hardcoded in a f-string.

---

## Agent rules

- Tool-call loop capped at 8 steps. Log cap hits; they are a finding, not an error.
- `max_output_tokens` set on every model call.
- System prompt carries pipeline topology and the `RootCauseId` list with one-line descriptions.
- Structured output bound to `TriageResult` via the framework's native Pydantic support.
- Trace every step to `ops.agent_traces` as it happens, not in a post-hoc pass.
- `UNKNOWN` is a legitimate answer. Never prompt the agent to always pick a cause.

---

## Repo layout

```
substrate/pipelines/   ingest_weather, build_gold
substrate/checks/      data quality checks
ops/schemas/           BQ DDL
ops/emitters/          run events, profiles, schema capture
triage/contracts.py    Pydantic models — single source of truth
triage/strategy.py     TriageStrategy protocol
triage/tools/          nine tools
triage/baseline/       rule engine
triage/agents/         langgraph/, adk/
triage/tracing/        cost + OTel GenAI attrs
eval/faults/           composable injectors
eval/runner.py
eval/metrics.sql
infra/                 terraform
```

---

## Style

- Python 3.12+, `uv`, ruff, pytest.
- Type hints on everything; Pydantic at boundaries, plain hints internally.
- No bare `except`. No `Any` in a signature.
- Tests for every tool: one happy path, one empty result, one malformed input that must raise `ValidationError`.
- Keep functions short enough to read in one screen.

---

## When in doubt

Ask rather than invent. The most damaging thing in a multi-session build is a slightly different table shape or result model appearing in week 4 than was agreed in week 1. If a contract here blocks you, raise it explicitly instead of working around it.
