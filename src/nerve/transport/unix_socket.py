"""Unix domain socket transport.

Provides client-server communication over Unix domain sockets.
Efficient for local IPC with persistent daemon processes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event


@dataclass
class UnixSocketServer:
    """Unix socket server transport.

    Listens on a Unix domain socket and handles client connections.
    Broadcasts events to all connected clients.

    Example:
        >>> transport = UnixSocketServer("/tmp/nerve.sock")
        >>> engine = NerveEngine(event_sink=transport)
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
                "channel_id": event.channel_id,
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
        )

        # Serve until shutdown requested
        async with self._server:
            while self._running and not engine.shutdown_requested:
                await asyncio.sleep(0.5)

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

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        self._clients.append(writer)

        try:
            while self._running:
                line = await reader.readline()
                if not line:
                    break

                try:
                    message = json.loads(line.decode())
                    response = await self._handle_message(message)
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
                except json.JSONDecodeError:
                    error = {"type": "error", "error": "Invalid JSON"}
                    writer.write((json.dumps(error) + "\n").encode())
                    await writer.drain()

        except Exception:
            pass
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()

    async def _handle_message(self, message: dict) -> dict:
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
        ...     type=CommandType.CREATE_CHANNEL,
        ...     params={"command": "claude"},
        ... ))
        >>>
        >>> async for event in client.events():
        ...     print(event.type)
    """

    socket_path: str
    _reader: asyncio.StreamReader | None = None
    _writer: asyncio.StreamWriter | None = None
    _event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _connected: bool = False
    _reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect to the server."""
        self._reader, self._writer = await asyncio.open_unix_connection(self.socket_path)
        self._connected = True

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

    async def send_command(self, command: Command) -> CommandResult:
        """Send a command and wait for result."""
        from nerve.server.protocols import CommandResult

        if not self._writer or not self._connected:
            raise RuntimeError("Not connected")

        message = {
            "type": "command",
            "command_type": command.type.name,
            "params": command.params,
            "request_id": command.request_id,
        }

        self._writer.write((json.dumps(message) + "\n").encode())
        await self._writer.drain()

        # Wait for result (from queue, put there by reader)
        while True:
            response = await self._event_queue.get()
            if isinstance(response, dict) and response.get("type") == "result":
                return CommandResult(
                    success=response["success"],
                    data=response.get("data"),
                    error=response.get("error"),
                    request_id=response.get("request_id"),
                )

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to events."""
        from nerve.server.protocols import Event, EventType

        while self._connected:
            item = await self._event_queue.get()
            if isinstance(item, dict) and item.get("type") == "event":
                yield Event(
                    type=EventType[item["event_type"]],
                    channel_id=item.get("channel_id"),
                    data=item.get("data", {}),
                    timestamp=item.get("timestamp", 0),
                )

    async def _read_loop(self) -> None:
        """Background loop to read from socket."""
        if not self._reader:
            return

        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    break

                try:
                    message = json.loads(line.decode())
                    await self._event_queue.put(message)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            self._connected = False
