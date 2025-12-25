"""ServerHandler - Server control and cleanup coordination.

Commands: STOP, PING

State:
- shutdown_requested: bool (exposed via property)
- Coordinates cleanup across all handlers

Design Note: Uses graph_handler.cancel_all_graphs() instead of accessing
_running_graphs directly to avoid coupling to GraphHandler internals.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.server.protocols import Event, EventType

if TYPE_CHECKING:
    from nerve.server.handlers.graph_handler import GraphHandler
    from nerve.server.protocols import EventSink
    from nerve.server.proxy_manager import ProxyManager
    from nerve.server.session_registry import SessionRegistry


@dataclass
class ServerHandler:
    """Server control and cleanup coordination.

    Commands: STOP, PING

    State:
    - _shutdown_requested: bool (exposed via property)
    - Coordinates cleanup across all handlers
    """

    event_sink: EventSink
    proxy_manager: ProxyManager
    session_registry: SessionRegistry
    graph_handler: GraphHandler

    # Owned state
    _shutdown_requested: bool = field(default=False)

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._shutdown_requested

    async def stop(self, params: dict[str, Any]) -> dict[str, Any]:
        """Stop the server.

        Returns immediately after initiating stop. Cleanup happens async.

        Returns:
            {"stopped": True}
        """
        # Set shutdown flag first so serve loop will exit
        self._shutdown_requested = True

        # Emit stop event
        await self.event_sink.emit(Event(type=EventType.SERVER_STOPPED))

        # Schedule cleanup in background (don't await)
        asyncio.create_task(self._cleanup_on_stop())

        return {"stopped": True}

    async def _cleanup_on_stop(self) -> None:
        """Background cleanup during stop.

        1. Cancel all running graphs (via GraphHandler)
        2. Stop all sessions (which stops all nodes)
        3. Stop all proxies
        """
        # Cancel running graphs via GraphHandler (proper encapsulation)
        await self.graph_handler.cancel_all_graphs()

        # Stop all sessions (get_all_sessions returns Session objects)
        for session in self.session_registry.get_all_sessions():
            try:
                await session.stop()
            except Exception:
                pass  # Best effort

        # Stop all proxies
        try:
            await self.proxy_manager.stop_all()
        except Exception:
            pass  # Best effort

    async def ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ping server to check if alive.

        Returns:
            {"pong": True, "nodes": int, "graphs": int, "sessions": int}
        """
        sessions = self.session_registry.get_all_sessions()
        total_nodes = sum(len(s.nodes) for s in sessions)

        return {
            "pong": True,
            "nodes": total_nodes,
            "graphs": self.graph_handler.running_graph_count,
            "sessions": len(sessions),
        }
