"""Composition helpers for common nerve configurations.

These helpers make it easy to set up nerve in different configurations
without manually wiring up all the layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.transport import InProcessTransport


def create_standalone() -> tuple[NerveEngine, InProcessTransport]:
    """Create a standalone in-process nerve setup.

    Returns:
        Tuple of (engine, transport) ready to use.

    Example:
        >>> engine, transport = create_standalone()
        >>>
        >>> result = await transport.send_command(Command(
        ...     type=CommandType.CREATE_CHANNEL,
        ...     params={"command": "claude"},
        ... ))
    """
    from nerve.server import NerveEngine
    from nerve.transport import InProcessTransport

    transport = InProcessTransport()
    engine = NerveEngine(event_sink=transport)
    transport.bind(engine)

    return engine, transport


async def create_socket_server(socket_path: str = "/tmp/nerve.sock") -> None:
    """Create and run a socket-based nerve server.

    This is a convenience function that blocks until stopped.

    Args:
        socket_path: Path for the Unix socket.
    """
    from nerve.server import NerveEngine
    from nerve.transport import UnixSocketServer

    transport = UnixSocketServer(socket_path)
    engine = NerveEngine(event_sink=transport)

    await transport.serve(engine)


async def create_http_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Create and run an HTTP-based nerve server.

    This is a convenience function that blocks until stopped.

    Args:
        host: Host to bind to.
        port: Port to bind to.
    """
    from nerve.server import NerveEngine
    from nerve.transport import HTTPServer

    transport = HTTPServer(host=host, port=port)
    engine = NerveEngine(event_sink=transport)

    await transport.serve(engine)
