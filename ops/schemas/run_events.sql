-- ops.run_events: Captures telemetry for every pipeline stage execution
CREATE TABLE IF NOT EXISTS `ops.run_events` (
  run_id STRING NOT NULL,
  pipeline STRING NOT NULL,
  stage STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP NOT NULL,
  status STRING NOT NULL, -- 'SUCCESS' | 'FAILED'
  rows_in INT64,
  rows_out INT64,
  bytes_processed INT64,
  exit_code INT64,
  error_type STRING,
  error_message STRING,
  log_uri STRING,
  git_sha STRING,
  config_json JSON
)
PARTITION BY DATE(started_at);

