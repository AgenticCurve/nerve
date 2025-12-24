"""REPL state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class REPLState:
    """State for the REPL."""

    namespace: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    nodes: dict[str, Any] = field(default_factory=dict)
