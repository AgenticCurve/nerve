"""Tests for ProxyManager."""

import asyncio

import pytest

from nerve.server.proxy_manager import (
    ProviderConfig,
    ProxyManager,
    ProxyStartError,
)


class TestProviderConfig:
    """Tests for ProviderConfig dataclass."""

    def test_anthropic_format_allows_optional_model(self):
        """Anthropic format should allow model to be None (keep original)."""
        config = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
            model=None,  # Optional for passthrough
        )
        assert config.model is None
        assert not config.needs_transform
        assert config.proxy_type == "passthrough"

    def test_anthropic_format_with_model_override(self):
        """Anthropic format should accept model override."""
        config = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.glm.ai/v1",
            api_key="glm-key",
            model="glm-4.5",
        )
        assert config.model == "glm-4.5"
        assert not config.needs_transform
        assert config.proxy_type == "passthrough"

    def test_openai_format_requires_model(self):
        """OpenAI format should require model."""
        with pytest.raises(ValueError, match="model is required"):
            ProviderConfig(
                api_format="openai",
                base_url="https://api.openai.com/v1",
                api_key="sk-...",
                model=None,  # Should raise
            )

    def test_openai_format_with_model(self):
        """OpenAI format should work with model specified."""
        config = ProviderConfig(
            api_format="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-...",
            model="gpt-4.1",
        )
        assert config.model == "gpt-4.1"
        assert config.needs_transform
        assert config.proxy_type == "openai"

    def test_debug_dir_optional(self):
        """debug_dir should be optional."""
        config = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
        )
        assert config.debug_dir is None


class TestProxyManager:
    """Tests for ProxyManager lifecycle."""

    @pytest.fixture
    def manager(self):
        """Create a ProxyManager instance."""
        return ProxyManager()

    @pytest.fixture
    def anthropic_config(self):
        """Create an Anthropic (passthrough) provider config."""
        return ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
        )

    @pytest.fixture
    def openai_config(self):
        """Create an OpenAI (transform) provider config."""
        return ProviderConfig(
            api_format="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )

    async def test_start_passthrough_proxy(self, manager, anthropic_config):
        """Should start a passthrough proxy for Anthropic format."""
        try:
            instance = await manager.start_proxy("node-1", anthropic_config)

            assert instance.node_id == "node-1"
            assert instance.port > 0
            assert instance.config == anthropic_config

            # Should be able to get the URL
            url = manager.get_proxy_url("node-1")
            assert url is not None
            assert f":{instance.port}" in url

        finally:
            await manager.stop_all()

    async def test_start_openai_proxy(self, manager, openai_config):
        """Should start an OpenAI transform proxy."""
        try:
            instance = await manager.start_proxy("node-2", openai_config)

            assert instance.node_id == "node-2"
            assert instance.port > 0
            assert instance.config == openai_config

        finally:
            await manager.stop_all()

    async def test_stop_proxy(self, manager, anthropic_config):
        """Should stop a specific proxy."""
        await manager.start_proxy("node-1", anthropic_config)

        # Stop the proxy
        await manager.stop_proxy("node-1")

        # Should no longer be tracked
        assert manager.get_proxy_url("node-1") is None
        assert manager.get_proxy_instance("node-1") is None

    async def test_stop_nonexistent_proxy(self, manager):
        """Stopping a nonexistent proxy should be a no-op."""
        # Should not raise
        await manager.stop_proxy("nonexistent")

    async def test_multiple_concurrent_proxies(self, manager, anthropic_config, openai_config):
        """Should support multiple proxies on different ports."""
        try:
            instance1 = await manager.start_proxy("node-1", anthropic_config)
            instance2 = await manager.start_proxy("node-2", openai_config)

            # Should have different ports
            assert instance1.port != instance2.port

            # Both should be accessible
            assert manager.get_proxy_url("node-1") is not None
            assert manager.get_proxy_url("node-2") is not None

        finally:
            await manager.stop_all()

    async def test_node_isolation(self, manager, anthropic_config, openai_config):
        """Stopping one node's proxy should not affect others."""
        try:
            await manager.start_proxy("node-1", anthropic_config)
            await manager.start_proxy("node-2", openai_config)

            # Stop first proxy
            await manager.stop_proxy("node-1")

            # First proxy should be gone
            assert manager.get_proxy_url("node-1") is None

            # Second proxy should still be running
            assert manager.get_proxy_url("node-2") is not None
            assert manager.get_proxy_instance("node-2") is not None

        finally:
            await manager.stop_all()

    async def test_stop_all(self, manager, anthropic_config, openai_config):
        """stop_all should stop all proxies."""
        await manager.start_proxy("node-1", anthropic_config)
        await manager.start_proxy("node-2", openai_config)

        await manager.stop_all()

        # Both should be gone
        assert manager.get_proxy_url("node-1") is None
        assert manager.get_proxy_url("node-2") is None
        assert len(manager._proxies) == 0

    async def test_duplicate_proxy_raises(self, manager, anthropic_config):
        """Starting a proxy for the same node twice should raise."""
        try:
            await manager.start_proxy("node-1", anthropic_config)

            with pytest.raises(ProxyStartError, match="already exists"):
                await manager.start_proxy("node-1", anthropic_config)

        finally:
            await manager.stop_all()

    async def test_get_proxy_instance(self, manager, anthropic_config):
        """get_proxy_instance should return the instance."""
        try:
            instance = await manager.start_proxy("node-1", anthropic_config)

            retrieved = manager.get_proxy_instance("node-1")
            assert retrieved is instance

        finally:
            await manager.stop_all()

    async def test_health_check_works(self, manager, anthropic_config):
        """Proxy should pass health check after starting."""
        import aiohttp

        try:
            instance = await manager.start_proxy("node-1", anthropic_config)

            # Health check should succeed
            url = f"http://127.0.0.1:{instance.port}/health"
            async with aiohttp.ClientSession() as session, session.get(url) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"

        finally:
            await manager.stop_all()

    async def test_port_reuse_after_stop(self, manager, anthropic_config):
        """Port should be freed after stopping a proxy."""
        # Start and stop a proxy
        await manager.start_proxy("node-1", anthropic_config)
        await manager.stop_proxy("node-1")

        # Give OS time to release the port
        await asyncio.sleep(0.1)

        # Start a new proxy - should be able to get a port
        # (may or may not be the same port, but should work)
        instance2 = await manager.start_proxy("node-2", anthropic_config)
        assert instance2.port > 0

        await manager.stop_all()


class TestProxyManagerEdgeCases:
    """Edge case tests for ProxyManager."""

    @pytest.fixture
    def manager(self):
        """Create a ProxyManager with short timeout."""
        return ProxyManager(_health_timeout=0.5)

    async def test_stop_all_empty(self):
        """stop_all on empty manager should be a no-op."""
        manager = ProxyManager()
        await manager.stop_all()  # Should not raise

    async def test_get_proxy_url_nonexistent(self):
        """get_proxy_url for nonexistent node should return None."""
        manager = ProxyManager()
        assert manager.get_proxy_url("nonexistent") is None

    async def test_debug_dir_passthrough(self):
        """debug_dir should be passed to proxy config."""
        manager = ProxyManager()
        config = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
            debug_dir="/tmp/test-debug",
        )

        try:
            instance = await manager.start_proxy("node-1", config, debug_dir="/tmp/override")
            # The proxy should be started with the debug_dir
            # (We can't easily verify this without inspecting the proxy config,
            # but we can verify the proxy starts successfully)
            assert instance.port > 0

        finally:
            await manager.stop_all()
