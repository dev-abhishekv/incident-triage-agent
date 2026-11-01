"""Pipeline A: ingest_weather

1. Ingests hourly weather data from Open-Meteo API for 20 verified plant sites
2. Lands raw JSON in GCS: gs://<bucket>/raw/weather/dt=YYYY-MM-DD/<site_id>.json
3. Parses raw JSON to bronze: raw.weather_readings (partitioned by partition_date)
4. Aggregates bronze to silver: core.daily_site_weather (partitioned by partition_date)
5. Records execution telemetry to ops.run_events and ops.data_profiles
"""

import argparse
import json
import os
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from google.cloud import bigquery, storage

    HAS_GOOGLE_CLOUD = True
except ImportError:
    bigquery = None  # type: ignore[assignment]
    storage = None  # type: ignore[assignment]
    HAS_GOOGLE_CLOUD = False

from ops.emitters.data_profiles import emit_data_profile
from ops.emitters.run_events import emit_run_event

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def load_sites_config() -> list[dict[str, Any]]:
    """Load the 20 verified plant coordinates from config/sites.yaml."""
    config_path = Path("config/sites.yaml")
    if not config_path.exists():
        # Fallback to absolute or relative search
        config_path = Path(__file__).parents[2] / "config" / "sites.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("sites", [])


def fetch_site_weather(
    client: httpx.Client,
    site: dict[str, Any],
    start_date: date,
    end_date: date,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Fetch hourly weather data from Open-Meteo for a given site and date range."""
    params = {
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m,precipitation",
        "timezone": "UTC",
    }
    for attempt in range(max_retries):
        try:
            resp = client.get(OPEN_METEO_FORECAST_URL, params=params)
            if resp.status_code == 200:
                payload = resp.json()
                payload["site_id"] = site["site_id"]
                payload["site_name"] = site["name"]
                return payload
            time.sleep(0.5)
        except httpx.RequestError as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Failed to fetch weather for {site['site_id']}: {exc}") from exc
            time.sleep(1.0)
    raise RuntimeError(f"Open-Meteo returned status {resp.status_code} for {site['site_id']}")


def land_raw_json(
    raw_payloads: dict[str, dict[str, Any]],
    target_date: date,
    bucket_name: str | None,
    storage_client: storage.Client | None,
) -> list[str]:
    """Land raw JSON payloads in GCS or local storage."""
    landed_uris = []
    dt_str = target_date.isoformat()

    for site_id, payload in raw_payloads.items():
        blob_path = f"raw/weather/dt={dt_str}/{site_id}.json"
        content = json.dumps(payload, indent=2)

        if storage_client and bucket_name:
            try:
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                blob.upload_from_string(content, content_type="application/json")
                landed_uris.append(f"gs://{bucket_name}/{blob_path}")
                continue
            except Exception as e:
                print(f"[WARN] Failed GCS upload for {site_id}, falling back to local: {e}")

        # Local fallback landing
        local_dir = Path("data/raw/weather") / f"dt={dt_str}"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file = local_dir / f"{site_id}.json"
        local_file.write_text(content, encoding="utf-8")
        landed_uris.append(str(local_file))

    return landed_uris


def parse_raw_to_bronze(
    raw_payloads: dict[str, dict[str, Any]],
    target_date: date,
) -> list[dict[str, Any]]:
    """Transform raw API responses into individual hourly readings for raw.weather_readings."""
    bronze_records = []
    ingested_at = datetime.now(UTC).isoformat()
    dt_str = target_date.isoformat()

    for site_id, payload in raw_payloads.items():
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        humidities = hourly.get("relative_humidity_2m", [])
        precips = hourly.get("precipitation", [])

        for i, time_str in enumerate(times):
            # Check partition date match
            if time_str.startswith(dt_str):
                bronze_records.append(
                    {
                        "site_id": site_id,
                        "partition_date": dt_str,
                        "reading_time": time_str,
                        "temperature_2m": temps[i] if i < len(temps) else None,
                        "relative_humidity_2m": humidities[i] if i < len(humidities) else None,
                        "precipitation": precips[i] if i < len(precips) else None,
                        "ingested_at": ingested_at,
                    }
                )
    return bronze_records


def aggregate_bronze_to_silver(
    bronze_records: list[dict[str, Any]],
    target_date: date,
) -> list[dict[str, Any]]:
    """Aggregate hourly readings to daily site statistics for core.daily_site_weather."""
    silver_records = []
    aggregated_at = datetime.now(UTC).isoformat()
    dt_str = target_date.isoformat()

    # Group by site_id
    by_site: dict[str, list[dict[str, Any]]] = {}
    for r in bronze_records:
        by_site.setdefault(r["site_id"], []).append(r)

    for site_id, readings in by_site.items():
        valid_temps = [r["temperature_2m"] for r in readings if r["temperature_2m"] is not None]
        valid_humidities = [
            r["relative_humidity_2m"] for r in readings if r["relative_humidity_2m"] is not None
        ]
        valid_precips = [r["precipitation"] for r in readings if r["precipitation"] is not None]

        avg_temp = round(sum(valid_temps) / len(valid_temps), 2) if valid_temps else None
        min_temp = min(valid_temps) if valid_temps else None
        max_temp = max(valid_temps) if valid_temps else None
        total_precip = round(sum(valid_precips), 2) if valid_precips else 0.0
        avg_humidity = (
            round(sum(valid_humidities) / len(valid_humidities), 2) if valid_humidities else None
        )

        silver_records.append(
            {
                "site_id": site_id,
                "partition_date": dt_str,
                "avg_temp": avg_temp,
                "min_temp": min_temp,
                "max_temp": max_temp,
                "total_precipitation": total_precip,
                "avg_humidity": avg_humidity,
                "reading_count": len(readings),
                "aggregated_at": aggregated_at,
            }
        )
    return silver_records


def run_ingest_pipeline(
    target_date: date | None = None,
    backfill_days: int | None = None,
    project_id: str | None = None,
    bucket_name: str | None = None,
) -> dict[str, Any]:
    """Execute Pipeline A end-to-end for a specific partition date or backfill range."""
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    bucket = bucket_name or os.getenv("GCS_RAW_BUCKET")

    start_time = datetime.now(UTC)
    sites = load_sites_config()

    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    start_date = target_date - timedelta(days=(backfill_days - 1)) if backfill_days else target_date
    end_date = target_date

    print(f"[PIPELINE A] Starting run {run_id} for {start_date} to {end_date} ({len(sites)} sites)")

    bq_client = None
    storage_client = None
    try:
        bq_client = bigquery.Client(project=project)
        storage_client = storage.Client(project=project)
    except Exception as e:
        print(f"[INFO] Cloud clients not available locally, running in offline mode: {e}")

    # Stage 1: Ingest & Land Raw JSON
    stage1_start = datetime.now(UTC)
    raw_payloads = {}
    with httpx.Client(timeout=30.0) as http_client:
        for s in sites:
            payload = fetch_site_weather(http_client, s, start_date, end_date)
            raw_payloads[s["site_id"]] = payload
            time.sleep(0.1)

    landed = land_raw_json(raw_payloads, end_date, bucket, storage_client)
    stage1_end = datetime.now(UTC)

    emit_run_event(
        run_id=run_id,
        pipeline="ingest_weather",
        stage="ingest_raw",
        started_at=stage1_start,
        ended_at=stage1_end,
        status="SUCCESS",
        rows_in=len(sites),
        rows_out=len(landed),
        project_id=project,
        client=bq_client,
    )

    # Loop through each partition date in range
    cur_date = start_date
    total_bronze_rows = 0
    total_silver_rows = 0

    while cur_date <= end_date:
        # Stage 2: Parse to Bronze
        stage2_start = datetime.now(UTC)
        bronze_rows = parse_raw_to_bronze(raw_payloads, cur_date)
        total_bronze_rows += len(bronze_rows)

        if bq_client:
            table_bronze = f"{project}.raw.weather_readings"
            # Delete partition first for idempotency
            dt_iso = cur_date.isoformat()
            delete_sql = f"DELETE FROM `{table_bronze}` WHERE partition_date = '{dt_iso}'"
            try:
                bq_client.query(delete_sql).result()
                bq_client.insert_rows_json(table_bronze, bronze_rows)
            except Exception as e:
                print(f"[WARN] Failed BigQuery bronze insert: {e}")

        stage2_end = datetime.now(UTC)
        emit_run_event(
            run_id=run_id,
            pipeline="ingest_weather",
            stage="parse_bronze",
            started_at=stage2_start,
            ended_at=stage2_end,
            status="SUCCESS",
            rows_in=len(raw_payloads),
            rows_out=len(bronze_rows),
            project_id=project,
            client=bq_client,
        )

        emit_data_profile(
            run_id=run_id,
            table_name="raw.weather_readings",
            partition_date=cur_date,
            records=bronze_rows,
            project_id=project,
            client=bq_client,
        )

        # Stage 3: Aggregate to Silver
        stage3_start = datetime.now(UTC)
        silver_rows = aggregate_bronze_to_silver(bronze_rows, cur_date)
        total_silver_rows += len(silver_rows)

        if bq_client:
            table_silver = f"{project}.core.daily_site_weather"
            dt_iso = cur_date.isoformat()
            delete_sql = f"DELETE FROM `{table_silver}` WHERE partition_date = '{dt_iso}'"
            try:
                bq_client.query(delete_sql).result()
                bq_client.insert_rows_json(table_silver, silver_rows)
            except Exception as e:
                print(f"[WARN] Failed BigQuery silver insert: {e}")

        stage3_end = datetime.now(UTC)
        emit_run_event(
            run_id=run_id,
            pipeline="ingest_weather",
            stage="aggregate_silver",
            started_at=stage3_start,
            ended_at=stage3_end,
            status="SUCCESS",
            rows_in=len(bronze_rows),
            rows_out=len(silver_rows),
            project_id=project,
            client=bq_client,
        )

        emit_data_profile(
            run_id=run_id,
            table_name="core.daily_site_weather",
            partition_date=cur_date,
            records=silver_rows,
            project_id=project,
            client=bq_client,
        )

        cur_date += timedelta(days=1)

    print(
        f"[PIPELINE A SUCCESS] Finished run {run_id}. "
        f"Bronze: {total_bronze_rows}, Silver: {total_silver_rows}"
    )

    return {
        "run_id": run_id,
        "bronze_count": total_bronze_rows,
        "silver_count": total_silver_rows,
        "sites_ingested": len(sites),
        "duration_sec": (datetime.now(UTC) - start_time).total_seconds(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline A: Ingest Weather")
    parser.add_argument("--date", type=str, help="Target partition date (YYYY-MM-DD)")
    parser.add_argument(
        "--backfill-days", type=int, help="Number of trailing days to backfill (e.g. 60)"
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    run_ingest_pipeline(target_date=target, backfill_days=args.backfill_days)
