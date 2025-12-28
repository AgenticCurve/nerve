"""NodeInteractionHandler - Handles node I/O: commands, execution, streaming, buffers.

Domain: Node communication (I/O operations)
Distinction: Manages HOW to interact with nodes, not their existence
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nerve.core.nodes import ExecutionContext
from nerve.core.nodes.history import HistoryReader
from nerve.core.parsers import get_parser
from nerve.core.types import ParserType
from nerve.server.protocols import Event, EventType

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nerve.core.types import ParsedResponse
    from nerve.server.protocols import EventSink
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class NodeInteractionHandler:
    """Handles node I/O: commands, execution, streaming, buffers.

    Domain: Node communication (I/O operations)
    Distinction: Manages HOW to interact with nodes, not their existence

    State: None (uses session registry for access)
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry
    server_name: str

    async def _auto_delete_if_ephemeral(self, node: object, session: object) -> bool:
        """Auto-delete ephemeral nodes after execution.

        Args:
            node: The node that was executed.
            session: The session containing the node.

        Returns:
            True if the node was deleted, False otherwise.
        """
        # Check if node is ephemeral (persistent == False)
        if getattr(node, "persistent", True):
            return False

        node_id = getattr(node, "id", None)
        if not node_id:
            return False

        # Delete from session
        deleted: bool = await session.delete_node(node_id)  # type: ignore[attr-defined]
        if deleted:
            # Emit NODE_DELETED event
            await self.event_sink.emit(
                Event(
                    type=EventType.NODE_DELETED,
                    node_id=node_id,
                )
            )
        return deleted

    async def run_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run a command in a node (fire and forget).

        This starts a program that takes over the terminal (like claude, python, etc.)
        without waiting for a response. Use EXECUTE_INPUT to interact with it after.

        Args:
            params: Must contain "node_id" and "command".

        Returns:
            {"executed": True}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        command = self.validation.require_param(params, "command")

        node = self.validation.get_node(session, node_id, require_terminal=True)
        await node.run(command)  # type: ignore[attr-defined]

        return {"executed": True}

    async def execute_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute input on a node and wait for response.

        Parameters:
            node_id: Node identifier (required)
            text: Input text to send (required)
            parser: Parser type ("claude", "gemini", "none")
            stream: Stream output as events (default: False)
            timeout: Override node's response_timeout for this execution (optional)

        Returns:
            {"response": ParsedResponse dict}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        text = self.validation.require_param(params, "text")
        parser_str = params.get("parser")
        stream = params.get("stream", False)
        timeout = params.get("timeout")

        node = self.validation.get_node(session, node_id)

        # Convert parser string to ParserType, or None to use node's default
        parser_type = ParserType(parser_str) if parser_str else None

        start_time = time.monotonic()
        logger.debug(
            "execute_start: node_id=%s, input_len=%d, parser=%s, stream=%s, timeout=%s",
            node_id,
            len(text),
            parser_str,
            stream,
            timeout,
        )

        await self.event_sink.emit(
            Event(
                type=EventType.NODE_BUSY,
                node_id=node_id,
            )
        )

        # Create execution context with optional timeout
        context = ExecutionContext(
            session=session,
            input=text,
            timeout=timeout,
        )

        if stream:
            # Stream output chunks as events
            stream_context = ExecutionContext(
                session=session,
                input=text,
                parser=parser_type,
                timeout=timeout,
            )
            async for chunk in node.execute_stream(stream_context):  # type: ignore[attr-defined]
                await self.event_sink.emit(
                    Event(
                        type=EventType.OUTPUT_CHUNK,
                        data={"chunk": chunk},
                        node_id=node_id,
                    )
                )

            # Parse final response
            actual_parser = parser_type or ParserType.NONE
            parser = get_parser(actual_parser)
            response = parser.parse(node.buffer)  # type: ignore[attr-defined]
        else:
            # Wait for complete response using ExecutionContext (immutable pattern)
            if parser_type is not None:
                context = context.with_parser(parser_type)
            response = await node.execute(context)

        # Handle response based on type:
        # - Ephemeral nodes (BashNode, OpenRouterNode) return dict
        # - Terminal nodes return ParsedResponse
        response_data: dict[str, Any]
        if isinstance(response, dict):
            # Ephemeral node - response is already a dict
            response_data = response

            # Emit OUTPUT_PARSED event with dict data
            await self.event_sink.emit(
                Event(
                    type=EventType.OUTPUT_PARSED,
                    data=response_data,
                    node_id=node_id,
                )
            )
        else:
            # Terminal node - response is ParsedResponse
            response_data = self._serialize_response(response)

            # Emit OUTPUT_PARSED event
            await self.event_sink.emit(
                Event(
                    type=EventType.OUTPUT_PARSED,
                    data={
                        "raw": response.raw,
                        "sections": [
                            {"type": s.type, "content": s.content, "metadata": s.metadata}
                            for s in response.sections
                        ],
                        "tokens": response.tokens,
                    },
                    node_id=node_id,
                )
            )

        await self.event_sink.emit(
            Event(
                type=EventType.NODE_READY,
                node_id=node_id,
            )
        )

        # Auto-delete ephemeral nodes after execution
        await self._auto_delete_if_ephemeral(node, session)

        duration = time.monotonic() - start_time
        logger.debug(
            "execute_complete: node_id=%s, duration=%.2fs, response_type=%s",
            node_id,
            duration,
            type(response).__name__,
        )

        return {"response": response_data}

    async def send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt signal to node.

        Args:
            params: Must contain "node_id".

        Returns:
            {"interrupted": True}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)

        await node.interrupt()

        return {"interrupted": True}

    async def write_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write raw data to a node (no waiting).

        Args:
            params: Must contain "node_id" and "data".

        Returns:
            {"written": int}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        data = self.validation.require_param(params, "data")

        node = self.validation.get_node(session, node_id, require_terminal=True)
        await node.write(data)  # type: ignore[attr-defined]

        return {"written": len(data)}

    async def get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get terminal buffer contents.

        Args:
            params: Must contain "node_id". Optional "lines" for tail.

        Returns:
            {"buffer": str}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        lines = params.get("lines")

        node = self.validation.get_node(session, node_id, require_terminal=True)

        if lines:
            buffer = node.read_tail(lines)  # type: ignore[attr-defined]
        else:
            buffer = await node.read()  # type: ignore[attr-defined]

        return {"buffer": buffer}

    async def get_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node history.

        Reads the JSONL history file for a node.

        Parameters:
            node_id: The node ID (required)
            server_name: Server name (optional, defaults to engine's server name)
            last: Limit to last N entries (optional)
            op: Filter by operation type (optional)
            inputs_only: Filter to input operations only (optional)

        Returns:
            Dict with node_id, server_name, entries, and total count.
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")

        server_name = params.get("server_name", self.server_name)
        last = params.get("last")
        op = params.get("op")
        inputs_only = params.get("inputs_only", False)

        try:
            reader = HistoryReader.create(
                node_id=node_id,
                server_name=server_name,
                session_name=session.name,
                base_dir=session.history_base_dir,
            )

            # Apply filters
            if inputs_only:
                entries = reader.get_inputs_only()
            elif op:
                entries = reader.get_by_op(op)
            else:
                entries = reader.get_all()

            # Apply limit if specified
            if last is not None and last < len(entries):
                entries = entries[-last:]

            return {
                "node_id": node_id,
                "server_name": server_name,
                "entries": entries,
                "total": len(entries),
            }

        except FileNotFoundError:
            # Fail soft - return empty results with note
            return {
                "node_id": node_id,
                "server_name": server_name,
                "entries": [],
                "total": 0,
                "note": "No history found for this node",
            }

    def _serialize_response(self, response: ParsedResponse) -> dict[str, Any]:
        """Serialize ParsedResponse to dict.

        Args:
            response: ParsedResponse to serialize.

        Returns:
            Serialized dict.
        """
        return {
            "raw": response.raw,
            "sections": [
                {"type": s.type, "content": s.content, "metadata": s.metadata}
                for s in response.sections
            ],
            "tokens": response.tokens,
            "is_complete": response.is_complete,
            "is_ready": response.is_ready,
        }
