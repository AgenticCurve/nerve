"""NodeLifecycleHandler - Handles node lifecycle: creation, deletion, listing, monitoring.

Domain: Node existence (CRUD operations)
Distinction: Manages WHETHER nodes exist, not HOW to interact with them
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nerve.core.nodes import NodeState
from nerve.server.protocols import Event, EventType
from nerve.server.proxy_manager import ProviderConfig

if TYPE_CHECKING:
    from nerve.server.factories.node_factory import NodeFactory
    from nerve.server.protocols import EventSink
    from nerve.server.proxy_manager import ProxyManager
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers

logger = logging.getLogger(__name__)


@dataclass
class NodeLifecycleHandler:
    """Handles node lifecycle: creation, deletion, listing, monitoring.

    Domain: Node existence (CRUD operations)
    Distinction: Manages WHETHER nodes exist, not HOW to interact with them

    State: Monitoring tasks (prevents GC, enables cancellation)
    """

    event_sink: EventSink
    node_factory: NodeFactory
    proxy_manager: ProxyManager
    validation: ValidationHelpers
    session_registry: SessionRegistry
    server_name: str

    # Monitoring tasks by node_id (prevents GC, enables cancellation)
    _monitoring_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)

    async def create_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new node.

        Requires node_id (name) in params. Names must be unique.
        Uses direct node class instantiation with session parameter.

        Parameters:
            node_id: Node identifier (required)
            command: Command to run (e.g., "claude" or ["claude", "--flag"])
            cwd: Working directory
            backend: Node backend ("pty", "wezterm", "claude-wezterm")
            pane_id: For attaching to existing WezTerm pane
            history: Enable history logging (default: True)
            response_timeout: Max wait for terminal response in seconds (default: 1800.0)
            ready_timeout: Max wait for terminal ready state in seconds (default: 60.0)
            provider: Provider configuration for proxy (optional, claude-wezterm only)
                      Dict with keys: api_format, base_url, api_key, model (optional), debug_dir (optional)

        Returns:
            {"node_id": str, "proxy_url": str|None}
        """
        session = self.session_registry.get_session(params.get("session_id"))

        node_id = self.validation.require_param(params, "node_id")
        command = params.get("command")
        cwd = params.get("cwd")
        backend = params.get("backend", "pty")
        pane_id = params.get("pane_id")
        history = params.get("history", True)
        response_timeout = params.get("response_timeout", 1800.0)
        ready_timeout = params.get("ready_timeout", 60.0)
        provider_dict = params.get("provider")

        # Ephemeral node options
        bash_timeout = params.get("bash_timeout")
        api_key = params.get("api_key")
        llm_model = params.get("llm_model")
        llm_base_url = params.get("llm_base_url")
        llm_timeout = params.get("llm_timeout")
        llm_debug_dir = params.get("llm_debug_dir")
        llm_thinking = params.get("llm_thinking", False)
        # LLMChatNode options
        llm_provider = params.get("llm_provider")
        llm_system = params.get("llm_system")
        # Tool calling options (LLMChatNode only)
        tool_node_ids = params.get("tool_node_ids")
        tool_choice = params.get("tool_choice")
        parallel_tool_calls = params.get("parallel_tool_calls")
        # HTTP backend for LLM nodes
        http_backend = cast(
            Literal["aiohttp", "openai"],
            params.get("http_backend", "aiohttp"),
        )

        # Handle provider configuration and start proxy if needed
        proxy_url: str | None = None
        if provider_dict is not None:
            proxy_url = await self._setup_proxy(
                session_name=session.name,
                node_id=str(node_id),
                provider_dict=provider_dict,
                backend=backend,
            )

        logger.debug(
            "node_creating: node_id=%s, backend=%s, command=%s, cwd=%s",
            node_id,
            backend,
            command,
            cwd,
        )

        # Create node via factory
        try:
            node = await self.node_factory.create(
                backend=backend,
                session=session,
                node_id=str(node_id),
                command=command,
                cwd=cwd,
                pane_id=pane_id,
                history=history,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
                proxy_url=proxy_url,
                # Ephemeral node options
                bash_timeout=bash_timeout,
                api_key=api_key,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_timeout=llm_timeout,
                llm_debug_dir=llm_debug_dir,
                llm_thinking=llm_thinking,
                # LLMChatNode options
                llm_provider=llm_provider,
                llm_system=llm_system,
                # Tool calling options
                tool_node_ids=tool_node_ids,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                # HTTP backend
                http_backend=http_backend,
            )
        except Exception as e:
            # Cleanup proxy on failure
            logger.debug(
                "node_create_failed: node_id=%s, backend=%s, error=%s",
                node_id,
                backend,
                str(e)[:200],
            )
            if proxy_url is not None:
                await self.proxy_manager.stop_proxy(str(node_id))
            raise

        logger.debug(
            "node_created: node_id=%s, backend=%s, persistent=%s, proxy_url=%s",
            node.id,
            backend,
            node.persistent,
            proxy_url,
        )

        # Emit event
        await self.event_sink.emit(
            Event(
                type=EventType.NODE_CREATED,
                node_id=node.id,
                data={
                    "command": command,
                    "cwd": cwd,
                    "backend": backend,
                    "pane_id": getattr(node, "pane_id", None),
                    "proxy_url": proxy_url,
                    "persistent": node.persistent,
                },
            )
        )

        # Only start monitoring for persistent nodes with state (PTYNode, WezTermNode, etc.)
        # Ephemeral nodes (BashNode, OpenRouterNode) and stateless persistent nodes
        # (LLMChatNode) don't need lifecycle monitoring
        if node.persistent and hasattr(node, "state"):
            # Start monitoring (store task to prevent GC and enable cancellation)
            task = asyncio.create_task(self._monitor_node(node))
            self._monitoring_tasks[node.id] = task

            # Add done callback to handle exceptions and cleanup
            def on_monitor_done(t: asyncio.Task[None]) -> None:
                # Remove from tracking
                self._monitoring_tasks.pop(node.id, None)
                # Log any unhandled exceptions
                try:
                    t.result()  # Raises if task failed
                except asyncio.CancelledError:
                    pass  # Expected when node is deleted
                except Exception as e:
                    logger.error(f"Monitoring task for node {node.id} failed: {e}", exc_info=True)

            task.add_done_callback(on_monitor_done)

        return {"node_id": node.id, "proxy_url": proxy_url}

    async def _setup_proxy(
        self,
        session_name: str,
        node_id: str,
        provider_dict: dict[str, Any],
        backend: str,
    ) -> str:
        """Setup proxy and return URL.

        Args:
            session_name: Name of the session.
            node_id: Node identifier.
            provider_dict: Provider configuration dict.
            backend: Node backend type.

        Returns:
            Proxy URL.

        Raises:
            ValueError: If provider config is invalid.
        """
        if backend != "claude-wezterm":
            raise ValueError("provider config is only supported for claude-wezterm backend")

        # Validate required keys are present
        is_transparent = provider_dict.get("transparent", False)
        if is_transparent:
            # Transparent mode: only api_format and base_url required
            required_keys = ["api_format", "base_url"]
        else:
            # Normal mode: api_key is also required
            required_keys = ["api_format", "base_url", "api_key"]
        missing = [k for k in required_keys if k not in provider_dict]
        if missing:
            raise ValueError(
                f"Provider config missing required keys: {', '.join(missing)}. "
                f"Required: {', '.join(required_keys)}"
            )

        # Convert dict to ProviderConfig
        provider_config = ProviderConfig(
            api_format=provider_dict["api_format"],
            base_url=provider_dict["base_url"],
            api_key=provider_dict.get("api_key") or "",  # Empty for transparent mode
            model=provider_dict.get("model"),
            debug_dir=provider_dict.get("debug_dir"),
            transparent=is_transparent,
            log_headers=provider_dict.get("log_headers", False),
        )

        # Determine debug directory for request/response logs
        debug_dir = provider_config.debug_dir
        log_dir: str | None = None
        if debug_dir is None:
            base_log_path = (
                Path.cwd()
                / ".nerve"
                / "logs"
                / "proxy"
                / self.server_name
                / session_name
                / str(node_id)
            )
            debug_dir = str(base_log_path / "request-response")
            log_dir = str(base_log_path / "stdout-stderr")

        # Start proxy before creating node
        instance = await self.proxy_manager.start_proxy(
            node_id=str(node_id),
            config=provider_config,
            debug_dir=debug_dir,
            log_dir=log_dir,
        )
        return f"http://127.0.0.1:{instance.port}"

    async def delete_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a node from session.

        Also stops any associated proxy and monitoring task for the node.

        Args:
            params: Must contain "node_id".

        Returns:
            {"deleted": True}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")

        # Validate node exists
        _node = self.validation.get_node(session, node_id)

        # Cancel monitoring task if it exists
        task = self._monitoring_tasks.get(str(node_id))
        if task and not task.done():
            task.cancel()
            # Note: cleanup happens in done_callback

        # Stop proxy if one exists for this node
        await self.proxy_manager.stop_proxy(str(node_id))

        # Delete node from session
        deleted = await session.delete_node(str(node_id))
        if not deleted:
            logger.debug("node_delete_failed: node_id=%s, reason=not_found", node_id)
            raise ValueError(f"Node not found: {node_id}")

        logger.debug("node_deleted: node_id=%s, session=%s", node_id, session.name)

        await self.event_sink.emit(
            Event(
                type=EventType.NODE_DELETED,
                node_id=str(node_id),
            )
        )

        return {"deleted": True}

    async def list_nodes(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all nodes in session.

        Args:
            params: May contain "session_id".

        Returns:
            {"nodes": [str], "nodes_info": [dict]}
        """
        session = self.session_registry.get_session(params.get("session_id"))

        node_ids = session.list_nodes()
        nodes_info = self._gather_nodes_info(session, node_ids)

        return {
            "nodes": node_ids,
            "nodes_info": nodes_info,
        }

    async def get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node information.

        Args:
            params: Must contain "node_id".

        Returns:
            Node info dict.
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)

        info = node.to_info()  # type: ignore[attr-defined]
        result = {
            "node_id": node.id,
            "type": info.node_type,
            "state": info.state.name,
        }

        # Add optional metadata
        if "backend" in info.metadata:
            result["backend"] = info.metadata["backend"]
        if "pane_id" in info.metadata:
            result["pane_id"] = info.metadata["pane_id"]

        return result

    def _gather_nodes_info(self, session: Any, node_ids: list[str]) -> list[dict[str, Any]]:
        """Gather info dicts for nodes.

        Args:
            session: Session to query.
            node_ids: List of node IDs.

        Returns:
            List of node info dicts.
        """
        nodes_info = []
        for nid in node_ids:
            node = session.get_node(nid)
            if node and hasattr(node, "to_info"):
                info = node.to_info()
                nodes_info.append(
                    {
                        "id": nid,
                        "type": info.node_type,
                        "state": info.state.name,
                        **info.metadata,
                    }
                )
        return nodes_info

    async def _monitor_node(self, node: Any) -> None:
        """Monitor node for state changes.

        This runs in the background and emits events when
        the node state changes.

        Args:
            node: Node to monitor.
        """
        last_state = node.state

        while node.state != NodeState.STOPPED:
            await asyncio.sleep(0.5)

            if node.state != last_state:
                if node.state == NodeState.READY:
                    await self.event_sink.emit(
                        Event(
                            type=EventType.NODE_READY,
                            node_id=node.id,
                        )
                    )
                elif node.state == NodeState.BUSY:
                    await self.event_sink.emit(
                        Event(
                            type=EventType.NODE_BUSY,
                            node_id=node.id,
                        )
                    )

                last_state = node.state
