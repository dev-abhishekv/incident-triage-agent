"""Helper to compute and record data profile statistics into ops.data_profiles."""

import json
import os
from datetime import UTC, date, datetime
from typing import Any

try:
    from google.cloud import bigquery
except ImportError:
    bigquery = None  # type: ignore[assignment]


def emit_data_profile(
    run_id: str,
    table_name: str,
    partition_date: date,
    records: list[dict[str, Any]],
    duplicate_key_count: int = 0,
    project_id: str | None = None,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    row_count = len(records)

    null_rates: dict[str, float] = {}
    distinct_counts: dict[str, int] = {}
    min_max: dict[str, dict[str, Any]] = {}

    if row_count > 0:
        keys = records[0].keys()
        for k in keys:
            vals = [r.get(k) for r in records]
            nulls = sum(1 for v in vals if v is None)
            null_rates[k] = round(nulls / row_count, 4)

            non_nulls = [v for v in vals if v is not None]
            distinct_counts[k] = len(set(non_nulls))

            if non_nulls and isinstance(non_nulls[0], int | float):
                min_max[k] = {"min": min(non_nulls), "max": max(non_nulls)}

    profile = {
        "run_id": run_id,
        "table_name": table_name,
        "partition_date": partition_date.isoformat(),
        "row_count": row_count,
        "null_rate_json": json.dumps(null_rates),
        "distinct_count_json": json.dumps(distinct_counts),
        "min_max_json": json.dumps(min_max),
        "duplicate_key_count": duplicate_key_count,
        "profiled_at": datetime.now(UTC).isoformat(),
    }

    if client:
        table_id = f"{project}.ops.data_profiles"
        try:
            errors = client.insert_rows_json(table_id, [profile])
            if errors:
                print(f"[WARN] Failed to insert profile into {table_id}: {errors}")
        except Exception as e:
            print(f"[WARN] BigQuery insert error for {table_id}: {e}")

    return profile
