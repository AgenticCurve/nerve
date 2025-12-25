"""PTY and terminal backend management.

This module provides backends for managing terminal processes.
The default is PTYBackend (direct PTY), but WezTermBackend is
available for integration with WezTerm.

Backends:
    PTYBackend: Direct pseudo-terminal using pty.fork() (default)
    WezTermBackend: Uses WezTerm CLI to manage panes

Classes:
    Backend: Abstract base class for backends
    BackendConfig: Configuration for backends

Legacy (deprecated, use backends instead):
    PTYProcess: Alias for PTYBackend
    PTYConfig: Alias for BackendConfig

Example:
    >>> from nerve.core.pty import PTYBackend, BackendConfig
    >>>
    >>> # Use PTY backend (default)
    >>> backend = PTYBackend(["claude"], BackendConfig(cwd="/project"))
    >>> await backend.start()
    >>> await backend.write("hello\\n")
    >>>
    >>> # Use WezTerm backend
    >>> from nerve.core.pty import WezTermBackend
    >>> backend = WezTermBackend(["claude"])
    >>> await backend.start()  # Opens in WezTerm pane
"""

from nerve.core.pty.backend import Backend, BackendConfig
from nerve.core.pty.manager import PTYManager

# Legacy aliases for backwards compatibility
from nerve.core.pty.process import PTYConfig, PTYProcess
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.pty.wezterm_backend import (
    WezTermBackend,
    ensure_wezterm_running,
    is_wezterm_available,
    is_wezterm_installed,
)

__all__ = [
    # Backend API
    "Backend",
    "BackendConfig",
    "PTYBackend",
    "WezTermBackend",
    "is_wezterm_available",
    "is_wezterm_installed",
    "ensure_wezterm_running",
    # Manager
    "PTYManager",
    # Legacy (deprecated)
    "PTYProcess",
    "PTYConfig",
]
