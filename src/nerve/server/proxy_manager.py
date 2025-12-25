"""Proxy Manager - Manages proxy instances for nodes.

ProxyManager handles the lifecycle of proxy instances that translate
between different LLM API formats (Anthropic ↔ OpenAI) or passthrough
requests for logging/debugging.

Key Concepts:
- Each node can have its own proxy instance (isolation)
- Proxy starts BEFORE node creation (so Claude Code can connect)
- Proxy stops AFTER node deletion (cleanup)
- Ports are auto-assigned using socket.bind(("", 0))
"""

from __future__ import annotations

import asyncio
import errno
import logging
import socket
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ProxyStartError(Exception):
    """Failed to start proxy server."""

    pass


class ProxyHealthError(Exception):
    """Proxy health check failed."""

    pass


@dataclass
class ProviderConfig:
    """Configuration for a custom LLM provider.

    When provided to ClaudeWezTermNode, a proxy will be started
    to handle the connection to this provider.

    Attributes:
        api_format: API format type ("anthropic", "openai", "gemini" future)
        base_url: Upstream URL (e.g., "https://api.openai.com/v1")
        api_key: Provider API key
        model: Model to use. Required for transform proxies (openai/gemini).
               Optional for passthrough (None = keep original from request).
        debug_dir: Directory for debug logs. None = auto-set to session log dir.

    Example:
        >>> # OpenAI backend (transform proxy)
        >>> config = ProviderConfig(
        ...     api_format="openai",
        ...     base_url="https://api.openai.com/v1",
        ...     api_key="sk-...",
        ...     model="gpt-4.1",
        ... )
        >>>
        >>> # Anthropic-format API (passthrough proxy for logging)
        >>> config = ProviderConfig(
        ...     api_format="anthropic",
        ...     base_url="https://api.glm.ai/v1",
        ...     api_key="glm-...",
        ...     model="glm-4.5",  # optional, can override model
        ... )
    """

    api_format: Literal["anthropic", "openai"]
    base_url: str
    api_key: str
    model: str | None = None
    debug_dir: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration."""
        # Transform proxies require model to be specified
        if self.needs_transform and self.model is None:
            raise ValueError(f"model is required for api_format='{self.api_format}'")

    @property
    def needs_transform(self) -> bool:
        """Whether this provider needs format transformation."""
        return self.api_format != "anthropic"

    @property
    def proxy_type(self) -> str:
        """Which proxy implementation to use."""
        if self.api_format == "anthropic":
            return "passthrough"
        elif self.api_format == "openai":
            return "openai"
        else:
            raise ValueError(f"Unknown api_format: {self.api_format}")


@dataclass
class ProxyInstance:
    """A running proxy instance.

    Attributes:
        node_id: ID of the node this proxy serves
        port: Port the proxy is listening on
        server: The proxy server instance
        task: The asyncio task running the server
        config: The provider configuration
    """

    node_id: str
    port: int
    server: Any  # OpenAIProxyServer or PassthroughProxyServer
    task: asyncio.Task[Any]
    config: ProviderConfig


def _find_free_port() -> int:
    """Find a free port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port: int = s.getsockname()[1]
    return port


@dataclass
class ProxyManager:
    """Manages proxy instances for nodes.

    ProxyManager handles starting, stopping, and tracking proxy instances.
    Each node gets its own isolated proxy instance.

    Attributes:
        _proxies: Mapping of node_id to ProxyInstance
        _health_timeout: Timeout for health check in seconds
        _default_debug_dir: Default directory for debug logs

    Example:
        >>> manager = ProxyManager()
        >>>
        >>> # Start proxy for a node
        >>> config = ProviderConfig(
        ...     api_format="openai",
        ...     base_url="https://api.openai.com/v1",
        ...     api_key="sk-...",
        ...     model="gpt-4.1",
        ... )
        >>> instance = await manager.start_proxy("my-node", config)
        >>> print(instance.port)  # Auto-assigned port
        >>>
        >>> # Get proxy URL
        >>> url = manager.get_proxy_url("my-node")
        >>> print(url)  # "http://127.0.0.1:XXXXX"
        >>>
        >>> # Stop proxy when done
        >>> await manager.stop_proxy("my-node")
    """

    _proxies: dict[str, ProxyInstance] = field(default_factory=dict)
    _health_timeout: float = 10.0
    _default_debug_dir: Path | None = None

    async def start_proxy(
        self,
        node_id: str,
        config: ProviderConfig,
        debug_dir: str | None = None,
    ) -> ProxyInstance:
        """Start a proxy for a node.

        Args:
            node_id: The node ID this proxy will serve
            config: Provider configuration
            debug_dir: Override debug directory (optional)

        Returns:
            ProxyInstance with port and server details

        Raises:
            ProxyStartError: If proxy fails to start after retries
            ProxyHealthError: If health check times out
        """
        if node_id in self._proxies:
            raise ProxyStartError(f"Proxy already exists for node: {node_id}")

        # Determine debug directory
        effective_debug_dir = debug_dir or config.debug_dir
        if effective_debug_dir is None and self._default_debug_dir:
            effective_debug_dir = str(self._default_debug_dir / "proxy" / node_id)

        # Retry loop to handle TOCTOU race in port allocation
        max_retries = 5
        last_error: Exception | None = None

        for attempt in range(max_retries):
            # Find a free port
            port = _find_free_port()
            logger.debug(
                f"Allocated port {port} for proxy serving node '{node_id}' "
                f"(attempt {attempt + 1}/{max_retries})"
            )

            try:
                # Create appropriate proxy server
                if config.proxy_type == "passthrough":
                    server = await self._create_passthrough_proxy(port, config, effective_debug_dir)
                elif config.proxy_type == "openai":
                    server = await self._create_openai_proxy(port, config, effective_debug_dir)
                else:
                    raise ProxyStartError(f"Unknown proxy type: {config.proxy_type}")

                # Start the server in a task
                task = asyncio.create_task(server.serve())

                # Wait for server to become healthy
                try:
                    await self._wait_for_health(port)
                except TimeoutError:
                    # Health check failed - cleanup and retry
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    last_error = ProxyHealthError(
                        f"Health check timeout on port {port} (attempt {attempt + 1}/{max_retries})"
                    )
                    logger.debug(f"Health check failed on port {port}, retrying...")
                    await asyncio.sleep(0.1 * (attempt + 1))  # Backoff
                    continue

                # Success! Create and store instance
                instance = ProxyInstance(
                    node_id=node_id,
                    port=port,
                    server=server,
                    task=task,
                    config=config,
                )
                self._proxies[node_id] = instance

                logger.info(
                    f"Started {config.proxy_type} proxy for node '{node_id}' on port {port} "
                    f"-> {config.base_url}"
                )

                return instance

            except OSError as e:
                # Handle port already in use (TOCTOU race)
                if e.errno == errno.EADDRINUSE:
                    logger.debug(f"Port {port} already in use (TOCTOU race), retrying...")
                    last_error = e
                    await asyncio.sleep(0.1 * (attempt + 1))  # Backoff
                    continue
                # Other OS errors are fatal
                raise ProxyStartError(f"Failed to start proxy: {e}") from e

        # All retries exhausted
        error_msg = f"Failed to start proxy for node '{node_id}' after {max_retries} attempts"
        if last_error:
            raise ProxyStartError(error_msg) from last_error
        else:
            raise ProxyStartError(error_msg)

    async def stop_proxy(self, node_id: str) -> None:
        """Stop proxy for a specific node.

        Other nodes' proxies continue running unaffected.

        Args:
            node_id: The node ID whose proxy to stop
        """
        instance = self._proxies.pop(node_id, None)
        if instance is None:
            logger.debug(f"No proxy found for node '{node_id}'")
            return

        logger.info(f"Stopping proxy for node '{node_id}' on port {instance.port}")

        # Signal shutdown
        instance.server._shutdown_event.set()

        # Wait for graceful termination (completes in-flight requests)
        try:
            await asyncio.wait_for(instance.task, timeout=5.0)
        except TimeoutError:
            logger.warning(f"Proxy for '{node_id}' did not stop gracefully, cancelling")
            instance.task.cancel()
            try:
                await instance.task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass

        logger.debug(f"Proxy for node '{node_id}' stopped, port {instance.port} freed")

    def get_proxy_url(self, node_id: str) -> str | None:
        """Get the URL for a node's proxy.

        Args:
            node_id: The node ID

        Returns:
            URL like "http://127.0.0.1:XXXXX" or None if no proxy
        """
        instance = self._proxies.get(node_id)
        if instance is None:
            return None
        return f"http://127.0.0.1:{instance.port}"

    def get_proxy_instance(self, node_id: str) -> ProxyInstance | None:
        """Get the proxy instance for a node.

        Args:
            node_id: The node ID

        Returns:
            ProxyInstance or None if no proxy
        """
        return self._proxies.get(node_id)

    async def stop_all(self) -> None:
        """Stop all proxies.

        Called during engine shutdown to cleanup all proxy instances.
        """
        if not self._proxies:
            return

        logger.info(f"Stopping all proxies ({len(self._proxies)} active)")

        # Stop all proxies concurrently
        await asyncio.gather(
            *[self.stop_proxy(node_id) for node_id in list(self._proxies.keys())],
            return_exceptions=True,
        )

    async def _create_passthrough_proxy(
        self,
        port: int,
        config: ProviderConfig,
        debug_dir: str | None,
    ) -> Any:
        """Create a passthrough (Anthropic-format) proxy server."""
        from nerve.gateway.passthrough_proxy import (
            PassthroughProxyConfig,
            PassthroughProxyServer,
        )

        proxy_config = PassthroughProxyConfig(
            host="127.0.0.1",
            port=port,
            upstream_base_url=config.base_url,
            upstream_api_key=config.api_key,
            upstream_model=config.model,
            debug_dir=debug_dir,
        )

        return PassthroughProxyServer(config=proxy_config)

    async def _create_openai_proxy(
        self,
        port: int,
        config: ProviderConfig,
        debug_dir: str | None,
    ) -> Any:
        """Create an OpenAI transform proxy server."""
        from nerve.gateway.openai_proxy import (
            OpenAIProxyConfig,
            OpenAIProxyServer,
        )

        # Model is required for OpenAI proxy (validated in ProviderConfig.__post_init__)
        assert config.model is not None

        proxy_config = OpenAIProxyConfig(
            host="127.0.0.1",
            port=port,
            upstream_base_url=config.base_url,
            upstream_api_key=config.api_key,
            upstream_model=config.model,
            debug_dir=debug_dir,
        )

        return OpenAIProxyServer(config=proxy_config)

    async def _wait_for_health(self, port: int) -> None:
        """Wait for proxy to become healthy.

        Args:
            port: The port to check

        Raises:
            asyncio.TimeoutError: If health check times out
        """
        import aiohttp

        url = f"http://127.0.0.1:{port}/health"
        start_time = asyncio.get_event_loop().time()

        async with aiohttp.ClientSession() as session:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self._health_timeout:
                    raise TimeoutError()

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=1.0)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "ok":
                                logger.debug(f"Proxy on port {port} is healthy")
                                return
                except (TimeoutError, aiohttp.ClientError):
                    pass

                await asyncio.sleep(0.1)
