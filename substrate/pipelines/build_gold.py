"""Pipeline B: build_gold

1. Reads silver layer (core.daily_site_weather) for partition date D
2. Joins with static site dimension (dim_site) to build core.site_daily_summary
3. Executes 4 automated data quality checks (row count, null rate, duplicate keys, freshness)
4. If checks fail: marks run FAILED with error_type="data_check_failed"
5. Emits execution telemetry to ops.run_events and ops.data_profiles
"""

import argparse
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ops.emitters.data_profiles import emit_data_profile
from ops.emitters.run_events import emit_run_event
from substrate.checks.data_quality import DataQualityError, evaluate_gold_checks

try:
    from google.cloud import bigquery
    HAS_BIGQUERY = True
except ImportError:
    bigquery = None  # type: ignore[assignment]
    HAS_BIGQUERY = False


def load_dim_site() -> dict[str, dict[str, Any]]:
    """Load dim_site dimension mapping from config/sites.yaml."""
    config_path = Path("config/sites.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parents[2] / "config" / "sites.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return {s["site_id"]: s for s in data.get("sites", [])}


def join_silver_to_gold(
    silver_records: list[dict[str, Any]],
    dim_sites: dict[str, dict[str, Any]],
    target_date: date,
) -> list[dict[str, Any]]:
    """Join silver weather metrics with site dimension attributes to build gold summaries."""
    gold_records = []
    dt_str = target_date.isoformat()
    now_iso = datetime.now(UTC).isoformat()

    for r in silver_records:
        site_id = r["site_id"]
        site_meta = dim_sites.get(site_id, {})

        gold_records.append(
            {
                "site_id": site_id,
                "site_name": site_meta.get("name"),
                "sector": site_meta.get("sector"),
                "state": site_meta.get("state"),
                "partition_date": dt_str,
                "avg_temp": r.get("avg_temp"),
                "min_temp": r.get("min_temp"),
                "max_temp": r.get("max_temp"),
                "total_precipitation": r.get("total_precipitation"),
                "avg_humidity": r.get("avg_humidity"),
                "summary_generated_at": now_iso,
            }
        )
    return gold_records


def run_gold_pipeline(
    target_date: date | None = None,
    silver_input: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
    upstream_failed: bool = False,
) -> dict[str, Any]:
    """Execute Pipeline B end-to-end for a specific partition date."""
    run_id = f"run-gold-{uuid.uuid4().hex[:8]}"
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    start_time = datetime.now(UTC)

    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    print(f"[PIPELINE B] Starting run {run_id} for partition date {target_date}")

    bq_client = None
    if HAS_BIGQUERY:
        try:
            bq_client = bigquery.Client(project=project)
        except Exception as e:
            print(f"[INFO] Cloud BigQuery client unavailable locally: {e}")

    # Guard: If Pipeline A failed, Pipeline B must not execute
    if upstream_failed:
        print("[GUARD] Upstream Pipeline A marked FAILED. Halting Pipeline B.")
        emit_run_event(
            run_id=run_id,
            pipeline="build_gold",
            stage="guard_check",
            started_at=start_time,
            ended_at=datetime.now(UTC),
            status="FAILED",
            error_type="upstream_dependency_failed",
            error_message="Pipeline B aborted: Upstream Pipeline A failed for this partition",
            project_id=project,
            client=bq_client,
        )
        return {
            "run_id": run_id,
            "status": "FAILED",
            "reason": "upstream_dependency_failed",
        }

    # Fetch silver records
    silver_records = silver_input
    if silver_records is None and bq_client:
        table_silver = f"{project}.core.daily_site_weather"
        query = f"SELECT * FROM `{table_silver}` WHERE partition_date = '{target_date.isoformat()}'"
        try:
            silver_records = [dict(row) for row in bq_client.query(query).result()]
        except Exception as e:
            print(f"[WARN] Failed to query BigQuery silver layer: {e}")

    silver_records = silver_records or []
    dim_sites = load_dim_site()

    # Step 1: Join to Gold
    gold_records = join_silver_to_gold(silver_records, dim_sites, target_date)

    # Step 2: Run Data Quality Checks
    upstream_d = target_date if silver_records else (target_date - timedelta(days=2))
    check_results = evaluate_gold_checks(
        records=gold_records,
        target_date=target_date,
        upstream_date=upstream_d,
    )

    failed_checks = [c for c in check_results if not c.passed]

    if failed_checks:
        error_msg = "; ".join(f"{c.check_name}: {c.message}" for c in failed_checks)
        print(f"[DATA CHECK FAILED] {error_msg}")
        emit_run_event(
            run_id=run_id,
            pipeline="build_gold",
            stage="data_quality_checks",
            started_at=start_time,
            ended_at=datetime.now(UTC),
            status="FAILED",
            rows_in=len(silver_records),
            rows_out=len(gold_records),
            exit_code=1,
            error_type="data_check_failed",
            error_message=error_msg,
            project_id=project,
            client=bq_client,
        )
        raise DataQualityError(error_msg, failed_checks=failed_checks)

    # Step 3: Write to BigQuery (Idempotent DELETE + INSERT)
    if bq_client and gold_records:
        table_gold = f"{project}.core.site_daily_summary"
        dt_iso = target_date.isoformat()
        del_sql = f"DELETE FROM `{table_gold}` WHERE partition_date = '{dt_iso}'"
        try:
            bq_client.query(del_sql).result()
            bq_client.insert_rows_json(table_gold, gold_records)
        except Exception as e:
            print(f"[WARN] Failed BigQuery gold insert: {e}")

    # Emit telemetry & profile
    end_time = datetime.now(UTC)
    emit_run_event(
        run_id=run_id,
        pipeline="build_gold",
        stage="gold_summary",
        started_at=start_time,
        ended_at=end_time,
        status="SUCCESS",
        rows_in=len(silver_records),
        rows_out=len(gold_records),
        exit_code=0,
        project_id=project,
        client=bq_client,
    )

    emit_data_profile(
        run_id=run_id,
        table_name="core.site_daily_summary",
        partition_date=target_date,
        records=gold_records,
        project_id=project,
        client=bq_client,
    )

    print(f"[PIPELINE B SUCCESS] Run {run_id} completed. Generated {len(gold_records)} gold rows.")
    return {
        "run_id": run_id,
        "status": "SUCCESS",
        "gold_rows": len(gold_records),
        "duration_sec": (end_time - start_time).total_seconds(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline B: Build Gold Site Summary")
    parser.add_argument("--date", type=str, help="Target partition date (YYYY-MM-DD)")
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    run_gold_pipeline(target_date=target)
