# Week 1 Spec — Substrate and Contracts

**Window:** 18–24 Oct 2026 · ~9 hrs
**Exit condition:** the daily pipeline has run unattended at least once, 60 days of history exist, `ops.*` tables are populated by real runs, and the Pydantic contracts are committed.

Written as Gherkin so each item is verifiable rather than vibes. Scenarios marked **[AUTOMATED]** should become pytest tests in `tests/`; the rest are manual checks you run once and tick off.

---

## Feature: Infrastructure foundation

```gherkin
Feature: GCP foundation provisioned as code
  So that the environment is reproducible and cost is bounded

  Scenario: Terraform applies cleanly from empty project
    Given a GCP project with billing enabled
    And no triage resources exist
    When I run "terraform apply"
    Then the datasets raw, core, ops and triage_eval exist in asia-south1
    And a GCS bucket named "<project>-triage-raw" exists
    And an Artifact Registry repository "triage-images" exists
    And the service accounts triage-pipeline, triage-agent, triage-scheduler exist
    And a billing budget of 100 USD exists with alerts at 25%, 50% and 100%

  Scenario: The agent service account cannot write to source data
    Given the Terraform state is applied
    When I inspect IAM bindings for the triage-agent service account
    Then it has bigquery.dataViewer on raw, core and triage_eval
    And it has bigquery.dataEditor on ops only
    And it has no storage.objectAdmin binding on any bucket

  Scenario: Terraform is idempotent
    Given "terraform apply" has completed successfully
    When I run "terraform plan" again
    Then the plan reports no changes

  Scenario: Expensive services stay disabled
    When I list enabled services for the project
    Then composer.googleapis.com is not enabled
    And dataflow.googleapis.com is not enabled
    And no Vertex AI endpoint or Workbench instance exists
```

---

## Feature: Contracts defined before any code depends on them

```gherkin
Feature: Pydantic contracts
  So that every later component shares one definition

  Scenario: TriageResult rejects an unknown root cause [AUTOMATED]
    Given the contracts module is importable
    When I construct a TriageResult with root_cause_id "definitely_not_real"
    Then a ValidationError is raised

  Scenario: TriageResult rejects out-of-range confidence [AUTOMATED]
    When I construct a TriageResult with confidence 1.4
    Then a ValidationError is raised

  Scenario: TriageResult rejects undeclared fields [AUTOMATED]
    When I construct a TriageResult with an extra field "notes"
    Then a ValidationError is raised

  Scenario: UNKNOWN is a valid answer [AUTOMATED]
    When I construct a TriageResult with root_cause_id UNKNOWN
    And confidence 0.0
    And an empty evidence list
    Then the model validates successfully

  Scenario: TriageResult round-trips through JSON [AUTOMATED]
    Given a populated TriageResult
    When I serialise it with model_dump_json and parse it back
    Then the parsed model equals the original

  Scenario: The strategy protocol is satisfiable [AUTOMATED]
    Given a stub class with name, routing_policy and diagnose(incident) -> TriageResult
    When I type-check the module
    Then it is accepted as a TriageStrategy with no errors
```

> Do this block **first**, before the pipeline. 45 minutes. Everything in weeks 2–6 imports from it.

---

## Feature: Pipeline A — weather ingestion

```gherkin
Feature: Ingest weather readings for 20 sites
  So that there is a real pipeline capable of failing realistically

  Background:
    Given 20 fixed site coordinates are defined in config
    And the Open-Meteo API is reachable

  Scenario: A successful daily run lands raw data
    When the ingest stage runs for partition date D
    Then raw JSON exists at gs://<bucket>/raw/weather/dt=D/
    And one object exists per site

  Scenario: Raw data is parsed into a partitioned bronze table
    Given raw JSON exists for partition date D
    When the parse stage runs
    Then raw.weather_readings contains rows for partition D
    And the table is partitioned by partition_date
    And row count equals sites multiplied by readings per site

  Scenario: Bronze is aggregated to silver
    Given raw.weather_readings has rows for partition D
    When the aggregate stage runs
    Then core.daily_site_weather contains exactly 20 rows for partition D
    And every row has a non-null site_id

  Scenario: Re-running a partition does not duplicate rows
    Given core.daily_site_weather has rows for partition D
    When the pipeline runs again for partition D
    Then the row count for partition D is unchanged

  Scenario: Backfill respects API call weighting
    Given no history exists
    When I run the 60-day backfill
    Then requests are chunked per site rather than one multi-variable bulk pull
    And total API calls consumed stay under 10 percent of the daily quota
    And 60 distinct partition dates exist in core.daily_site_weather
```

---

## Feature: Pipeline B — gold layer with data checks

```gherkin
Feature: Build the gold summary and run data checks
  So that silent data faults have somewhere to surface

  Scenario: Gold joins silver to the site dimension
    Given core.daily_site_weather has 20 rows for partition D
    And dim_site contains 20 sites
    When the gold stage runs for partition D
    Then core.site_daily_summary contains 20 rows for partition D
    And no row has a null site_name

  Scenario: Data checks run and record results
    When the gold stage completes for partition D
    Then a row count check has run against the trailing 7-day mean
    And a null-rate check has run for every column
    And a duplicate-key check has run on (site_id, partition_date)
    And a freshness check has run on the upstream table
    And each check result is recorded with pass or fail

  Scenario: A failing data check marks the run failed
    Given the duplicate-key check finds duplicates
    When the gold stage completes
    Then the run status recorded is FAILED
    And error_type is "data_check_failed"

  Scenario: Pipeline B does not run when Pipeline A failed
    Given Pipeline A ended with status FAILED for partition D
    When the daily orchestration executes
    Then Pipeline B is not executed for partition D
```

> The last scenario is deliberate: fault 13 (`upstream_failed_downstream_ran`) works by *breaking* this guard. Build the guard now so there is something to break.

---

## Feature: Metadata emission

```gherkin
Feature: Every run writes the metadata the agent will read
  So that the tools in week 2 have real data to query

  Scenario: Each stage emits a run event
    When any pipeline stage completes, successfully or not
    Then exactly one row is appended to ops.run_events
    And it carries run_id, pipeline, stage, started_at, ended_at, status
    And it carries rows_in, rows_out and exit_code
    And it carries the git_sha of the deployed image
    And on failure it carries error_type and error_message

  Scenario: Schema history records only changes
    Given raw.weather_readings has been observed before with no schema change
    When the schema capture step runs
    Then no new rows are written to ops.schema_history

  Scenario: Schema history records a new version on change [AUTOMATED]
    Given a column is added to raw.weather_readings
    When the schema capture step runs
    Then new rows are written with schema_version incremented by one
    And the previous version's rows are left untouched

  Scenario: Profiles are written per table per partition
    When a pipeline stage writes to a table for partition D
    Then one row is appended to ops.data_profiles for that table and partition
    And it carries row_count, null_rate_json, distinct_count_json
    And it carries min_max_json and duplicate_key_count

  Scenario: Lineage is populated
    When the deployment completes
    Then ops.lineage contains the edge core.daily_site_weather -> core.site_daily_summary
    And ops.lineage contains the edge raw.weather_readings -> core.daily_site_weather

  Scenario: Results tables exist with the full column set
    When I describe ops.triage_results
    Then the columns strategy, routing_policy and run_seq are present
    Even though only the baseline strategy exists so far
```

> That last scenario looks pointless this week. It is the §1a seam: adding a dimension later means re-running every eval already paid for.

---

## Feature: Scheduled unattended operation

```gherkin
Feature: The pipeline runs without me
  So that history accumulates and failures are real rather than staged

  Scenario: The scheduler triggers the job daily
    Given the Cloud Run Job is deployed
    And Cloud Scheduler is configured for 07:00 IST
    When 24 hours elapse
    Then a new run_id appears in ops.run_events
    And I did not trigger it manually

  Scenario: Cost stays near zero
    Given the pipeline has run daily for one week
    When I check billing for the project
    Then total spend is under 5 USD
    And no charge appears for Composer, Dataflow or a Vertex endpoint
```

---

## Definition of done

Tick all before starting week 2. Anything unticked becomes a blocker later, not a nice-to-have.

- [x] `terraform plan` reports no changes
- [x] `triage/contracts.py` committed; the six contract scenarios pass as pytest tests
- [x] `TriageStrategy` protocol committed in `triage/strategy.py`
- [x] 60 partitions present in `core.daily_site_weather`
- [x] At least one unattended scheduled run visible in `ops.run_events`
- [x] `ops.run_events`, `ops.schema_history`, `ops.data_profiles`, `ops.lineage` all non-empty
- [x] `ops.triage_results` and `ops.agent_traces` created with full column sets, empty is fine
- [x] Spend under 5 USD (verified with GCP budget)
- [x] Repo public, README stub committed

---

## If you fall behind

Cut in this order, and keep the week boundary:

1. Workflows orchestration — run both pipelines inside one Cloud Run Job
2. GCS raw landing — write the API response straight to `raw.weather_readings`
3. Backfill 60 days → 30 days

**Do not cut:** the contracts block, metadata emission, or the scheduled run. Weeks 2 through 6 all stand on those three.
