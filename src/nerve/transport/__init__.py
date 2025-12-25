"""Transport - Communication adapters.

Transport adapters handle the communication between clients and the server.
They implement the EventSink protocol to receive events from the engine,
and provide methods for clients to send commands.

Available transports:
    InProcessTransport: Direct in-process communication (no IPC).
    UnixSocketTransport: Unix domain socket communication.
    HTTPTransport: HTTP REST + WebSocket communication.

Example (in-process):
    >>> from nerve.transport import InProcessTransport
    >>> from nerve.server import build_nerve_engine
    >>>
    >>> transport = InProcessTransport()
    >>> engine = build_nerve_engine(event_sink=transport)
    >>>
    >>> # Client uses transport directly
    >>> result = await transport.send_command(Command(...))
    >>> async for event in transport.events():
    ...     print(event)

Example (socket server):
    >>> from nerve.transport import UnixSocketTransport
    >>> from nerve.server import build_nerve_engine
    >>>
    >>> transport = UnixSocketTransport("/tmp/nerve.sock")
    >>> engine = build_nerve_engine(event_sink=transport)
    >>> await transport.serve(engine)
"""

from nerve.transport.http import HTTPClient, HTTPServer
from nerve.transport.in_process import InProcessTransport
from nerve.transport.protocol import ClientTransport, ServerTransport, Transport
from nerve.transport.tcp_socket import TCPSocketClient, TCPSocketServer
from nerve.transport.unix_socket import UnixSocketClient, UnixSocketServer

__all__ = [
    # Protocols
    "Transport",
    "ClientTransport",
    "ServerTransport",
    # Implementations
    "InProcessTransport",
    "UnixSocketServer",
    "UnixSocketClient",
    "TCPSocketServer",
    "TCPSocketClient",
    "HTTPServer",
    "HTTPClient",
]
