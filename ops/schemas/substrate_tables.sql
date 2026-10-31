-- Substrate production tables in raw and core datasets

-- raw.weather_readings: Bronze layer holding hourly observations
CREATE TABLE IF NOT EXISTS `raw.weather_readings` (
  site_id STRING NOT NULL,
  partition_date DATE NOT NULL,
  reading_time TIMESTAMP NOT NULL,
  temperature_2m FLOAT64,
  relative_humidity_2m FLOAT64,
  precipitation FLOAT64,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY partition_date;

-- core.dim_site: Static site reference table
CREATE TABLE IF NOT EXISTS `core.dim_site` (
  site_id STRING NOT NULL,
  site_name STRING NOT NULL,
  sector STRING NOT NULL,
  state STRING NOT NULL,
  latitude FLOAT64 NOT NULL,
  longitude FLOAT64 NOT NULL
);

-- core.daily_site_weather: Silver aggregated daily statistics per site
CREATE TABLE IF NOT EXISTS `core.daily_site_weather` (
  site_id STRING NOT NULL,
  partition_date DATE NOT NULL,
  avg_temp FLOAT64,
  min_temp FLOAT64,
  max_temp FLOAT64,
  total_precipitation FLOAT64,
  avg_humidity FLOAT64,
  reading_count INT64,
  aggregated_at TIMESTAMP NOT NULL
)
PARTITION BY partition_date;

-- core.site_daily_summary: Gold final summary joined with dim_site
CREATE TABLE IF NOT EXISTS `core.site_daily_summary` (
  site_id STRING NOT NULL,
  site_name STRING NOT NULL,
  sector STRING NOT NULL,
  state STRING NOT NULL,
  partition_date DATE NOT NULL,
  avg_temp FLOAT64,
  min_temp FLOAT64,
  max_temp FLOAT64,
  total_precipitation FLOAT64,
  avg_humidity FLOAT64,
  summary_generated_at TIMESTAMP NOT NULL
)
PARTITION BY partition_date;

