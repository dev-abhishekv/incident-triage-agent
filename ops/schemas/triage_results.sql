-- ops.triage_results: Evaluated diagnosis from baseline and agent strategies
CREATE TABLE IF NOT EXISTS `ops.triage_results` (
  incident_id STRING NOT NULL,
  strategy STRING NOT NULL,         -- 'baseline' | 'langgraph' | 'adk'
  routing_policy STRING NOT NULL,   -- 'n/a' | 'all_cheap' | 'all_premium' | 'tiered'
  predicted_root_cause_id STRING NOT NULL,
  confidence FLOAT64 NOT NULL,
  evidence_json JSON NOT NULL,
  proposed_remediation STRING NOT NULL,
  latency_ms INT64 NOT NULL,
  input_tokens INT64,
  output_tokens INT64,
  cost_usd FLOAT64,
  run_seq INT64 NOT NULL            -- 1, 2, or 3 (for repeatability evaluation)
);

