"""NodeFactory - Factory for creating nodes by backend type.

This module implements the factory pattern for node creation, implementing
the Open/Closed Principle:
- Open for extension (add new backends)
- Closed for modification (via registry pattern)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from nerve.core.nodes import Node
    from nerve.core.session import Session


class NodeFactory:
    """Factory for creating nodes by backend type.

    Encapsulates backend dispatch logic, making it easy to:
    - Add new backends without modifying handlers
    - Test node creation in isolation
    - Maintain consistent error messages

    Example:
        >>> factory = NodeFactory()
        >>> node = await factory.create(
        ...     backend="pty",
        ...     session=session,
        ...     node_id="my-node",
        ...     command="bash",
        ... )
    """

    # Valid backends (immutable)
    VALID_BACKENDS: ClassVar[tuple[str, ...]] = ("pty", "wezterm", "claude-wezterm")

    async def create(
        self,
        backend: str,
        session: Session,
        node_id: str,
        command: str | list[str] | None = None,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,
        response_timeout: float = 1800.0,
        ready_timeout: float = 60.0,
        proxy_url: str | None = None,
    ) -> Node:
        """Create a node of the specified backend type.

        Args:
            backend: Node backend type ("pty", "wezterm", "claude-wezterm").
            session: Session to register node with.
            node_id: Node identifier.
            command: Command to run (e.g., "claude" or ["claude", "--flag"]).
            cwd: Working directory.
            pane_id: For attaching to existing WezTerm pane.
            history: Enable history logging (default: True).
            response_timeout: Max wait for terminal response in seconds.
            ready_timeout: Max wait for terminal ready state in seconds.
            proxy_url: Proxy URL for claude-wezterm backend.

        Returns:
            The created node.

        Raises:
            ValueError: If backend is unknown or invalid parameters.
        """
        # Deferred imports to avoid circular dependencies and for testability
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )

        node: PTYNode | WezTermNode | ClaudeWezTermNode

        if backend == "pty":
            node = await PTYNode.create(
                id=str(node_id),
                session=session,
                command=command,
                cwd=cwd,
                history=history,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
            )
        elif backend == "wezterm":
            if pane_id:
                # Attach to existing pane
                node = await WezTermNode.attach(
                    id=str(node_id),
                    session=session,
                    pane_id=pane_id,
                    history=history,
                    response_timeout=response_timeout,
                    ready_timeout=ready_timeout,
                )
            else:
                # Create new pane
                node = await WezTermNode.create(
                    id=str(node_id),
                    session=session,
                    command=command,
                    cwd=cwd,
                    history=history,
                    response_timeout=response_timeout,
                    ready_timeout=ready_timeout,
                )
        elif backend == "claude-wezterm":
            if not command:
                raise ValueError("command is required for claude-wezterm backend")
            # ClaudeWezTermNode.create expects str, not list[str]
            if isinstance(command, list):
                import shlex

                command_str = " ".join(shlex.quote(arg) for arg in command)
            else:
                command_str = command
            node = await ClaudeWezTermNode.create(
                id=str(node_id),
                session=session,
                command=command_str,
                cwd=cwd,
                history=history,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
                proxy_url=proxy_url,
            )
        else:
            raise ValueError(f"Unknown backend: '{backend}'. Valid backends: {self.VALID_BACKENDS}")

        return node
