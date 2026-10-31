-- ops.agent_traces: Fine-grained OpenTelemetry GenAI step tracing
CREATE TABLE IF NOT EXISTS `ops.agent_traces` (
  incident_id STRING NOT NULL,
  strategy STRING NOT NULL,
  step_no INT64 NOT NULL,
  model STRING NOT NULL,
  tool_called STRING,
  input_tokens INT64,
  output_tokens INT64,
  latency_ms INT64 NOT NULL,
  cost_usd FLOAT64
);

