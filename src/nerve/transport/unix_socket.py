"""Unix domain socket transport.

Provides client-server communication over Unix domain sockets.
Efficient for local IPC with persistent daemon processes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event

logger = logging.getLogger(__name__)


@dataclass
class UnixSocketServer:
    """Unix socket server transport.

    Listens on a Unix domain socket and handles client connections.
    Broadcasts events to all connected clients.

    Example:
        >>> transport = UnixSocketServer("/tmp/nerve.sock")
        >>> engine = build_nerve_engine(event_sink=transport)
        >>> await transport.serve(engine)
    """

    socket_path: str
    _engine: NerveEngine | None = None
    _server: asyncio.Server | None = None
    _clients: list[asyncio.StreamWriter] = field(default_factory=list)
    _running: bool = False

    async def emit(self, event: Event) -> None:
        """Broadcast event to all connected clients."""
        if not self._clients:
            return

        # Serialize event
        data = json.dumps(
            {
                "type": "event",
                "event_type": event.type.name,
                "node_id": event.node_id,
                "data": event.data,
                "timestamp": event.timestamp,
            }
        )
        message = (data + "\n").encode()

        # Send to all clients
        dead_clients = []
        for writer in self._clients:
            try:
                writer.write(message)
                await writer.drain()
            except Exception:
                dead_clients.append(writer)

        # Remove dead clients
        for writer in dead_clients:
            self._clients.remove(writer)

    async def serve(self, engine: NerveEngine) -> None:
        """Start serving.

        Args:
            engine: The engine to serve.
        """
        self._engine = engine
        self._running = True

        # Remove existing socket
        socket_path = Path(self.socket_path)
        if socket_path.exists():
            socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
            limit=16 * 1024 * 1024,  # 16MB limit for large buffer responses
        )

        logger.info("Unix socket server started on %s", self.socket_path)

        # Serve until shutdown requested (poll every 0.1s for responsive shutdown)
        async with self._server:
            while self._running and not engine.shutdown_requested:
                await asyncio.sleep(0.1)

        # Cleanup
        await self.stop()

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Close all client connections
        for writer in self._clients:
            writer.close()
        self._clients.clear()

        # Remove socket file
        socket_path = Path(self.socket_path)
        if socket_path.exists():
            socket_path.unlink()

        logger.info("Unix socket server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        self._clients.append(writer)
        client_addr = writer.get_extra_info("peername") or "unknown"
        logger.debug("Client connected: %s", client_addr)

        # Lock to prevent concurrent writes from interleaving
        write_lock = asyncio.Lock()
        # Track active handler tasks for cleanup
        handler_tasks: set[asyncio.Task[None]] = set()

        async def handle_and_respond(message: dict[str, Any]) -> None:
            """Handle a message and write response (runs concurrently)."""
            try:
                response = await self._handle_message(message)
            except Exception as e:
                logger.error("Error handling message: %s", e, exc_info=True)
                response = {"type": "error", "error": str(e)}

            # Write response with lock to prevent interleaving
            async with write_lock:
                try:
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
                except Exception as e:
                    logger.warning("Error writing response to %s: %s", client_addr, e)

        try:
            while self._running:
                line = await reader.readline()
                if not line:
                    logger.debug("Client disconnected: %s", client_addr)
                    break

                try:
                    message = json.loads(line.decode())
                    # Spawn concurrent handler task instead of awaiting
                    task = asyncio.create_task(handle_and_respond(message))
                    handler_tasks.add(task)
                    # Clean up completed tasks
                    handler_tasks = {t for t in handler_tasks if not t.done()}
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON from client %s: %s", client_addr, e)
                    error = {"type": "error", "error": "Invalid JSON"}
                    async with write_lock:
                        writer.write((json.dumps(error) + "\n").encode())
                        await writer.drain()

        except asyncio.CancelledError:
            logger.debug("Client handler cancelled: %s", client_addr)
            raise
        except ConnectionResetError:
            logger.debug("Client connection reset: %s", client_addr)
        except Exception as e:
            logger.error("Error handling client %s: %s", client_addr, e, exc_info=True)
        finally:
            # Cancel all active handler tasks
            for task in handler_tasks:
                task.cancel()
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()

    async def _handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle an incoming message."""
        from nerve.server.protocols import Command, CommandType

        if message.get("type") != "command":
            return {"type": "error", "error": "Unknown message type"}

        if not self._engine:
            return {"type": "error", "error": "Engine not available"}

        command = Command(
            type=CommandType[message["command_type"]],
            params=message.get("params", {}),
            request_id=message.get("request_id"),
        )

        result = await self._engine.execute(command)

        return {
            "type": "result",
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "request_id": result.request_id,
        }


@dataclass
class UnixSocketClient:
    """Unix socket client transport.

    Connects to a Unix socket server to send commands and receive events.

    Example:
        >>> client = UnixSocketClient("/tmp/nerve.sock")
        >>> await client.connect()
        >>>
        >>> result = await client.send_command(Command(
        ...     type=CommandType.CREATE_NODE,
        ...     params={"command": "claude"},
        ... ))
        >>>
        >>> async for event in client.events():
        ...     print(event.type)
    """

    socket_path: str
    _reader: asyncio.StreamReader | None = None
    _writer: asyncio.StreamWriter | None = None
    _event_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    _pending_requests: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    _connected: bool = False
    _reader_task: asyncio.Task[Any] | None = None
    _last_error: Exception | None = field(default=None, repr=False)
    _error_count: int = field(default=0, repr=False)

    async def connect(self) -> None:
        """Connect to the server."""
        # Use larger limit for reading (16MB) to handle large buffer responses
        self._reader, self._writer = await asyncio.open_unix_connection(
            self.socket_path,
            limit=16 * 1024 * 1024,  # 16MB limit
        )
        self._connected = True
        logger.debug("Unix socket client connected to %s", self.socket_path)

        # Start background reader
        self._reader_task = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._writer:
            self._writer.close()

    async def send_command(self, command: Command, timeout: float = 300.0) -> CommandResult:
        """Send a command and wait for result.

        Uses request_id to match responses to requests, enabling concurrent
        command execution without mixing up responses.

        Auto-generates a UUID for request_id if not provided, ensuring each
        request has a unique identifier for proper correlation.

        Args:
            command: The command to send.
            timeout: Timeout in seconds (default 300s).

        Returns:
            Command result from the server.

        Raises:
            RuntimeError: If not connected.
            TimeoutError: If response not received within timeout.
        """

        if not self._writer or not self._connected:
            raise RuntimeError("Not connected")

        # Auto-generate request_id if not provided (Command is frozen/immutable)
        if command.request_id is None:
            command = replace(command, request_id=str(uuid.uuid4()))

        # Extract request_id (guaranteed to be str after the above check)
        request_id = command.request_id
        assert request_id is not None  # Type narrowing for mypy

        # Create a future for this specific request
        future: asyncio.Future[CommandResult] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            message = {
                "type": "command",
                "command_type": command.type.name,
                "params": command.params,
                "request_id": request_id,
            }

            self._writer.write((json.dumps(message) + "\n").encode())
            await self._writer.drain()

            # Wait for THIS request's response (matched by request_id in _read_loop)
            return await asyncio.wait_for(future, timeout=timeout)

        except TimeoutError:
            raise TimeoutError(f"Command timed out after {timeout}s") from None
        finally:
            # Clean up pending request
            self._pending_requests.pop(request_id, None)

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to events."""
        from nerve.server.protocols import Event, EventType

        while self._connected:
            item = await self._event_queue.get()
            if isinstance(item, dict) and item.get("type") == "event":
                yield Event(
                    type=EventType[item["event_type"]],
                    node_id=item.get("node_id"),
                    data=item.get("data", {}),
                    timestamp=item.get("timestamp", 0),
                )

    async def _read_loop(self) -> None:
        """Background loop to read from socket.

        Routes messages based on type:
        - "result" messages: Matched to pending requests by request_id
        - "event" messages: Put in event queue for events() iterator

        Errors are logged and tracked in _last_error and _error_count.
        """
        from nerve.server.protocols import CommandResult

        if not self._reader:
            return

        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    logger.debug("Socket closed by server (empty read)")
                    break

                try:
                    message = json.loads(line.decode())

                    # Route command results to their specific futures
                    if isinstance(message, dict) and message.get("type") == "result":
                        request_id = message.get("request_id")
                        if request_id and request_id in self._pending_requests:
                            future = self._pending_requests[request_id]
                            if not future.done():
                                result = CommandResult(
                                    success=message["success"],
                                    data=message.get("data"),
                                    error=message.get("error"),
                                    request_id=request_id,
                                )
                                future.set_result(result)
                        else:
                            # This can happen when a request was cancelled but the server
                            # still sent a response. Not an error, just debug-level info.
                            logger.debug(
                                "Received response for unknown request_id: %s",
                                request_id,
                            )
                    else:
                        # Events and other messages go to the event queue
                        await self._event_queue.put(message)

                except json.JSONDecodeError as e:
                    self._error_count += 1
                    self._last_error = e
                    logger.warning(
                        "Failed to parse JSON from server: %s (line: %s...)",
                        e,
                        line[:100] if len(line) > 100 else line,
                    )
        except asyncio.CancelledError:
            logger.debug("Read loop cancelled")
            raise
        except ConnectionResetError as e:
            self._last_error = e
            logger.debug("Connection reset by server")
        except Exception as e:
            self._error_count += 1
            self._last_error = e
            logger.error("Unexpected error in read loop: %s", e, exc_info=True)
        finally:
            self._connected = False

    @property
    def last_error(self) -> Exception | None:
        """Last error encountered in the read loop."""
        return self._last_error

    @property
    def error_count(self) -> int:
        """Number of errors encountered in the read loop."""
        return self._error_count
