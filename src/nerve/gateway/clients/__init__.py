"""LLM client module for upstream API calls.

This module provides HTTP clients for calling upstream LLM APIs
with resilience patterns like circuit breaker and retry logic.
"""

from .llm_client import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    LLMClient,
    LLMClientConfig,
    UpstreamError,
)

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "LLMClient",
    "LLMClientConfig",
    "UpstreamError",
]
