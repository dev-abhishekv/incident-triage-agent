"""Idempotent BigQuery table provisioner.

Reads DDL definitions from ops/schemas/ and applies them to:
- ops.*
- raw.*
- core.*
"""

import os
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery


def setup_all_tables(project_id: str | None = None) -> list[str]:
    project = project_id or os.getenv("GCP_PROJECT", "incident-triage-agent-513309")
    schemas_dir = Path(__file__).parent / "schemas"
    applied = []

    client = bigquery.Client(project=project)

    for sql_file in sorted(schemas_dir.glob("*.sql")):
        ddl_text = sql_file.read_text(encoding="utf-8")
        # Ensure project qualification if needed, or execute within default project
        print(f"Applying {sql_file.name} to project '{project}'...")
        query_job = client.query(ddl_text)
        query_job.result()  # Wait for completion
        applied.append(sql_file.name)
        print(f"Successfully applied {sql_file.name}")

    return applied


if __name__ == "__main__":
    try:
        results = setup_all_tables()
        print(f"Applied {len(results)} schema definitions successfully.")
    except GoogleAPIError as e:
        print(f"BigQuery API Error: {e}")
    except Exception as ex:
        print(f"Error during schema setup: {ex}")
