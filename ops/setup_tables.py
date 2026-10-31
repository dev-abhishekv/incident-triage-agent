"""Idempotent BigQuery table provisioner.

Reads DDL definitions from ops/schemas/ and applies them to:
- ops.*
- raw.*
- core.*

Also seeds initial static data:
- ops.lineage (DAG edges)
- core.dim_site (20 verified plant metadata)
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery


def load_sites_config() -> list[dict[str, Any]]:
    """Load verified sites from config/sites.yaml."""
    config_path = Path("config/sites.yaml")
    if not config_path.exists():
        config_path = Path(__file__).parents[1] / "config" / "sites.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("sites", [])


def seed_lineage(client: bigquery.Client, project: str) -> None:
    """Populate ops.lineage with initial dependency edges."""
    table_id = f"{project}.ops.lineage"
    edges = [
        {
            "downstream_table": "core.site_daily_summary",
            "upstream_table": "core.daily_site_weather",
            "dependency_type": "DIRECT",
        },
        {
            "downstream_table": "core.site_daily_summary",
            "upstream_table": "core.dim_site",
            "dependency_type": "JOIN",
        },
        {
            "downstream_table": "core.daily_site_weather",
            "upstream_table": "raw.weather_readings",
            "dependency_type": "TRANSFORM",
        },
    ]

    # Delete existing to prevent duplicate rows on re-runs
    client.query(f"DELETE FROM `{table_id}` WHERE 1=1").result()
    errors = client.insert_rows_json(table_id, edges)
    if errors:
        print(f"[WARN] Errors seeding ops.lineage: {errors}")
    else:
        print(f"Successfully seeded {len(edges)} lineage edges into {table_id}")


def seed_dim_site(client: bigquery.Client, project: str) -> None:
    """Populate core.dim_site with the 20 plant coordinates."""
    table_id = f"{project}.core.dim_site"
    sites = load_sites_config()
    dim_rows = [
        {
            "site_id": s["site_id"],
            "site_name": s["name"],
            "sector": s.get("sector", "Industrial"),
            "state": s["state"],
            "latitude": float(s["latitude"]),
            "longitude": float(s["longitude"]),
        }
        for s in sites
    ]

    client.query(f"DELETE FROM `{table_id}` WHERE 1=1").result()
    errors = client.insert_rows_json(table_id, dim_rows)
    if errors:
        print(f"[WARN] Errors seeding core.dim_site: {errors}")
    else:
        print(f"Successfully seeded {len(dim_rows)} sites into {table_id}")


def seed_schema_history(client: bigquery.Client, project: str) -> None:
    """Populate ops.schema_history with the initial schema version (v1) for substrate tables."""
    table_id = f"{project}.ops.schema_history"
    tables = [
        "raw.weather_readings",
        "core.dim_site",
        "core.daily_site_weather",
        "core.site_daily_summary",
    ]
    now_iso = datetime.now(UTC).isoformat()
    rows = []
    for tbl in tables:
        t = client.get_table(f"{project}.{tbl}")
        for col in t.schema:
            rows.append(
                {
                    "observed_at": now_iso,
                    "table_name": tbl,
                    "column_name": col.name,
                    "data_type": col.field_type,
                    "is_nullable": (col.mode != "REQUIRED"),
                    "schema_version": 1,
                }
            )

    client.query(f"DELETE FROM `{table_id}` WHERE 1=1").result()
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        print(f"[WARN] Errors seeding ops.schema_history: {errors}")
    else:
        print(f"Successfully seeded {len(rows)} column schemas into {table_id}")


def setup_all_tables(project_id: str | None = None) -> list[str]:
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    schemas_dir = Path(__file__).parent / "schemas"
    applied = []

    client = bigquery.Client(project=project)

    # 1. Apply DDL schemas
    for sql_file in sorted(schemas_dir.glob("*.sql")):
        ddl_text = sql_file.read_text(encoding="utf-8")
        print(f"Applying {sql_file.name} to project '{project}'...")
        query_job = client.query(ddl_text)
        query_job.result()  # Wait for completion
        applied.append(sql_file.name)
        print(f"Successfully applied {sql_file.name}")

    # 2. Seed static reference data
    seed_lineage(client, project)
    seed_dim_site(client, project)
    seed_schema_history(client, project)

    return applied


if __name__ == "__main__":
    try:
        results = setup_all_tables()
        print(f"\nAll {len(results)} schema definitions applied & seeded successfully!")
    except GoogleAPIError as e:
        print(f"BigQuery API Error: {e}")
    except Exception as ex:
        print(f"Error during schema setup: {ex}")
