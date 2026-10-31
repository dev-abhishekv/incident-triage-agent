-- ops.data_profiles: Profiling metrics per table partition per run
CREATE TABLE IF NOT EXISTS `ops.data_profiles` (
  run_id STRING NOT NULL,
  table_name STRING NOT NULL,
  partition_date DATE NOT NULL,
  row_count INT64 NOT NULL,
  null_rate_json JSON NOT NULL,
  distinct_count_json JSON NOT NULL,
  min_max_json JSON NOT NULL,
  duplicate_key_count INT64 NOT NULL,
  profiled_at TIMESTAMP NOT NULL
)
PARTITION BY partition_date;

