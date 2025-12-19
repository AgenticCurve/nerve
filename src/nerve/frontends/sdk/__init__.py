"""Python SDK for nerve.

High-level Python API for programmatic interaction with nerve.

Classes:
    NerveClient: Main client class for interacting with nerve.
    RemoteChannel: Proxy for a remote channel.

Example (with server):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.connect("/tmp/nerve.sock") as client:
    ...     channel = await client.create_channel("claude", cwd="/project")
    ...     response = await channel.send("Explain this code", parser="claude")
    ...     print(response.raw)

Example (standalone - uses core directly):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.standalone() as client:
    ...     channel = await client.create_channel("claude")
    ...     response = await channel.send("Hello!", parser="claude")
"""

from nerve.frontends.sdk.client import NerveClient, RemoteChannel

__all__ = ["NerveClient", "RemoteChannel"]
