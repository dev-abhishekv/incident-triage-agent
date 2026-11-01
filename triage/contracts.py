"""Core Pydantic boundary contracts for the incident triage agent.

These models serve as the single source of truth across:
1. Agent structured outputs
2. Deterministic rule baseline results
3. BigQuery ops.triage_results ingestion
4. Evaluation harness metrics and scoring
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RootCauseId(StrEnum):
    """The 20 mutually agreed failure modes plus UNKNOWN."""

    SCHEMA_ADDITIVE = "schema_additive"
    SCHEMA_RENAME = "schema_rename"
    SCHEMA_TYPE_CHANGE = "schema_type_change"
    SCHEMA_COLUMN_DROPPED = "schema_column_dropped"
    NULL_EXPLOSION = "null_explosion"
    DUPLICATE_KEYS = "duplicate_keys"
    UNIT_CHANGE = "unit_change"
    TIMEZONE_SHIFT = "timezone_shift"
    SENTINEL_VALUES = "sentinel_values"
    MALFORMED_JSON = "malformed_json"
    UPSTREAM_EMPTY = "upstream_empty"
    STALE_PARTITION = "stale_partition"
    UPSTREAM_FAILED_DOWNSTREAM_RAN = "upstream_failed_downstream_ran"
    DOUBLE_LOAD = "double_load"
    CREDENTIAL_EXPIRED = "credential_expired"
    IAM_PERMISSION_DENIED = "iam_permission_denied"
    SOURCE_RATE_LIMITED = "source_rate_limited"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    NETWORK_TIMEOUT = "network_timeout"
    CONFIG_DRIFT = "config_drift"
    UNKNOWN = "unknown"


class Incident(BaseModel):
    """Input incident payload representing a pipeline failure or anomaly."""

    model_config = {"extra": "forbid"}

    incident_id: str = Field(description="Unique identifier for the incident")
    pipeline: str = Field(description="Name of the pipeline (e.g. ingest_weather, build_gold)")
    stage: str = Field(description="Pipeline stage where failure surfaced")
    run_id: str = Field(description="Execution run ID of the failure")
    occurred_at: datetime = Field(description="Timestamp when failure or alert was observed")
    partition_date: date = Field(description="Data partition date under investigation")
    alert_text: str = Field(description="Raw text from alert notification or error check")

    # Ground truth: populated ONLY in synthetic eval scenarios.
    # NEVER pass this field to an agent prompt or baseline strategy.
    injected_root_cause: RootCauseId | None = Field(
        default=None,
        description="Ground truth root cause for scoring. Stripped before strategy diagnosis.",
    )

    def to_agent_payload(self) -> "Incident":
        """Return a clean copy of the Incident with ground truth strictly stripped."""
        payload_data = self.model_dump()
        payload_data["injected_root_cause"] = None
        return Incident.model_validate(payload_data)


class Evidence(BaseModel):
    """Verifiable finding produced by a read-only diagnostic tool."""

    model_config = {"extra": "forbid"}

    tool: str = Field(description="Name of the diagnostic tool called")
    finding: str = Field(description="Structured summary of the tool output finding")


class TriageResult(BaseModel):
    """The unified output schema required from all triage strategies."""

    model_config = {"extra": "forbid"}

    root_cause_id: RootCauseId = Field(
        description="Diagnosed root cause ID constrained to the agreed enum"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score bounded between 0.0 (uncertain) and 1.0 (certain)",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="List of concrete findings discovered during investigation",
    )
    blast_radius: list[str] = Field(
        default_factory=list,
        description="Downstream tables or consumers affected by this incident",
    )
    proposed_remediation: str = Field(
        description="Actionable remediation steps proposed to fix the issue"
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Whether executing the remediation requires human approval",
    )
