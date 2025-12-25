"""Passthrough proxy server for Anthropic-format APIs.

Exposes /v1/messages endpoint that accepts Anthropic Messages API format
and proxies requests to an Anthropic-compatible upstream (e.g., GLM-4.5, api.anthropic.com).

This is a re-export of AnthropicProxyServer with consistent naming for the
multi-provider support feature. The passthrough proxy:
1. Accepts Anthropic format requests from Claude Code CLI
2. Logs the request for debugging
3. Forwards directly to upstream (no transformation needed)
4. Optionally overrides the model name
5. Logs and streams the response back
"""

from __future__ import annotations

# Re-export from anthropic_proxy with passthrough-focused names
from nerve.gateway.anthropic_proxy import (
    AnthropicProxyConfig as PassthroughProxyConfig,
)
from nerve.gateway.anthropic_proxy import (
    AnthropicProxyServer as PassthroughProxyServer,
)

__all__ = [
    "PassthroughProxyConfig",
    "PassthroughProxyServer",
]
