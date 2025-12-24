"""HTTP transport - REST API + WebSocket for events.

Provides HTTP-based communication for web clients and remote access.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event

logger = logging.getLogger(__name__)


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
    _websockets: list[Any] = field(default_factory=list)
    _running: bool = False

    async def emit(self, event: Event) -> None:
        """Broadcast event to all WebSocket clients."""
        if not self._websockets:
            return

        data = json.dumps(
            {
                "type": "event",
                "event_type": event.type.name,
                "node_id": event.node_id,
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
        self._running = True

        self._app = web.Application()
        self._app.router.add_post("/api/command", self._handle_command)
        self._app.router.add_post("/api/shutdown", self._handle_shutdown)
        self._app.router.add_get("/api/events", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("HTTP server started on %s:%s", self.host, self.port)

        # Serve until shutdown requested (poll every 0.1s for responsive shutdown)
        while self._running and not engine.shutdown_requested:
            await asyncio.sleep(0.1)

        logger.info("HTTP server shutdown requested")

        # Clean up after shutdown
        await self.stop()

    async def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False

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

        client_addr = request.remote or "unknown"
        logger.debug("WebSocket client connected: %s", client_addr)
        self._websockets.append(ws)

        try:
            async for _msg in ws:
                # We don't expect messages from client on this endpoint
                pass
        finally:
            if ws in self._websockets:
                self._websockets.remove(ws)
            logger.debug("WebSocket client disconnected: %s", client_addr)

        return ws

    async def _handle_health(self, request: Any) -> Any:
        """Handle GET /health."""
        from aiohttp import web

        return web.json_response({"status": "ok"})

    async def _handle_shutdown(self, request: Any) -> Any:
        """Handle POST /api/shutdown."""
        from aiohttp import web

        if not self._engine:
            return web.json_response(
                {"error": "Engine not available"},
                status=503,
            )

        # Trigger engine shutdown (the serve loop polls this)
        self._engine._shutdown_requested = True
        self._running = False

        return web.json_response({"success": True, "message": "Shutdown initiated"})


@dataclass
class HTTPClient:
    """HTTP client transport.

    Connects to an HTTP server to send commands and receive events.

    Example:
        >>> client = HTTPClient("http://localhost:8080")
        >>> await client.connect()
        >>>
        >>> result = await client.send_command(Command(
        ...     type=CommandType.CREATE_NODE,
        ...     params={"node_id": "my-node", "command": "claude"},
        ... ))
    """

    base_url: str
    _session: Any = None  # aiohttp.ClientSession
    _ws: Any = None  # aiohttp.ClientWebSocketResponse
    _event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)  # type: ignore[type-arg]
    _connected: bool = False
    _reader_task: asyncio.Task[Any] | None = None
    _last_error: Exception | None = field(default=None, repr=False)
    _error_count: int = field(default=0, repr=False)

    async def connect(self, with_events: bool = False) -> None:
        """Connect to the server.

        Args:
            with_events: If True, also connect WebSocket for event streaming.
                        For simple command/response, this isn't needed.
        """
        try:
            import aiohttp
        except ImportError as err:
            raise ImportError(
                "aiohttp is required for HTTP transport. Install with: pip install nerve[server]"
            ) from err

        self._session = aiohttp.ClientSession()
        self._connected = True
        logger.debug("HTTP client connected to %s", self.base_url)

        # Optionally connect WebSocket for events
        if with_events:
            ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            try:
                self._ws = await self._session.ws_connect(f"{ws_url}/api/events")
                logger.debug("WebSocket connected to %s/api/events", ws_url)
                # Start background reader
                self._reader_task = asyncio.create_task(self._read_loop())
            except Exception as e:
                # WebSocket connection failed, but we can still send commands
                self._last_error = e
                logger.warning("WebSocket connection failed (commands still work): %s", e)

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

    async def send_command(self, command: Command, timeout: float = 300.0) -> CommandResult:
        """Send a command to the server.

        Args:
            command: The command to send.
            timeout: Timeout in seconds (default: 60s).

        Returns:
            CommandResult from the server.

        Raises:
            RuntimeError: If not connected.
            TimeoutError: If the request times out.
        """
        import aiohttp

        from nerve.server.protocols import CommandResult

        if not self._session or not self._connected:
            raise RuntimeError("Not connected")

        try:
            async with self._session.post(
                f"{self.base_url}/api/command",
                json={
                    "command_type": command.type.name,
                    "params": command.params,
                    "request_id": command.request_id,
                },
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                data = await response.json()
                return CommandResult(
                    success=data["success"],
                    data=data.get("data"),
                    error=data.get("error"),
                    request_id=data.get("request_id"),
                )
        except TimeoutError:
            raise TimeoutError(f"Command timed out after {timeout}s") from None

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
        """Background loop to read WebSocket messages.

        Reads JSON messages from the WebSocket and puts them in the event queue.
        Errors are logged and tracked in _last_error and _error_count.
        """
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == 1:  # TEXT
                    try:
                        data = json.loads(msg.data)
                        await self._event_queue.put(data)
                    except json.JSONDecodeError as e:
                        self._error_count += 1
                        self._last_error = e
                        logger.warning("Failed to parse JSON from WebSocket: %s", e)
        except asyncio.CancelledError:
            logger.debug("WebSocket read loop cancelled")
            raise
        except ConnectionResetError as e:
            self._last_error = e
            logger.debug("WebSocket connection reset by server")
        except Exception as e:
            # Check if it's a connection-related error from aiohttp
            error_name = type(e).__name__
            if "Connection" in error_name or "WSClosed" in error_name:
                self._last_error = e
                logger.debug("WebSocket connection closed: %s", e)
            else:
                self._error_count += 1
                self._last_error = e
                logger.error("Unexpected error in WebSocket read loop: %s", e, exc_info=True)
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
