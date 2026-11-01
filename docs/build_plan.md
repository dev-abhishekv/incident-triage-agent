# Agentic Incident Triage for Data Pipelines — Build Plan

**Owner:** Abhishek Patel
**Window:** 18 Oct – 29 Nov 2026 (6 weeks, 8–10 hrs/week, ~55 hrs total)
**Stack:** Python · LangGraph and/or Google ADK · Gemini (Vertex AI) · Cloud Run Jobs · Cloud Workflows · Cloud Scheduler · BigQuery · GCS · Pub/Sub

> **Framework is deliberately left open.** Build the first working agent in LangGraph, then add an ADK implementation of the same strategy. The `TriageStrategy` interface in §1a makes the second one cheap, and having both with eval numbers attached is a stronger artifact than either alone. See §5a for the trade-off.

---

## 0. The one-sentence pitch

An agent that receives a data-pipeline failure event, investigates it using tools over run metadata, schema history, data profiles and lineage, and returns a ranked root cause with evidence and a proposed fix — evaluated against 20 injected faults and benchmarked on accuracy, latency and cost against a deterministic rule-based baseline.

**What this proves that your resume doesn't already:** agent orchestration, evaluation rigour, and cost-aware model routing.

**What it deliberately does not try to prove:** that you can build data pipelines. Four years at Accenture already says that. Keep the substrate small.

---

## 1. Architecture

```
                 ┌──────────────────────────────────────────┐
  Public API ───►│  SUBSTRATE (the thing that breaks)       │
                 │  Cloud Scheduler → Workflows → Run Jobs   │
                 │  GCS raw → BQ bronze → silver → gold      │
                 └───────────────┬──────────────────────────┘
                                 │ emits run events + data checks
                                 ▼
                        Pub/Sub  ──►  BQ `ops.run_events`
                                      BQ `ops.schema_history`
                                      BQ `ops.data_profiles`
                                      BQ `ops.lineage`
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
        BASELINE (rule engine)          TRIAGE AGENT (ADK)
        ~12 deterministic rules          9 tools, Gemini
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                        BQ `ops.triage_results`
                        BQ `ops.agent_traces`  (tokens, latency, model, cost)
                                 │
                                 ▼
                        EVAL HARNESS → metrics + routing curve
```

Everything lands in BigQuery. One query language for the whole project, and it makes the eval reporting trivial.

---

## 1a. Four design decisions to make on day one

Everything in §15 (the expansion list) bolts on cleanly *except* where it crosses one of these four seams. Each costs under an hour now and saves eight to ten later. Make these decisions before you write the first line of agent code.

**1. Put every diagnosis method behind one interface.**

If the eval runner calls a concrete LangGraph or ADK class, then adding plan-then-execute, multi-agent, or a second framework means rewriting the runner. Instead:

```python
class TriageStrategy(Protocol):
    name: str
    def diagnose(self, incident: Incident) -> TriageResult: ...
```

`Incident` and `TriageResult` are **Pydantic models**, not dataclasses or dicts. See §1b.

Make the **rule-based baseline the first implementation**. Then the baseline, every agent architecture, and every framework are all just strategies the runner loops over. This single decision is what makes the ADK-vs-LangGraph comparison and the architecture comparison nearly free.

**2. Put `strategy` and `routing_policy` in `ops.triage_results` from the start.**

They're already in the §3 schema. Don't drop them because v1 only has two values. Adding a dimension to a results table later means re-running every eval you have already paid for.

**3. Make fault injectors composable.**

Each fault is a setup/teardown pair that assumes nothing about the starting state and never assumes it is running alone. Composable: multi-fault incidents become a loop over pairs, two hours. Hardcoded to a clean state: you rebuild all twenty, eight hours.

**4. Grade remediations as you go, and grade 40 not 20.**

When you hand-grade in week 5, do 40. It's an extra 40 minutes at the time, and it is exactly the ground-truth set an LLM judge needs for calibration later. Grading retroactively means re-reading incidents whose context you have forgotten.

---

## 1b. Pydantic contracts, not plain annotations

Every boundary in this project is typed with Pydantic: tool inputs, tool outputs, `Incident`, and `TriageResult`. Plain annotations are documentation that nothing enforces; a tool returning a null where a float was expected then fails somewhere inside an agent loop, which is the worst possible place to debug it. Pydantic moves that failure to the boundary where it happened.

This matters more here than in a normal project because you are deliberately injecting faults. When something breaks you need to know immediately whether the fault caused it or your own tool code did. Validation at the boundary answers that question for free.

**`TriageResult` is the single source of truth.** The same model feeds the agent's structured output, the baseline's return value, and the `ops.triage_results` insert. One definition, three consumers, no drift.

```python
from enum import StrEnum
from pydantic import BaseModel, Field

class RootCauseId(StrEnum):
    SCHEMA_ADDITIVE = "schema_additive"
    SCHEMA_RENAME = "schema_rename"
    # ... all 20 from §4
    UNKNOWN = "unknown"

class Evidence(BaseModel):
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

The `RootCauseId` enum is what constrains the agent to known IDs — the same enum drives the structured-output schema, the baseline's return, and the eval comparison, so a typo cannot silently score as a miss.

**Conventions**
- `extra="forbid"` on `TriageResult` and all tool outputs. Silent extra fields hide bugs.
- Tool inputs as Pydantic models too; both LangGraph and ADK generate their function-calling schemas from them, so you write the contract once and the model sees it.
- Keep models **flat and strict** at the boundaries that matter (tool I/O, `TriageResult`). Don't gold-plate the substrate pipeline code with nested validators.
- Log `ValidationError` separately from pipeline errors in `ops.run_events`. If your eval run shows validation failures, that is your bug, not a finding about the agent.

---

## 2. The substrate — 6 hours, deliberately unambitious

Two pipelines with a dependency between them. The dependency is the point; without it, half the interesting failure modes don't exist.

**Pipeline A — `ingest_weather`** (daily, Cloud Run Job)
- Pull from Open-Meteo's free API (no key required) for ~20 fixed coordinates representing "plant sites"
- Land raw JSON in `gs://<bucket>/raw/weather/dt=YYYY-MM-DD/`
- Parse to `bronze.weather_readings`
- Aggregate to `silver.daily_site_weather`

**Pipeline B — `build_gold_site_daily`** (daily, runs after A)
- Join `silver.daily_site_weather` to a small static `dim_site` table
- Write `gold.site_daily_summary`
- Run data checks: row count vs. 7-day average, null rate per column, duplicate key check, freshness

Backfill ~60 days of history on day one. You need history for "compared to yesterday" reasoning to work at all.

**Orchestration:** Cloud Scheduler → Cloud Workflows → Cloud Run Jobs.
**Do not use Cloud Composer.** It idles at $300+/month and buys you nothing here.

**Shortcut if you're behind:** run both pipelines as a single Cloud Run Job invoked by Scheduler and skip Workflows. You lose a little realism, you save three hours.

---

## 3. Metadata schema

These four tables are what the agent's tools read. Design them first; everything else depends on them.

**`ops.run_events`**
```
run_id, pipeline, task, started_at, ended_at, status,
rows_in, rows_out, bytes_processed, exit_code,
error_type, error_message, log_uri, git_sha, config_json
```

**`ops.schema_history`** — one row per column per observed schema version
```
observed_at, table, column_name, data_type, is_nullable, schema_version
```
Capture by reading `INFORMATION_SCHEMA.COLUMNS` after each run and writing a new version only on change.

**`ops.data_profiles`** — one row per table per partition per run
```
run_id, table, partition_date, row_count,
null_rate_json, distinct_count_json, min_max_json,
duplicate_key_count, profiled_at
```

**`ops.lineage`** — hand-maintained, six rows is fine
```
downstream_table, upstream_table, dependency_type
```

**`ops.triage_results`**
```
incident_id, method ('baseline'|'agent'), routing_policy,
predicted_root_cause_id, confidence, evidence_json,
proposed_remediation, latency_ms, input_tokens, output_tokens, cost_usd
```

---

## 4. The 20 failure modes

Each is injected by a fault-injection script that knows the ground-truth `root_cause_id`. That label is what makes evaluation possible.

The column that matters most is **Signal**: loud faults throw errors and the baseline will catch them; silent faults don't, and that's where the agent earns its keep. Your headline finding will come from splitting accuracy by this column.

| # | root_cause_id | Injection | Signal |
|---|---|---|---|
| 1 | `schema_additive` | Add an unexpected column to the raw JSON | Silent |
| 2 | `schema_rename` | Rename `location_id` → `site_id` in raw | Silent, breaks later |
| 3 | `schema_type_change` | Emit temperature as string instead of float | Loud |
| 4 | `schema_column_dropped` | Remove a required column from raw | Loud |
| 5 | `null_explosion` | Null out 40% of join keys | Loud (join or check) |
| 6 | `duplicate_keys` | Duplicate 10% of rows in bronze | Silent |
| 7 | `unit_change` | Switch temperature °C → °F | Silent |
| 8 | `timezone_shift` | Shift timestamps by +5:30 | Silent |
| 9 | `sentinel_values` | Replace missing readings with `-999` | Silent |
| 10 | `malformed_json` | Corrupt 5% of raw records | Loud |
| 11 | `upstream_empty` | Pipeline A writes 0 rows but exits 0 | Silent |
| 12 | `stale_partition` | A doesn't run; B reads yesterday's partition | Silent |
| 13 | `upstream_failed_downstream_ran` | A fails, B triggered anyway | Loud upstream |
| 14 | `double_load` | Run A twice for the same partition | Silent |
| 15 | `credential_expired` | Invalid API token in Secret Manager | Loud |
| 16 | `iam_permission_denied` | Strip the job's GCS read binding | Loud |
| 17 | `source_rate_limited` | Force HTTP 429 from the source | Loud |
| 18 | `resource_exhausted` | Shrink Cloud Run memory until OOM | Loud |
| 19 | `network_timeout` | Point at an unreachable endpoint | Loud |
| 20 | `config_drift` | Change a partition-column config value | Loud, misleading |

Note #20. It throws an error that points somewhere unhelpful. Misleading-signal cases are the most interesting ones in the writeup.

**Fault injection design:** each fault is a Python function that mutates config or data before a run, plus a teardown. Run them against a dedicated `triage_eval` dataset so your clean history stays clean. Produce ~40 incidents total (20 fault types × 2 variations) if time allows; 20 is the floor.

---

## 5. Agent tool signatures

Nine tools. Each one is a thin, well-documented Python function over BigQuery or GCS. The docstrings are load-bearing: they are what the model reads to decide when to call each tool, so write them for a stranger.

Each tool takes a Pydantic input model and returns a Pydantic output model (§1b). Both LangGraph and ADK generate their function-calling schemas from these, so the contract is written once and the model sees exactly it.

```python
get_run_details(args: GetRunDetailsInput)           -> RunDetails
get_run_history(args: GetRunHistoryInput)           -> RunHistory
get_schema_changes(args: GetSchemaChangesInput)     -> SchemaChanges
get_data_profile(args: GetDataProfileInput)         -> DataProfile
compare_partitions(args: ComparePartitionsInput)    -> PartitionDiff
get_upstream_dependencies(args: GetUpstreamInput)   -> UpstreamDeps
get_freshness(args: GetFreshnessInput)              -> Freshness
search_logs(args: SearchLogsInput)                  -> LogLines
get_recent_config_changes(args: GetConfigChangesInput) -> ConfigChanges
```

Example of the pattern — note that constraints live in the model, not in defensive code inside the function:

```python
class GetDataProfileInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(description="Fully qualified table, e.g. core.site_daily_summary")
    partition_date: date

class DataProfile(BaseModel):
    model_config = {"extra": "forbid"}
    table: str
    partition_date: date
    row_count: int = Field(ge=0)
    null_rates: dict[str, float]
    distinct_counts: dict[str, int]
    duplicate_key_count: int = Field(ge=0)
```

The `Field(description=...)` text is what the model reads when deciding whether to call the tool, so write it for a stranger. This replaces the old advice about load-bearing docstrings: with Pydantic the descriptions live in the schema and reach the model directly.

**Output contract** — `TriageResult` from §1b, used verbatim. Both the agent and the rule baseline return it, and it serialises straight into `ops.triage_results`. Constraining `root_cause_id` to the `RootCauseId` enum is what prevents the agent inventing causes, and keeping `UNKNOWN` in the enum is what stops it guessing to look confident.

**Agent design notes**
- Cap the tool-call loop at 8 steps. Log when you hit the cap; that's a finding.
- System prompt gets the pipeline topology and the list of valid root-cause IDs with one-line descriptions.
- Consider a two-stage split: a cheap model gathers evidence, an expensive one reasons over it. This is what makes the routing experiment in §8 meaningful.
- Check the current docs for whichever framework you start in. Both APIs move fast; don't build from a blog post.

---

## 5a. Framework: LangGraph and ADK, in that order

**The technical gap has genuinely narrowed.** ADK 2.0 added graph-based workflows, so the "LangGraph has explicit graphs, ADK doesn't" argument is no longer true. On a pure-GCP project with Gemini and Vertex, ADK is a defensible first choice: native IAM, no integration layer to build, A2A support.

Three reasons to still start in LangGraph:

| | |
|---|---|
| **Labour market** | LangGraph runs at roughly ten times ADK's monthly download volume and appears by name in Indian job postings constantly; ADK rarely does. Keyword matching by recruiters is a real mechanism, not a theoretical one. |
| **Your resume** | LangGraph currently sits under *Coursework*. Shipping this moves it into *Core Skills* honestly. ADK is already claimed via the Vanderbilt specialization, so it buys you less. |
| **Precedent** | Monte Carlo's Troubleshooting Agent for data-pipeline RCA is built on LangGraph. Building in the same framework makes your comparison direct and citable rather than hand-wavy. |

One real technical point in LangGraph's favour for *this* project: its explicit state machine and checkpointers make each step easy to inspect and replay, which matters when the whole deliverable is an evaluation. ADK's higher-level abstractions can obscure LLM-driven routing decisions, which is exactly what you need visibility into.

**But build both.** Because of the `TriageStrategy` interface in §1a, a second implementation is a contained piece of work, and the eval harness already exists to score it. Then you can say:

> I implemented the same triage agent in LangGraph and ADK and ran both through the same fault set. Accuracy was within noise; the differences were in state inspection, deployment path and cost.

Almost nobody has built the same agent twice in two frameworks with numbers attached. That paragraph is worth more than either framework alone, and it neutralises any interviewer who happens to prefer the one you didn't pick.

**Budget:** 12 hrs for the LangGraph implementation in week 3, 5 hrs for the ADK implementation in week 6. If you fall behind, the ADK version is the first thing to cut.

---

## 6. The deterministic baseline — build this before the agent

About 12 rules. Regex over error messages plus threshold checks over profiles.

```
"OutOfMemory" in log              -> resource_exhausted
"403" or "PermissionDenied"       -> iam_permission_denied
"401" or "invalid_token"          -> credential_expired
"429"                             -> source_rate_limited
null_rate(join_key) > 0.2         -> null_explosion
row_count == 0 upstream           -> upstream_empty
duplicate_key_count > 0           -> duplicate_keys
freshness_hours > 30              -> stale_partition
schema_version changed < 48h      -> schema_rename
...else                           -> unknown
```

Two reasons this comes first. It forces the metadata schema to be complete before you write agent code. And without it your accuracy number is meaningless — "82%" only means something next to "the dumb version got 61%."

Build it honestly. A strawman baseline you rigged to lose is the first thing a sharp interviewer will probe.

---

## 7. Eval harness

**Metrics**

| Metric | Definition |
|---|---|
| Root-cause accuracy | top-1 match against injected `root_cause_id` |
| Accuracy by signal class | split loud vs. silent — your headline finding |
| False-confidence rate | wrong AND confidence > 0.7 |
| Abstention rate | share answered `unknown` |
| Remediation quality | you grade 20 by hand, 0–2 scale |
| Latency | p50 / p95 |
| Cost per incident | USD, from the trace table |
| Tool calls per incident | efficiency proxy |

**Runner:** loop over incidents, run baseline and agent, write to `ops.triage_results`, aggregate with one SQL query. Keep it a script, not a notebook — it's a deliverable.

**Run each configuration 3 times.** LLM outputs are non-deterministic and single-run numbers are noise. Report mean and spread. Very few portfolio projects do this and it is immediately visible to anyone who evaluates models for a living.

---

## 8. Tracing, cost and the routing experiment

**Trace every step** into `ops.agent_traces`: `incident_id, step_no, model, tool_called, input_tokens, output_tokens, latency_ms, cost_usd`. Use the OpenTelemetry GenAI semantic convention attribute names rather than inventing your own, and say so in the writeup.

Compute cost from a small pricing config keyed by model. Verify current Vertex AI Gemini prices when you build it.

**The routing experiment** — three policies, same eval set:

| Policy | Evidence gathering | Reasoning |
|---|---|---|
| `all_cheap` | Flash | Flash |
| `all_premium` | Pro | Pro |
| `tiered` | Flash | Pro |

Plot accuracy against cost per incident. The output you want is a sentence like: *"tiered routing reached 82% at $0.004/incident; all-premium reached 85% at $0.026 — 3 points of accuracy for 6.5× the cost."*

That single sentence is the most valuable artifact in this project. It demonstrates agent engineering, evaluation and cost discipline at once, and almost no candidate can say it about a system they built.

---

## 9. Schedule

### Week 1 · 18–24 Oct · ~9 hrs — Substrate
- [x] GCP project, billing alerts at $50 and $100 (configured in INR), enable APIs (1h)
- [x] Check **Billing → Credits** for eligible SKUs and expiry date
- [x] Repo, `uv`, ruff, pytest, GitHub Actions skeleton (1h)
- [x] **Define Pydantic contracts and `TriageStrategy` interface (§1a, §1b) — 45 min, do it first**
- [x] Pipeline A: API → GCS → bronze → silver (3h)
- [x] Pipeline B: gold join + data checks (2h)
- [x] Scheduler → Workflows → Run Jobs, deployed and running daily (1h)
- [x] Backfill 60 days (0.5h)

### Week 2 · 25–31 Oct · ~9 hrs — Metadata, tools, baseline
- [ ] Four `ops.*` tables, including `strategy` and `routing_policy` columns from the start (§1a) (3h)
- [ ] Nine tools with Pydantic input/output models and unit tests (4h)
- [ ] Rule-based baseline as the first `TriageStrategy` implementation, ~12 rules (2h)

### Week 3 · 1–7 Nov · ~10 hrs — LangGraph agent
- [ ] LangGraph graph skeleton, tools registered, runs locally (4h)
- [ ] System prompt, structured output schema, loop cap (2h)
- [ ] Trace instrumentation + cost capture wired in now, not later (2h)
- [ ] Manual iteration on 5 hand-made incidents until it behaves (2h)

### Week 4 · 8–14 Nov · ~10 hrs — Faults and evals
- [ ] Fault injection framework, composable setup/teardown (§1a) (3h)
- [ ] All 20 faults implemented, incidents generated (4h)
- [ ] Eval runner looping over strategies + aggregation SQL (2h)
- [ ] First full eval run, baseline vs. agent (1h)

### Week 5 · 15–21 Nov · ~9 hrs — Routing, writeup, ship
- [ ] Deploy agent to Cloud Run, Pub/Sub-triggered (1h)
- [ ] Routing experiment, 3 policies × 3 runs (2h)
- [ ] Hand-grade 40 remediations (§1a) (1h)
- [ ] README + writeup (3h)
- [ ] Resume, LinkedIn, Naukri updated (1h)

**v1 is shippable at the end of week 5.** Treat 21 November as the real deadline. Week 6 is upside.

### Week 6 · 22–29 Nov · ~8 hrs — ADK comparison and polish
- [ ] ADK implementation of `TriageStrategy`, same tools (5h)
- [ ] Run it through the existing eval harness, write the comparison (1h)
- [ ] 4-minute demo video (2h)

**If you fall behind, cut in this order:** ADK implementation (week 6) → number of faults (20 → 12, keeping the loud/silent balance) → Workflows orchestration → number of tools (9 → 6) → routing experiment down to 2 policies.

**Never cut:** the baseline, the eval harness, the writeup. Those three *are* the project.

---

## 10. Repo structure

```
pipeline-triage-agent/
├── README.md                 # the writeup — most-read file
├── substrate/
│   ├── pipelines/            # ingest_weather, build_gold
│   ├── checks/               # data quality checks
│   └── workflows/            # Workflows YAML, Scheduler config
├── ops/
│   ├── schemas/              # BQ DDL for ops.* tables
│   └── emitters/             # run events, profiles, schema capture
├── triage/
│   ├── tools/                # the 9 tools
│   ├── baseline/             # rule engine
│   ├── agent/                # ADK agent, prompts, output schema
│   └── tracing/              # OTel attrs, cost calculation
├── eval/
│   ├── faults/               # 20 injectors
│   ├── runner.py
│   ├── metrics.sql
│   └── results/              # committed CSVs + charts
├── infra/                    # Terraform
└── docs/
    ├── ARCHITECTURE.md
    ├── FAILURE_MODES.md
    └── FINDINGS.md
```

Terraform is a cheap win here. You already know it from WBD and it takes an evening.

---

## 11. The writeup

Order matters. Lead with the finding, not the architecture.

1. **The problem** — a real alert, and the 20 minutes of human detective work behind it (use the §0 example from our conversation)
2. **Results table** — baseline vs. agent vs. routing policies, accuracy / latency / cost
3. **The accuracy-vs-cost chart**
4. **Where the agent lost to the baseline** — the most valuable section in the document
5. **Failure modes of the agent itself** — hallucinated causes, loop-cap hits, over-confidence
6. **Architecture**
7. **What I'd do differently at production scale**

Section 4 is not a disclaimer. It's the evidence that you evaluated honestly instead of demoing a happy path, and it's what separates you from the candidate whose project only ever worked.

**Demo video, 4 minutes:** the problem (30s), one live triage end to end (90s), the eval harness running (60s), the results chart (45s). Unlisted YouTube, linked from the README and LinkedIn.

---

## 12. Positioning

**Resume** — under Independent Projects. Only add real numbers once you have them:

> **Agentic Incident Triage for Data Pipelines** · *Google ADK · Gemini · Cloud Run · BigQuery · Pub/Sub · Terraform*
> - Built an agent that diagnoses data-pipeline failures from run metadata, schema history, data profiles and lineage, returning a ranked root cause with evidence and a proposed remediation behind a human-approval gate.
> - Evaluated against [N] injected failure modes with a deterministic rule-based baseline: [X]% root-cause accuracy vs. [Y]% baseline, with the gap concentrated in silent failures that produce no error signal.
> - Instrumented per-step token, latency and cost tracing; tiered model routing held [X]% accuracy at [Z]× lower cost per incident than premium-only routing.

**The interview sentence:** "I ran Databricks platforms for four years and spent a lot of mornings doing root-cause triage by hand. So I built the agent I wanted, and then I built the harness to find out whether it was actually better than a rule engine."

**Honesty line, hold it firmly:** this is a personal project on synthetic faults. Never let it drift into sounding like production work. The measured results are strong enough on their own, and the moment an interviewer catches an inflated claim, everything else you said becomes suspect.

---

## 13. Cost guardrails

- Billing alerts at $50 and $100 on day one
- BigQuery: set a custom query quota per day; at this volume you'll likely stay inside the free tier
- Cloud Run: `min-instances=0`, always
- Gemini: cap max output tokens; the loop cap bounds worst-case spend per incident
- Realistic total: **$40–90**. If you cross $200, something is misconfigured — stop and check before adding credit.

---

## 14. Open items to verify before you build

1. **Credit eligibility** — Billing → Credits, note eligible SKUs and expiry date
2. **Current LangGraph and ADK API surfaces** — official docs only, both move fast
3. **Current Vertex AI Gemini pricing** — needed for the cost config to be honest
4. **Databricks Free Edition** — only if MLflow tracing/eval drops in within one evening; otherwise skip
5. **Open-Meteo terms** — confirm the free tier covers your call volume

---

## 15. Full service and tool inventory — for cost checking

Every paid or potentially-paid thing this project touches. Verify all pricing yourself before you start; figures below are order-of-magnitude expectations for *this* workload only, not quotes.

### GCP services (billable)

| Service | What it's used for | Pricing dimension to check | Expected here |
|---|---|---|---|
| **Vertex AI — Gemini** | Agent reasoning, evidence gathering, routing experiment | Input and output tokens, per model (Flash vs Pro) | The only meaningful cost. Dominated by eval runs: 20 faults × 2 variations × 3 strategies × 3 repeats |
| **BigQuery** | All `ops.*` tables, substrate tables, eval aggregation | Query bytes scanned + active storage; both have a monthly free tier | Likely free at this volume if you partition and avoid `SELECT *` |
| **Cloud Run Jobs** | Substrate pipeline execution | vCPU-seconds, memory-seconds, requests; generous free tier | Pennies |
| **Cloud Run Service** | Hosting the deployed agent endpoint | Same, plus idle if `min-instances > 0` | Pennies at `min-instances=0` |
| **Cloud Scheduler** | Daily pipeline trigger | Per job per month; small free allowance | Free |
| **Cloud Workflows** | Orchestrating A → B | Per step executed; free tier covers low volume | Free |
| **Pub/Sub** | Run events, agent trigger | Volume of data published; free tier allowance | Free |
| **Cloud Storage** | Raw JSON landing zone | Storage GB-month, operations, egress | Cents |
| **Artifact Registry** | Container images for Cloud Run | Storage GB-month above free allowance | Cents |
| **Secret Manager** | API tokens (and the `credential_expired` fault) | Active secret versions, access operations | Cents |
| **Cloud Logging** | `search_logs` tool source | Ingestion GB above monthly free allotment | Free if you don't log verbosely |

### Explicitly avoided — check these are NOT enabled

| Service | Why avoided |
|---|---|
| **Cloud Composer** | Idles at $300+/month regardless of usage. Workflows + Scheduler do this job for free. |
| **Dataflow** | Per-worker-hour billing; unnecessary unless you add the streaming extension, and even then a Cloud Run consumer is cheaper. |
| **Vertex AI endpoints / Workbench** | Idle-time billing. You are calling Gemini via API, not deploying a model or running a notebook instance. |
| **BigQuery slot reservations** | On-demand is correct at this scale. |

### Free / no-cost dependencies

| Thing | Notes |
|---|---|
| **Open-Meteo API** | Free, no key, but confirm the non-commercial terms and rate limits cover 20 coordinates daily plus a 60-day backfill |
| **LangGraph (OSS)** | Free. LangGraph *Platform* is the paid hosted product — you do not need it. |
| **LangSmith** | Optional tracing. Has a free tier; you are building your own trace table anyway, so treat as optional. |
| **Google ADK (OSS)** | Free. Billing comes only from the Gemini calls underneath. |
| **GitHub + GitHub Actions** | Free for public repos |
| **Databricks Free Edition** | Free, optional, only if MLflow eval tooling earns its setup time |

### Cost control checklist before first agent run

- [ ] Billing alerts live at $50 and $100
- [ ] BigQuery custom query quota set per day
- [ ] `min-instances=0` on every Cloud Run service
- [ ] `max_output_tokens` capped on every Gemini call
- [ ] Tool-call loop capped at 8 steps (bounds worst-case spend per incident)
- [ ] Eval runs use Flash by default; Pro only inside the routing experiment
- [ ] A pricing config file in the repo, keyed by model, so cost numbers in the README are computed rather than guessed

**Expected total across the six weeks: $40–90.** If you cross $200, stop and find the misconfiguration before topping up credit. The usual culprits are an idle Vertex endpoint, a Composer environment someone enabled by accident, or an uncapped loop.
