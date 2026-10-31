"""Daily Substrate Orchestration Entrypoint.

Coordinates the daily execution of:
1. Pipeline A: Ingest Weather (Open-Meteo -> GCS -> Bronze -> Silver)
2. Upstream Guard Check: Pipeline B must NOT execute if Pipeline A fails.
3. Pipeline B: Build Gold (Silver -> Dim Join -> Data Quality Checks)
"""

import argparse
import sys
from datetime import date, timedelta

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from substrate.pipelines.build_gold import run_gold_pipeline
from substrate.pipelines.ingest_weather import run_ingest_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Substrate Pipeline Runner")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Target partition date (default: yesterday)",
    )
    args = parser.parse_args()

    target_date = args.date or (date.today() - timedelta(days=1))
    print("==================================================")
    print(f"[ORCHESTRATOR] Starting daily pipeline run for {target_date.isoformat()}")
    print("==================================================")

    # Stage 1: Pipeline A
    print("\n>>> Running Pipeline A (Ingest Weather)...")
    try:
        res_a = run_ingest_pipeline(target_date=target_date)
        print(f">>> Pipeline A completed successfully: {res_a}")
    except Exception as e:
        print(f"[FATAL] Pipeline A failed: {e}", file=sys.stderr)
        print("[GUARD] Aborting Pipeline B because Pipeline A failed.", file=sys.stderr)
        return 1

    # Stage 2: Upstream guard verification
    # If Pipeline A did not generate silver data or errored, do not proceed
    if not res_a.get("silver_count", 0):
        print(
            "[WARN] Pipeline A produced 0 silver rows. Guard condition triggered.",
            file=sys.stderr,
        )
        return 1

    # Stage 3: Pipeline B
    print("\n>>> Running Pipeline B (Build Gold & Data Quality Checks)...")
    try:
        res_b = run_gold_pipeline(target_date=target_date)
        print(f">>> Pipeline B completed successfully: {res_b}")
    except Exception as e:
        print(f"[FATAL] Pipeline B failed: {e}", file=sys.stderr)
        return 2

    print("\n==================================================")
    print(f"[ORCHESTRATOR] Daily pipeline run SUCCESS for {target_date.isoformat()}")
    print("==================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
