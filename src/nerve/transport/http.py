"""HTTP transport - REST API + WebSocket for events.

Provides HTTP-based communication for web clients and remote access.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event


@dataclass
class HTTPServer:
    """HTTP server transport.

    Provides:
    - POST /api/command - Send commands (REST)
    - GET /api/events - Subscribe to events (WebSocket)

    Example:
        >>> transport = HTTPServer(host="0.0.0.0", port=8080)
        >>> engine = NerveEngine(event_sink=transport)
        >>> await transport.serve(engine)
    """

    host: str = "127.0.0.1"
    port: int = 8080
    _engine: NerveEngine | None = None
    _app: Any = None  # aiohttp.web.Application
    _runner: Any = None  # aiohttp.web.AppRunner
    _websockets: list = field(default_factory=list)

    async def emit(self, event: Event) -> None:
        """Broadcast event to all WebSocket clients."""
        if not self._websockets:
            return

        data = json.dumps(
            {
                "type": "event",
                "event_type": event.type.name,
                "channel_id": event.channel_id,
                "data": event.data,
                "timestamp": event.timestamp,
            }
        )

        dead_sockets = []
        for ws in self._websockets:
            try:
                await ws.send_str(data)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self._websockets.remove(ws)

    async def serve(self, engine: NerveEngine) -> None:
        """Start the HTTP server."""
        try:
            from aiohttp import web
        except ImportError as err:
            raise ImportError(
                "aiohttp is required for HTTP transport. Install with: pip install nerve[server]"
            ) from err

        self._engine = engine

        self._app = web.Application()
        self._app.router.add_post("/api/command", self._handle_command)
        self._app.router.add_get("/api/events", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        # Keep running
        while True:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner:
            await self._runner.cleanup()

    async def _handle_command(self, request: Any) -> Any:
        """Handle POST /api/command."""
        from aiohttp import web

        from nerve.server.protocols import Command, CommandType

        if not self._engine:
            return web.json_response(
                {"error": "Engine not available"},
                status=503,
            )

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON"},
                status=400,
            )

        try:
            command = Command(
                type=CommandType[body["command_type"]],
                params=body.get("params", {}),
                request_id=body.get("request_id"),
            )
        except KeyError as e:
            return web.json_response(
                {"error": f"Missing field: {e}"},
                status=400,
            )

        result = await self._engine.execute(command)

        return web.json_response(
            {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "request_id": result.request_id,
            }
        )

    async def _handle_websocket(self, request: Any) -> Any:
        """Handle GET /api/events (WebSocket)."""
        from aiohttp import web

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self._websockets.append(ws)

        try:
            async for _msg in ws:
                # We don't expect messages from client on this endpoint
                pass
        finally:
            if ws in self._websockets:
                self._websockets.remove(ws)

        return ws

    async def _handle_health(self, request: Any) -> Any:
        """Handle GET /health."""
        from aiohttp import web

        return web.json_response({"status": "ok"})


@dataclass
class HTTPClient:
    """HTTP client transport.

    Connects to an HTTP server to send commands and receive events.

    Example:
        >>> client = HTTPClient("http://localhost:8080")
        >>> await client.connect()
        >>>
        >>> result = await client.send_command(Command(
        ...     type=CommandType.CREATE_CHANNEL,
        ...     params={"command": "claude"},
        ... ))
    """

    base_url: str
    _session: Any = None  # aiohttp.ClientSession
    _ws: Any = None  # aiohttp.ClientWebSocketResponse
    _event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)  # type: ignore[type-arg]
    _connected: bool = False
    _reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect to the server."""
        try:
            import aiohttp
        except ImportError as err:
            raise ImportError(
                "aiohttp is required for HTTP transport. Install with: pip install nerve[server]"
            ) from err

        self._session = aiohttp.ClientSession()
        self._connected = True

        # Connect WebSocket for events
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws = await self._session.ws_connect(f"{ws_url}/api/events")

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

        if self._ws:
            await self._ws.close()

        if self._session:
            await self._session.close()

    async def send_command(self, command: Command) -> CommandResult:
        """Send a command to the server."""
        from nerve.server.protocols import CommandResult

        if not self._session or not self._connected:
            raise RuntimeError("Not connected")

        async with self._session.post(
            f"{self.base_url}/api/command",
            json={
                "command_type": command.type.name,
                "params": command.params,
                "request_id": command.request_id,
            },
        ) as response:
            data = await response.json()
            return CommandResult(
                success=data["success"],
                data=data.get("data"),
                error=data.get("error"),
                request_id=data.get("request_id"),
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
        """Background loop to read WebSocket messages."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == 1:  # TEXT
                    try:
                        data = json.loads(msg.data)
                        await self._event_queue.put(data)
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        finally:
            self._connected = False
