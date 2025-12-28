"""SessionHandler - Manages session lifecycle.

Commands: CREATE_SESSION, DELETE_SESSION, LIST_SESSIONS, GET_SESSION

State: Manages SessionRegistry (add/remove sessions)
Note: There is no SWITCH_SESSION command in the current API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nerve.core.session import Session
from nerve.server.protocols import Event, EventType

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nerve.server.protocols import EventSink
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class SessionHandler:
    """Manages session lifecycle.

    Commands: CREATE_SESSION, DELETE_SESSION, LIST_SESSIONS, GET_SESSION

    State: Manages SessionRegistry (add/remove sessions)
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry
    server_name: str

    async def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create new session and register it.

        Parameters:
            name: Session name (required)
            description: Session description (optional)
            tags: Session tags (optional)

        Returns:
            {"session_id": str, "name": str}
        """
        name = self.validation.require_param(params, "name")
        description = params.get("description", "")
        tags = params.get("tags", [])

        # Check for duplicate (uses proper encapsulation)
        if self.session_registry.has_session(name):
            raise ValueError(f"Session with name '{name}' already exists")

        session = Session(
            name=name,
            description=description,
            tags=tags,
            server_name=self.server_name,
        )

        # Auto-create built-in identity node for debugging/testing
        from nerve.core.nodes.identity import IdentityNode

        IdentityNode(id="identity", session=session)

        self.session_registry.add_session(name, session)

        logger.debug(
            "session_created: name=%s, description=%s, tags=%s",
            name,
            description[:50] if description else "",
            tags,
        )

        await self.event_sink.emit(
            Event(
                type=EventType.SESSION_CREATED,
                data={"session_id": name, "name": name},
            )
        )

        return {"session_id": name, "name": name}

    async def delete_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a session.

        Parameters:
            session_id: Session ID to delete (required)

        Returns:
            {"deleted": True}
        """
        session_id = self.validation.require_param(params, "session_id")

        # Cannot delete default session
        default = self.session_registry.default_session
        if default is not None and session_id == default.name:
            raise ValueError("Cannot delete the default session")

        session = self.session_registry.remove_session(session_id)
        if session is None:
            logger.debug("session_delete_failed: session_id=%s, reason=not_found", session_id)
            raise ValueError(f"Session not found: {session_id}")

        node_count = len(session.nodes)
        await session.stop()

        logger.debug(
            "session_deleted: session_id=%s, nodes_stopped=%d",
            session_id,
            node_count,
        )

        await self.event_sink.emit(
            Event(
                type=EventType.SESSION_DELETED,
                data={"session_id": session_id},
            )
        )

        return {"deleted": True}

    async def list_sessions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all sessions.

        Returns:
            {"sessions": list, "default_session_id": str}
        """
        default = self.session_registry.default_session
        default_name = default.name if default else None

        sessions = []
        for session in self.session_registry.get_all_sessions():
            sessions.append(
                {
                    "id": session.name,
                    "name": session.name,
                    "description": session.description,
                    "tags": session.tags,
                    "node_count": len(session.nodes),
                    "graph_count": len(session.graphs),
                    "is_default": session.name == default_name,
                }
            )

        return {
            "sessions": sessions,
            "default_session_id": default_name,
        }

    async def get_session_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get session info including nodes and graphs.

        Parameters:
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Session info dict with nodes and graphs.
        """
        session = self.session_registry.get_session(params.get("session_id"))
        default = self.session_registry.default_session

        # Get detailed node info
        node_ids = session.list_nodes()
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

        return {
            "session_id": session.name,
            "name": session.name,
            "description": session.description,
            "tags": session.tags,
            "nodes": node_ids,
            "nodes_info": nodes_info,
            "graphs": session.list_graphs(),
            "is_default": default is not None and session.name == default.name,
        }
