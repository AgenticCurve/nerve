"""NodeFactory - Factory for creating nodes by backend type.

This module implements the factory pattern for node creation, implementing
the Open/Closed Principle:
- Open for extension (add new backends)
- Closed for modification (via registry pattern)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    from nerve.core.nodes import Node
    from nerve.core.nodes.llm.base import SingleShotLLMNode
    from nerve.core.session import Session

# HTTP backend type
HttpBackend = Literal["aiohttp", "openai"]


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
    VALID_BACKENDS: ClassVar[tuple[str, ...]] = (
        "pty",
        "wezterm",
        "claude-wezterm",
        "bash",
        "openrouter",
        "glm",
        "llm-chat",
    )

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
        # BashNode options
        bash_timeout: float | None = None,
        # LLM node options (OpenRouterNode, GLMNode)
        api_key: str | None = None,
        llm_model: str | None = None,
        llm_base_url: str | None = None,
        llm_timeout: float | None = None,
        llm_debug_dir: str | None = None,
        # GLMNode-specific options
        llm_thinking: bool = False,
        # LLMChatNode-specific options
        llm_provider: str | None = None,  # "openrouter" or "glm"
        llm_system: str | None = None,  # System prompt
        # Tool calling options (LLMChatNode only)
        tool_node_ids: list[str] | None = None,  # Node IDs to use as tools
        tool_choice: str
        | dict[str, object]
        | None = None,  # "auto", "none", "required", or force dict
        parallel_tool_calls: bool | None = None,  # Control parallel tool execution
        # HTTP backend for LLM nodes
        http_backend: HttpBackend = "aiohttp",
    ) -> Node:
        """Create a node of the specified backend type.

        Args:
            backend: Node backend type ("pty", "wezterm", "claude-wezterm", "bash", "openrouter", "glm", "llm-chat").
            session: Session to register node with.
            node_id: Node identifier.
            command: Command to run (e.g., "claude" or ["claude", "--flag"]).
            cwd: Working directory.
            pane_id: For attaching to existing WezTerm pane.
            history: Enable history logging (default: True).
            response_timeout: Max wait for terminal response in seconds.
            ready_timeout: Max wait for terminal ready state in seconds.
            proxy_url: Proxy URL for claude-wezterm backend.
            bash_timeout: Timeout for bash command execution (BashNode only).
            api_key: API key for LLM provider (LLM nodes).
            llm_model: Model name (LLM nodes).
            llm_base_url: Base URL for LLM API (LLM nodes, uses provider default if None).
            llm_timeout: Request timeout (LLM nodes).
            llm_debug_dir: Directory for request/response logs (LLM nodes).
            llm_thinking: Enable thinking/reasoning mode (GLMNode only).
            llm_provider: LLM provider for chat node ("openrouter" or "glm").
            llm_system: System prompt for chat node.
            tool_node_ids: List of node IDs to use as tools (LLMChatNode only).
            tool_choice: Tool choice mode - "auto", "none", "required", or force dict.
            parallel_tool_calls: Control parallel tool execution (True/False/None).
            http_backend: HTTP backend for LLM nodes ("aiohttp" or "openai").

        Returns:
            The created node.

        Raises:
            ValueError: If backend is unknown or invalid parameters.
        """
        # Deferred imports to avoid circular dependencies and for testability
        from nerve.core.nodes.bash import BashNode
        from nerve.core.nodes.llm import GLMNode, LLMChatNode, OpenRouterNode
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )

        node: (
            PTYNode
            | WezTermNode
            | ClaudeWezTermNode
            | BashNode
            | OpenRouterNode
            | GLMNode
            | LLMChatNode
        )

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
        elif backend == "bash":
            # BashNode is ephemeral - no lifecycle management
            # Note: BashNode doesn't support history parameter
            node = BashNode(
                id=str(node_id),
                session=session,
                cwd=cwd,
                timeout=bash_timeout or 120.0,
            )
        elif backend == "openrouter":
            # OpenRouterNode is ephemeral - no lifecycle management
            if not api_key:
                raise ValueError("api_key is required for openrouter backend")
            if not llm_model:
                raise ValueError("llm_model is required for openrouter backend")

            node = OpenRouterNode(
                id=str(node_id),
                session=session,
                api_key=api_key,
                model=llm_model,
                base_url=llm_base_url,  # None uses provider default
                timeout=llm_timeout or 120.0,
                debug_dir=llm_debug_dir,
                http_backend=http_backend,
            )
        elif backend == "glm":
            # GLMNode is ephemeral - no lifecycle management
            if not api_key:
                raise ValueError("api_key is required for glm backend")
            if not llm_model:
                raise ValueError("llm_model is required for glm backend")

            node = GLMNode(
                id=str(node_id),
                session=session,
                api_key=api_key,
                model=llm_model,
                base_url=llm_base_url,  # None uses provider default
                timeout=llm_timeout or 120.0,
                debug_dir=llm_debug_dir,
                thinking=llm_thinking,
                http_backend=http_backend,
            )
        elif backend == "llm-chat":
            # LLMChatNode is persistent - wraps a single-shot LLM node
            if not api_key:
                raise ValueError("api_key is required for llm-chat backend")
            if not llm_model:
                raise ValueError("llm_model is required for llm-chat backend")
            if not llm_provider:
                raise ValueError(
                    "llm_provider is required for llm-chat backend (openrouter or glm)"
                )

            # Create underlying LLM node based on provider
            # Use a unique ID for the inner node
            inner_id = f"{node_id}-llm"
            inner_llm: SingleShotLLMNode
            if llm_provider == "openrouter":
                inner_llm = OpenRouterNode(
                    id=inner_id,
                    session=session,
                    api_key=api_key,
                    model=llm_model,
                    base_url=llm_base_url,
                    timeout=llm_timeout or 120.0,
                    debug_dir=llm_debug_dir,
                    http_backend=http_backend,
                )
            elif llm_provider == "glm":
                inner_llm = GLMNode(
                    id=inner_id,
                    session=session,
                    api_key=api_key,
                    model=llm_model,
                    base_url=llm_base_url,
                    timeout=llm_timeout or 120.0,
                    debug_dir=llm_debug_dir,
                    thinking=llm_thinking,
                    http_backend=http_backend,
                )
            else:
                raise ValueError(
                    f"Unknown llm_provider: '{llm_provider}'. Use 'openrouter' or 'glm'"
                )

            # Set up tools if tool_node_ids provided
            tools = None
            tool_executor = None
            if tool_node_ids:
                from nerve.core.nodes import is_tool_capable, tools_from_nodes

                # Look up tool nodes from session
                tool_nodes = []
                for tid in tool_node_ids:
                    if tid not in session.nodes:
                        raise ValueError(f"Tool node '{tid}' not found in session")
                    tool_node = session.nodes[tid]
                    if not is_tool_capable(tool_node):
                        raise ValueError(
                            f"Node '{tid}' is not tool-capable. "
                            "It must implement tool_description(), tool_parameters(), "
                            "tool_input(), and tool_result() methods."
                        )
                    tool_nodes.append(tool_node)

                # Create tool definitions and executor
                tools, tool_executor = tools_from_nodes(tool_nodes)

            # Create chat node wrapping the LLM
            node = LLMChatNode(
                id=str(node_id),
                session=session,
                llm=inner_llm,
                system=llm_system,
                tools=tools or [],
                tool_executor=tool_executor,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
            )
        else:
            raise ValueError(f"Unknown backend: '{backend}'. Valid backends: {self.VALID_BACKENDS}")

        return node
