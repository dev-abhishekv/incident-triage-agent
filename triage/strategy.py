"""The TriageStrategy protocol.

Every diagnosis method (rule-based baseline, LangGraph agent, ADK agent)
implements this interface so the evaluation harness remains decoupled
from any underlying agent framework.
"""

from typing import Protocol, runtime_checkable

from triage.contracts import Incident, TriageResult


@runtime_checkable
class TriageStrategy(Protocol):
    """Unified interface for all incident diagnosis strategies."""

    name: str  # Goes into ops.triage_results.strategy (e.g. 'baseline', 'langgraph', 'adk')
    routing_policy: str  # 'n/a' for baseline; 'all_cheap' | 'all_premium' | 'tiered'

    def diagnose(self, incident: Incident) -> TriageResult:
        """Diagnose an incident and return a strictly validated TriageResult."""
        ...
