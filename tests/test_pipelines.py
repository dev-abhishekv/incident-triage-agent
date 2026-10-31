"""Tests for Substrate Pipeline A logic: bronze parsing and silver aggregation."""

from datetime import date

from substrate.pipelines.ingest_weather import (
    aggregate_bronze_to_silver,
    parse_raw_to_bronze,
)


def test_parse_raw_to_bronze_and_aggregate_silver() -> None:
    target_d = date(2026, 10, 24)
    dt_str = target_d.isoformat()

    # Synthetic raw API payloads for 20 sites with 24 hourly readings each
    mock_raw_payloads = {}
    for i in range(1, 21):
        site_id = f"PLANT_{i:02d}"
        times = [f"{dt_str}T{hour:02d}:00" for hour in range(24)]
        temps = [25.0 + (hour * 0.2) for hour in range(24)]
        humidities = [60.0 - (hour * 0.5) for hour in range(24)]
        precips = [0.0] * 24

        mock_raw_payloads[site_id] = {
            "latitude": 20.0 + i,
            "longitude": 75.0 + i,
            "hourly": {
                "time": times,
                "temperature_2m": temps,
                "relative_humidity_2m": humidities,
                "precipitation": precips,
            },
        }

    # Test Bronze Parsing
    bronze_rows = parse_raw_to_bronze(mock_raw_payloads, target_d)
    # 20 sites * 24 hours = 480 rows
    assert len(bronze_rows) == 480
    assert all(r["partition_date"] == dt_str for r in bronze_rows)
    assert all(r["temperature_2m"] is not None for r in bronze_rows)

    # Test Silver Aggregation
    silver_rows = aggregate_bronze_to_silver(bronze_rows, target_d)
    # Exactly 20 rows (one per site)
    assert len(silver_rows) == 20
    assert all(r["partition_date"] == dt_str for r in silver_rows)
    assert all(r["reading_count"] == 24 for r in silver_rows)
    assert all(r["avg_temp"] is not None for r in silver_rows)
