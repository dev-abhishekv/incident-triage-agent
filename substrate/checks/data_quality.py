"""Data quality assertion engine for Pipeline B gold layer.

Implements 4 core data quality assertions required by Week 1 Spec:
1. Row count check vs trailing 7-day mean
2. Null rate check across all columns
3. Duplicate key check on (site_id, partition_date)
4. Upstream freshness check on core.daily_site_weather
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


class DataQualityError(Exception):
    """Raised when one or more data quality checks fail."""

    def __init__(self, message: str, failed_checks: list["CheckResult"]):
        super().__init__(message)
        self.failed_checks = failed_checks


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def check_row_count(
    records: list[dict[str, Any]],
    trailing_7d_mean: float = 20.0,
    tolerance: float = 0.15,
) -> CheckResult:
    """Check that row count is within tolerance of trailing 7-day average."""
    count = len(records)
    min_expected = trailing_7d_mean * (1.0 - tolerance)
    max_expected = trailing_7d_mean * (1.0 + tolerance)

    passed = min_expected <= count <= max_expected
    msg = (
        f"Row count {count} is within expected range [{min_expected:.1f}, {max_expected:.1f}]"
        if passed
        else f"Row count {count} deviates from trailing 7d mean ({trailing_7d_mean:.1f})"
    )
    return CheckResult(
        check_name="row_count_vs_7d_mean",
        passed=passed,
        message=msg,
        details={"actual": count, "trailing_7d_mean": trailing_7d_mean},
    )


def check_null_rates(
    records: list[dict[str, Any]],
    required_columns: list[str] | None = None,
    max_null_rate: float = 0.0,
) -> CheckResult:
    """Check that specified or all columns do not exceed maximum allowable null rate."""
    if not records:
        return CheckResult(
            check_name="null_rate_check",
            passed=False,
            message="No records provided to evaluate null rates",
        )

    cols = required_columns or list(records[0].keys())
    null_rates: dict[str, float] = {}
    failing_cols = []

    total = len(records)
    for col in cols:
        null_count = sum(1 for r in records if r.get(col) is None)
        rate = round(null_count / total, 4)
        null_rates[col] = rate
        if rate > max_null_rate:
            failing_cols.append(col)

    passed = len(failing_cols) == 0
    msg = (
        "All columns within allowable null rate thresholds"
        if passed
        else f"Columns exceeded null rate threshold: {failing_cols}"
    )
    return CheckResult(
        check_name="null_rate_check",
        passed=passed,
        message=msg,
        details={"null_rates": null_rates, "failing_columns": failing_cols},
    )


def check_duplicate_keys(
    records: list[dict[str, Any]],
    key_columns: tuple[str, ...] = ("site_id", "partition_date"),
) -> CheckResult:
    """Check that composite key (site_id, partition_date) has zero duplicates."""
    seen = set()
    duplicates = []

    for r in records:
        key = tuple(r.get(k) for k in key_columns)
        if key in seen:
            duplicates.append(key)
        else:
            seen.add(key)

    passed = len(duplicates) == 0
    msg = (
        f"Zero duplicate keys found for {key_columns}"
        if passed
        else f"Found {len(duplicates)} duplicate keys: {duplicates[:5]}"
    )
    return CheckResult(
        check_name="duplicate_key_check",
        passed=passed,
        message=msg,
        details={"duplicate_count": len(duplicates), "key_columns": list(key_columns)},
    )


def check_upstream_freshness(
    upstream_partition_date: date,
    target_partition_date: date,
    max_lag_days: int = 0,
) -> CheckResult:
    """Check that upstream dependency partition matches the target date."""
    diff_days = (target_partition_date - upstream_partition_date).days
    passed = diff_days <= max_lag_days
    msg = (
        f"Upstream partition ({upstream_partition_date}) is fresh"
        if passed
        else f"Upstream partition ({upstream_partition_date}) is stale for {target_partition_date}"
    )
    return CheckResult(
        check_name="upstream_freshness_check",
        passed=passed,
        message=msg,
        details={"upstream_date": str(upstream_partition_date), "lag_days": diff_days},
    )


def evaluate_gold_checks(
    records: list[dict[str, Any]],
    target_date: date,
    upstream_date: date | None = None,
    trailing_7d_mean: float = 20.0,
) -> list[CheckResult]:
    """Execute all 4 data quality assertions and return list of CheckResults."""
    checks = [
        check_row_count(records, trailing_7d_mean=trailing_7d_mean),
        check_null_rates(
            records,
            required_columns=[
                "site_id",
                "site_name",
                "sector",
                "state",
                "partition_date",
                "avg_temp",
            ],
            max_null_rate=0.0,
        ),
        check_duplicate_keys(records, key_columns=("site_id", "partition_date")),
    ]

    if upstream_date:
        checks.append(check_upstream_freshness(upstream_date, target_date))

    return checks
