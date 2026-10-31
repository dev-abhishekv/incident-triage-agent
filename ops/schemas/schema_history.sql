-- ops.schema_history: One row per column per observed schema version
CREATE TABLE IF NOT EXISTS `ops.schema_history` (
  observed_at TIMESTAMP NOT NULL,
  table_name STRING NOT NULL,
  column_name STRING NOT NULL,
  data_type STRING NOT NULL,
  is_nullable BOOL NOT NULL,
  schema_version INT64 NOT NULL
);

