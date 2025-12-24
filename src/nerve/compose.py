"""Composition helpers for common nerve configurations.

These helpers make it easy to set up nerve in different configurations
without manually wiring up all the layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        ...     type=CommandType.CREATE_NODE,
        ...     params={"node_id": "my-node", "command": "claude"},
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


async def create_openai_proxy(
    host: str = "127.0.0.1",
    port: int = 3456,
    upstream_base_url: str | None = None,
    upstream_api_key: str | None = None,
    upstream_model: str | None = None,
    config_file: str | None = None,
) -> None:
    """Create and run an OpenAI upstream proxy server.

    This proxy accepts Anthropic Messages API format requests, transforms them
    to OpenAI format, and forwards to an OpenAI-compatible upstream API.
    Useful for using Claude Code with alternative LLM backends.

    Configuration priority:
    1. Function arguments (highest)
    2. Environment variables
    3. Config file (if NERVE_PROXY_CONFIG is set)

    This is a convenience function that blocks until stopped.

    Args:
        host: Host to bind to (or PROXY_HOST env var).
        port: Port to bind to (or PROXY_PORT env var).
        upstream_base_url: Upstream API URL (or OPENAI_BASE_URL env var).
        upstream_api_key: Upstream API key (or OPENAI_API_KEY env var).
        upstream_model: Default model (or OPENAI_MODEL env var).
        config_file: Path to YAML config (or NERVE_PROXY_CONFIG env var).

    Example:
        >>> # Using environment variables
        >>> # export OPENAI_BASE_URL=https://api.openai.com/v1
        >>> # export OPENAI_API_KEY=sk-...
        >>> # export OPENAI_MODEL=gpt-4o
        >>> await create_openai_proxy()
        >>>
        >>> # Or with explicit arguments
        >>> await create_openai_proxy(
        ...     upstream_base_url="https://api.openai.com/v1",
        ...     upstream_api_key="sk-...",
        ...     upstream_model="gpt-4o",
        ... )
    """
    import os

    from nerve.gateway.openai_proxy import (
        OpenAIProxyConfig,
        OpenAIProxyServer,
    )

    # Load config file if specified
    file_config: dict[str, Any] = {}
    config_path = config_file or os.environ.get("NERVE_PROXY_CONFIG")
    if config_path:
        try:
            import yaml  # type: ignore[import-untyped]

            with open(config_path) as f:
                file_config = yaml.safe_load(f) or {}
        except ImportError:
            # YAML not available, skip config file
            pass
        except FileNotFoundError:
            pass

    # Build config with priority: args > env > file > defaults
    def get_value(arg: str | None, env_key: str, file_key: str, default: str) -> str:
        if arg is not None:
            return arg
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val
        file_val = file_config.get(file_key)
        if file_val:
            return str(file_val)
        return default

    config = OpenAIProxyConfig(
        host=get_value(host if host != "127.0.0.1" else None, "PROXY_HOST", "host", "127.0.0.1"),
        port=int(get_value(str(port) if port != 3456 else None, "PROXY_PORT", "port", "3456")),
        upstream_base_url=get_value(upstream_base_url, "OPENAI_BASE_URL", "upstream_base_url", ""),
        upstream_api_key=get_value(upstream_api_key, "OPENAI_API_KEY", "upstream_api_key", ""),
        upstream_model=get_value(upstream_model, "OPENAI_MODEL", "upstream_model", ""),
    )

    # Validate required config
    if not config.upstream_base_url:
        raise ValueError(
            "upstream_base_url is required. Set OPENAI_BASE_URL env var or pass explicitly."
        )
    if not config.upstream_api_key:
        raise ValueError(
            "upstream_api_key is required. Set OPENAI_API_KEY env var or pass explicitly."
        )
    if not config.upstream_model:
        raise ValueError("upstream_model is required. Set OPENAI_MODEL env var or pass explicitly.")

    server = OpenAIProxyServer(config=config)
    await server.serve()


async def create_anthropic_proxy(
    host: str = "127.0.0.1",
    port: int = 3457,
    upstream_base_url: str | None = None,
    upstream_api_key: str | None = None,
    config_file: str | None = None,
) -> None:
    """Create and run an Anthropic upstream proxy server.

    This proxy accepts Anthropic Messages API format requests and forwards
    them directly to an Anthropic-compatible upstream API with no transformation.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        upstream_base_url: Upstream API URL.
        upstream_api_key: Upstream API key.
        config_file: Path to YAML config (or NERVE_PROXY_CONFIG env var).
    """
    import os

    from nerve.gateway.anthropic_proxy import (
        AnthropicProxyConfig,
        AnthropicProxyServer,
    )

    # Load config file if specified
    file_config: dict[str, Any] = {}
    config_path = config_file or os.environ.get("NERVE_PROXY_CONFIG")
    if config_path:
        try:
            import yaml

            with open(config_path) as f:
                file_config = yaml.safe_load(f) or {}
        except ImportError:
            # YAML not available, skip config file
            pass
        except FileNotFoundError:
            pass

    # Build config with priority: args > env > file > defaults
    def get_value(arg: str | None, env_key: str, file_key: str, default: str) -> str:
        if arg is not None:
            return arg
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val
        file_val = file_config.get(file_key)
        if file_val:
            return str(file_val)
        return default

    config = AnthropicProxyConfig(
        host=get_value(host if host != "127.0.0.1" else None, "PROXY_HOST", "host", "127.0.0.1"),
        port=int(get_value(str(port) if port != 3457 else None, "PROXY_PORT", "port", "3457")),
        upstream_base_url=get_value(upstream_base_url, "ANTHROPIC_BASE_URL", "upstream_base_url", ""),
        upstream_api_key=get_value(upstream_api_key, "ANTHROPIC_API_KEY", "upstream_api_key", ""),
    )

    server = AnthropicProxyServer(config=config)
    await server.serve()
