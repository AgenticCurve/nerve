"""Orchestration patterns for multi-agent workflows.

Reusable patterns for common multi-agent scenarios:
- DevCoach: Developer-Coach collaboration loop
- Debate: Two agents debating a topic
- Consensus: Multiple agents reaching agreement

These patterns use core primitives (Session, DAG) and can be
customized via configuration.
"""

from nerve.core.patterns.debate import DebateConfig, DebateLoop
from nerve.core.patterns.dev_coach import DevCoachConfig, DevCoachLoop

__all__ = [
    "DevCoachConfig",
    "DevCoachLoop",
    "DebateConfig",
    "DebateLoop",
]
