"""Helper to record stage run events into ops.run_events."""

import json
import os
from datetime import datetime
from typing import Any

try:
    from google.cloud import bigquery
except ImportError:
    bigquery = None  # type: ignore[assignment]


def emit_run_event(
    run_id: str,
    pipeline: str,
    stage: str,
    started_at: datetime,
    ended_at: datetime,
    status: str,  # 'SUCCESS' | 'FAILED'
    rows_in: int = 0,
    rows_out: int = 0,
    bytes_processed: int = 0,
    exit_code: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
    log_uri: str | None = None,
    git_sha: str | None = None,
    config: dict[str, Any] | None = None,
    project_id: str | None = None,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    git_sha = git_sha or os.getenv("GIT_SHA", "unknown")

    record = {
        "run_id": run_id,
        "pipeline": pipeline,
        "stage": stage,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "status": status,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "bytes_processed": bytes_processed,
        "exit_code": exit_code,
        "error_type": error_type,
        "error_message": error_message,
        "log_uri": log_uri,
        "git_sha": git_sha,
        "config_json": json.dumps(config or {}),
    }

    if client:
        table_id = f"{project}.ops.run_events"
        errors = client.insert_rows_json(table_id, [record])
        if errors:
            print(f"[WARN] Failed to insert run event into {table_id}: {errors}")

    return record
