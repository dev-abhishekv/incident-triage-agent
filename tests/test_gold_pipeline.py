"""Automated tests for Pipeline B (build_gold) and Data Quality Checks.

Satisfies all Gherkin scenarios from Week 1 Spec:
- Gold joins silver to the site dimension
- Data checks run and record results
- A failing data check marks the run failed
- Pipeline B does not run when Pipeline A failed
"""

from datetime import date

import pytest

from substrate.checks.data_quality import (
    DataQualityError,
    check_duplicate_keys,
    check_null_rates,
    check_row_count,
    evaluate_gold_checks,
)
from substrate.pipelines.build_gold import (
    join_silver_to_gold,
    load_dim_site,
    run_gold_pipeline,
)


def create_mock_silver_records(partition_d: date) -> list[dict]:
    """Create 20 mock silver daily site weather records."""
    dt_str = partition_d.isoformat()
    return [
        {
            "site_id": f"PLANT_{i:02d}",
            "partition_date": dt_str,
            "avg_temp": 28.5 + (i * 0.1),
            "min_temp": 20.0,
            "max_temp": 35.0,
            "total_precipitation": 0.0,
            "avg_humidity": 55.0,
            "reading_count": 24,
        }
        for i in range(1, 21)
    ]


def test_gold_joins_silver_to_site_dimension() -> None:
    """Scenario: Gold joins silver to the site dimension [AUTOMATED]"""
    target_d = date(2026, 10, 24)
    silver = create_mock_silver_records(target_d)
    dim_sites = load_dim_site()

    gold_records = join_silver_to_gold(silver, dim_sites, target_d)

    assert len(gold_records) == 20
    assert all(r["partition_date"] == target_d.isoformat() for r in gold_records)
    # Check that dim_site joined properly and site_name is not null
    assert all(r["site_name"] is not None for r in gold_records)
    assert all(r["sector"] is not None for r in gold_records)
    assert all(r["state"] is not None for r in gold_records)


def test_data_checks_evaluate_clean_records() -> None:
    """Scenario: Data checks run and record results on clean records [AUTOMATED]"""
    target_d = date(2026, 10, 24)
    silver = create_mock_silver_records(target_d)
    dim_sites = load_dim_site()
    gold_records = join_silver_to_gold(silver, dim_sites, target_d)

    results = evaluate_gold_checks(
        records=gold_records,
        target_date=target_d,
        upstream_date=target_d,
    )

    assert len(results) == 4
    assert all(r.passed for r in results)


def test_failing_duplicate_key_check_raises_data_quality_error() -> None:
    """Scenario: A failing data check marks the run failed [AUTOMATED]"""
    target_d = date(2026, 10, 24)
    silver = create_mock_silver_records(target_d)
    # Inject a duplicate key
    silver.append(silver[0].copy())

    dim_sites = load_dim_site()
    gold_records = join_silver_to_gold(silver, dim_sites, target_d)

    dup_result = check_duplicate_keys(gold_records)
    assert not dup_result.passed
    assert dup_result.details["duplicate_count"] == 1

    with pytest.raises(DataQualityError) as exc_info:
        run_gold_pipeline(target_date=target_d, silver_input=silver)

    assert "duplicate_key_check" in str(exc_info.value)


def test_null_rate_check_detects_nulls() -> None:
    """Verify that null rate check catches null fields in required columns."""
    records = [{"site_id": "PLANT_01", "site_name": None, "partition_date": "2026-10-24"}]
    res = check_null_rates(records, required_columns=["site_name"], max_null_rate=0.0)
    assert not res.passed
    assert "site_name" in res.details["failing_columns"]


def test_row_count_check_detects_deviation() -> None:
    """Verify row count deviation check vs trailing 7d mean."""
    records = [{"id": 1}] * 5  # Only 5 records instead of 20
    res = check_row_count(records, trailing_7d_mean=20.0, tolerance=0.15)
    assert not res.passed


def test_pipeline_b_does_not_run_when_pipeline_a_failed() -> None:
    """Scenario: Pipeline B does not run when Pipeline A failed [AUTOMATED]"""
    target_d = date(2026, 10, 24)
    result = run_gold_pipeline(target_date=target_d, upstream_failed=True)

    assert result["status"] == "FAILED"
    assert result["reason"] == "upstream_dependency_failed"
