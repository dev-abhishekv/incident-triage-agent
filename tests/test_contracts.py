"""Automated tests for Feature: Pydantic contracts and TriageStrategy.

Implements all 6 automated Gherkin scenarios defined in Week 1 Spec:
- TriageResult rejects an unknown root cause
- TriageResult rejects out-of-range confidence
- TriageResult rejects undeclared fields
- UNKNOWN is a valid answer
- TriageResult round-trips through JSON
- The strategy protocol is satisfiable
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from triage.contracts import Evidence, Incident, RootCauseId, TriageResult
from triage.strategy import TriageStrategy


def test_triage_result_rejects_unknown_root_cause() -> None:
    """Scenario: TriageResult rejects an unknown root cause [AUTOMATED]"""
    with pytest.raises(ValidationError) as exc_info:
        TriageResult(
            root_cause_id="definitely_not_real",  # type: ignore[arg-type]
            confidence=0.8,
            evidence=[Evidence(tool="search_logs", finding="found error")],
            blast_radius=["core.site_daily_summary"],
            proposed_remediation="Inspect logs",
        )
    assert "Input should be" in str(exc_info.value) or "root_cause_id" in str(exc_info.value)


def test_triage_result_rejects_out_of_range_confidence() -> None:
    """Scenario: TriageResult rejects out-of-range confidence [AUTOMATED]"""
    # Over upper bound
    with pytest.raises(ValidationError) as exc_info_high:
        TriageResult(
            root_cause_id=RootCauseId.SCHEMA_ADDITIVE,
            confidence=1.4,
            evidence=[],
            proposed_remediation="Update schema",
        )
    assert "confidence" in str(exc_info_high.value)

    # Under lower bound
    with pytest.raises(ValidationError) as exc_info_low:
        TriageResult(
            root_cause_id=RootCauseId.SCHEMA_ADDITIVE,
            confidence=-0.1,
            evidence=[],
            proposed_remediation="Update schema",
        )
    assert "confidence" in str(exc_info_low.value)


def test_triage_result_rejects_undeclared_fields() -> None:
    """Scenario: TriageResult rejects undeclared fields [AUTOMATED]"""
    with pytest.raises(ValidationError) as exc_info:
        TriageResult(
            root_cause_id=RootCauseId.UPSTREAM_EMPTY,
            confidence=0.9,
            evidence=[],
            proposed_remediation="Rerun pipeline A",
            notes="this is an undeclared extra field",  # type: ignore[call-arg]
        )
    assert "extra_forbidden" in str(exc_info.value) or "Extra inputs are not permitted" in str(
        exc_info.value
    )


def test_unknown_is_a_valid_answer() -> None:
    """Scenario: UNKNOWN is a valid answer [AUTOMATED]"""
    result = TriageResult(
        root_cause_id=RootCauseId.UNKNOWN,
        confidence=0.0,
        evidence=[],
        proposed_remediation="Escalate to human on-call engineer",
        requires_human_approval=True,
    )
    assert result.root_cause_id == RootCauseId.UNKNOWN
    assert result.confidence == 0.0
    assert result.evidence == []
    assert result.requires_human_approval is True


def test_triage_result_round_trips_through_json() -> None:
    """Scenario: TriageResult round-trips through JSON [AUTOMATED]"""
    original = TriageResult(
        root_cause_id=RootCauseId.SCHEMA_RENAME,
        confidence=0.95,
        evidence=[
            Evidence(tool="get_schema_changes", finding="column location_id renamed to site_id"),
            Evidence(tool="search_logs", finding="KeyError: 'location_id' in parse task"),
        ],
        blast_radius=["raw.weather_readings", "core.daily_site_weather"],
        proposed_remediation="Update bronze parser column alias to site_id",
        requires_human_approval=True,
    )

    json_str = original.model_dump_json()
    parsed = TriageResult.model_validate_json(json_str)

    assert parsed == original
    assert parsed.root_cause_id == RootCauseId.SCHEMA_RENAME
    assert len(parsed.evidence) == 2


def test_strategy_protocol_is_satisfiable() -> None:
    """Scenario: The strategy protocol is satisfiable [AUTOMATED]"""

    class StubBaselineStrategy:
        name: str = "baseline"
        routing_policy: str = "n/a"

        def diagnose(self, incident: Incident) -> TriageResult:
            return TriageResult(
                root_cause_id=RootCauseId.UNKNOWN,
                confidence=0.5,
                evidence=[],
                proposed_remediation="Default triage",
            )

    stub = StubBaselineStrategy()
    assert isinstance(stub, TriageStrategy)

    test_incident = Incident(
        incident_id="inc-101",
        pipeline="ingest_weather",
        stage="parse",
        run_id="run-999",
        occurred_at=datetime.now(UTC),
        partition_date=date(2026, 10, 24),
        alert_text="Task failed with exit code 1",
    )

    result = stub.diagnose(test_incident)
    assert isinstance(result, TriageResult)
    assert result.root_cause_id == RootCauseId.UNKNOWN


def test_incident_strips_ground_truth_for_agent() -> None:
    """Verify that Incident ground truth cannot leak to agent payloads."""
    ground_truth_incident = Incident(
        incident_id="inc-202",
        pipeline="build_gold",
        stage="gold_join",
        run_id="run-888",
        occurred_at=datetime.now(UTC),
        partition_date=date(2026, 10, 24),
        alert_text="Duplicate keys detected in summary",
        injected_root_cause=RootCauseId.DUPLICATE_KEYS,
    )

    agent_payload = ground_truth_incident.to_agent_payload()
    assert agent_payload.injected_root_cause is None
    assert ground_truth_incident.injected_root_cause == RootCauseId.DUPLICATE_KEYS
