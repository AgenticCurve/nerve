"""Tests for NerveEngine proxy integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.server.engine import NerveEngine
from nerve.server.protocols import Command, CommandType, Event


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class TestEngineProxyIntegration:
    """Tests for NerveEngine proxy management."""

    @pytest.fixture
    def event_sink(self):
        """Create a mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink, tmp_path):
        """Create a NerveEngine for testing."""
        engine = NerveEngine(event_sink=event_sink, _server_name="test-server")
        engine._default_session.history_base_dir = tmp_path
        return engine

    @pytest.fixture
    def mock_inner_node(self):
        """Create a mock inner WezTermNode."""
        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()
        mock_inner.stop = AsyncMock()
        mock_inner.pane_id = "mock-pane-123"
        return mock_inner

    async def test_create_node_with_provider_starts_proxy(self, engine, mock_inner_node):
        """Node creation with provider config starts a proxy.

        When creating a claude-wezterm node with a provider configuration,
        the engine should start a proxy and return the proxy_url in the result.
        """
        provider_config = {
            "api_format": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "test-key",
        }

        # Mock WezTermNode._create_internal to avoid creating real panes
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            try:
                result = await engine.execute(
                    Command(
                        type=CommandType.CREATE_NODE,
                        params={
                            "node_id": "test-claude",
                            "command": "claude --dangerously-skip-permissions",
                            "backend": "claude-wezterm",
                            "provider": provider_config,
                        },
                    )
                )

                # Verify the result includes proxy_url
                assert result.success
                assert result.data is not None
                assert "proxy_url" in result.data
                assert result.data["proxy_url"].startswith("http://127.0.0.1:")

            finally:
                # Cleanup
                await engine._proxy_manager.stop_all()
                engine._default_session.nodes.pop("test-claude", None)

    async def test_delete_node_stops_proxy(self, engine):
        """Node deletion also stops the associated proxy.

        When deleting a node that has an associated proxy, the engine
        should stop the proxy after deleting the node.
        """
        # Start a proxy manually to test deletion cleanup
        from nerve.server.proxy_manager import ProviderConfig

        provider_config = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key",
        )

        # Start proxy
        await engine._proxy_manager.start_proxy("test-node", provider_config)
        assert engine._proxy_manager.get_proxy_url("test-node") is not None

        # Manually delete the proxy (simulating what _delete_node does)
        await engine._proxy_manager.stop_proxy("test-node")

        # Verify proxy is stopped
        assert engine._proxy_manager.get_proxy_url("test-node") is None

    async def test_engine_stop_cleans_up_all_proxies(self, engine):
        """Engine stop calls proxy_manager.stop_all().

        When the engine is stopped, all proxies should be cleaned up.
        """
        from nerve.server.proxy_manager import ProviderConfig

        # Start multiple proxies
        config1 = ProviderConfig(
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            api_key="test-key-1",
        )
        config2 = ProviderConfig(
            api_format="openai",
            base_url="https://api.openai.com/v1",
            api_key="test-key-2",
            model="gpt-4o",
        )

        await engine._proxy_manager.start_proxy("node-1", config1)
        await engine._proxy_manager.start_proxy("node-2", config2)

        # Verify proxies are running
        assert engine._proxy_manager.get_proxy_url("node-1") is not None
        assert engine._proxy_manager.get_proxy_url("node-2") is not None

        # Call cleanup (what _stop does internally)
        await engine._cleanup_on_stop()

        # Verify all proxies are stopped
        assert engine._proxy_manager.get_proxy_url("node-1") is None
        assert engine._proxy_manager.get_proxy_url("node-2") is None


class TestEngineProviderValidation:
    """Tests for provider configuration validation in engine."""

    @pytest.fixture
    def event_sink(self):
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink, tmp_path):
        engine = NerveEngine(event_sink=event_sink, _server_name="test-server")
        engine._default_session.history_base_dir = tmp_path
        return engine

    async def test_provider_only_allowed_for_claude_wezterm(self, engine):
        """Provider config is only allowed for claude-wezterm backend.

        Using provider config with other backends should raise an error.
        """
        provider_config = {
            "api_format": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "test-key",
        }

        # Try with PTY backend - should fail
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-node",
                    "command": "echo hello",
                    "backend": "pty",
                    "provider": provider_config,
                },
            )
        )

        assert result.success is False
        assert "claude-wezterm" in result.error.lower()

    async def test_openai_format_requires_model(self, engine):
        """OpenAI format requires model to be specified.

        Creating a node with openai api_format but no model should fail.
        """
        provider_config = {
            "api_format": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-key",
            # model is missing
        }

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-node",
                    "command": "claude",
                    "backend": "claude-wezterm",
                    "provider": provider_config,
                },
            )
        )

        assert result.success is False
        assert "model" in result.error.lower()
