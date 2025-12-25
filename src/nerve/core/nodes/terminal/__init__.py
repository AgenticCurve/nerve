"""Terminal nodes - PTY and WezTerm based terminal interactions.

Terminal nodes implement the Node protocol for terminal-based interactions.

Key characteristics:
- PTYNode: Owns process via pseudo-terminal, continuous buffer
- WezTermNode: Attaches to WezTerm panes, always-fresh buffer query
- ClaudeWezTermNode: WezTerm optimized for Claude CLI

All terminal nodes:
- Are persistent (maintain state across executions)
- Support execute() and execute_stream() methods
- Have history logging capability
"""

from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode
from nerve.core.nodes.terminal.pty_node import PTYNode
from nerve.core.nodes.terminal.wezterm_node import WezTermNode

__all__ = [
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",
]
