"""Python SDK for nerve.

High-level Python API for programmatic interaction with nerve.

Classes:
    NerveClient: Main client class for interacting with nerve.
    RemoteNode: Proxy for a remote node.

Example (with server):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.connect("/tmp/nerve.sock") as client:
    ...     node = await client.create_node("claude", cwd="/project")
    ...     response = await node.send("Explain this code", parser="claude")
    ...     print(response.raw)

Example (standalone - uses core directly):
    >>> from nerve.frontends.sdk import NerveClient
    >>>
    >>> async with NerveClient.standalone() as client:
    ...     node = await client.create_node("claude")
    ...     response = await node.send("Hello!", parser="claude")
"""

from nerve.frontends.sdk.client import NerveClient, RemoteNode

__all__ = ["NerveClient", "RemoteNode"]
