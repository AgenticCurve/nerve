"""Orchestration patterns for multi-agent workflows.

Reusable patterns for common multi-agent scenarios:
- DevCoach: Developer-Coach collaboration loop
- Debate: Two agents debating a topic
- Consensus: Multiple agents reaching agreement

These patterns use the Agent protocol - any object with a send() method
that returns a ParsedResponse (e.g., PTYNode, WezTermNode, RemoteNode).
"""

from nerve.core.patterns.debate import DebateConfig, DebateLoop
from nerve.core.patterns.dev_coach import Agent, DevCoachConfig, DevCoachLoop

__all__ = [
    "Agent",
    "DevCoachConfig",
    "DevCoachLoop",
    "DebateConfig",
    "DebateLoop",
]
