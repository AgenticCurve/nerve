"""Python SDK for nerve.

High-level Python API for programmatic interaction with nerve.

Classes:
    NerveClient: Main client class for interacting with nerve.
    RemoteSession: Proxy for a remote session.

Example (with server):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.connect("/tmp/nerve.sock") as client:
    ...     session = await client.create_session("claude", cwd="/project")
    ...     response = await session.send("Explain this code")
    ...     print(response.raw)

Example (standalone - uses core directly):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.standalone() as client:
    ...     session = await client.create_session("claude")
    ...     response = await session.send("Hello!")
"""

from nerve.frontends.sdk.client import NerveClient, RemoteSession

__all__ = ["NerveClient", "RemoteSession"]
