"""Tests for ClaudeWezTermNode fork functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode
from nerve.core.session.session import Session


@pytest.fixture
def mock_session() -> MagicMock:
    """Create a mock session."""
    session = MagicMock(spec=Session)
    session.name = "test-session"
    session.server_name = "test-server"
    session.history_enabled = False
    session.history_base_dir = None
    session.nodes = {}
    session.graphs = {}
    session.session_logger = None

    def validate_unique_id(id: str, kind: str) -> None:
        if id in session.nodes or id in session.graphs:
            raise ValueError(f"{kind.capitalize()} ID '{id}' conflicts with existing node or graph")

    session.validate_unique_id = validate_unique_id
    return session


@pytest.fixture
def mock_wezterm_node() -> MagicMock:
    """Create a mock WezTermNode."""
    node = MagicMock()
    node.backend = MagicMock()
    node.backend.write = AsyncMock()
    node.backend.config = MagicMock()
    node.backend.config.cwd = "/test/cwd"
    node.pane_id = "test-pane-123"
    return node


class TestExtractBaseCommand:
    """Tests for _extract_base_command() helper."""

    def _create_mock_node(self, command: str, session: MagicMock) -> ClaudeWezTermNode:
        """Create a mock ClaudeWezTermNode with given command."""
        node = object.__new__(ClaudeWezTermNode)
        node._created_via_create = True
        node.id = "test"
        node.session = session
        node._command = command
        node._inner = MagicMock()
        node._claude_session_id = "test-session-id"
        return node

    def test_strips_session_id(self, mock_session: MagicMock) -> None:
        """Should remove --session-id and its argument."""
        node = self._create_mock_node(
            "claude --dangerously-skip-permissions --session-id abc123",
            mock_session,
        )
        result = node._extract_base_command()
        assert "--session-id" not in result
        assert "abc123" not in result
        assert "claude" in result
        assert "--dangerously-skip-permissions" in result

    def test_strips_resume(self, mock_session: MagicMock) -> None:
        """Should remove --resume and its argument."""
        node = self._create_mock_node(
            "claude --resume old-session --fork-session",
            mock_session,
        )
        result = node._extract_base_command()
        assert "--resume" not in result
        assert "old-session" not in result

    def test_strips_fork_session(self, mock_session: MagicMock) -> None:
        """Should remove --fork-session flag."""
        node = self._create_mock_node(
            "claude --fork-session --dangerously-skip-permissions",
            mock_session,
        )
        result = node._extract_base_command()
        assert "--fork-session" not in result
        assert "--dangerously-skip-permissions" in result

    def test_preserves_other_flags(self, mock_session: MagicMock) -> None:
        """Should preserve unrelated flags."""
        node = self._create_mock_node(
            "claude --dangerously-skip-permissions --model opus --session-id abc",
            mock_session,
        )
        result = node._extract_base_command()
        assert "--dangerously-skip-permissions" in result
        assert "--model" in result
        assert "opus" in result
        assert "--session-id" not in result
        assert "abc" not in result

    def test_handles_all_flags_together(self, mock_session: MagicMock) -> None:
        """Should handle all session-related flags together."""
        node = self._create_mock_node(
            "claude --resume old-id --fork-session --session-id new-id --dangerously-skip-permissions",
            mock_session,
        )
        result = node._extract_base_command()
        assert "--resume" not in result
        assert "--fork-session" not in result
        assert "--session-id" not in result
        assert "old-id" not in result
        assert "new-id" not in result
        assert "--dangerously-skip-permissions" in result

    def test_preserves_shell_operators(self, mock_session: MagicMock) -> None:
        """Should preserve && and other shell operators."""
        node = self._create_mock_node(
            "cd ~/project && claude --dangerously-skip-permissions --session-id abc123",
            mock_session,
        )
        result = node._extract_base_command()
        assert "cd ~/project && claude" in result
        assert "--dangerously-skip-permissions" in result
        assert "--session-id" not in result
        assert "abc123" not in result
        # Verify && is NOT quoted
        assert "'&&'" not in result
        assert '"&&"' not in result

    def test_handles_quoted_args(self, mock_session: MagicMock) -> None:
        """Should handle quoted arguments properly."""
        node = self._create_mock_node(
            'claude --dangerously-skip-permissions --session-id "my session id"',
            mock_session,
        )
        result = node._extract_base_command()
        assert "--session-id" not in result
        # Note: shlex may quote the session id differently, so we just check it's removed


class TestSessionIdTracking:
    """Tests for Claude session ID tracking."""

    @pytest.mark.asyncio
    async def test_create_generates_session_id(self, mock_session: MagicMock) -> None:
        """create() should generate a UUID session ID."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
            )

            assert node._claude_session_id is not None
            assert len(node._claude_session_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_create_uses_provided_session_id(self, mock_session: MagicMock) -> None:
        """create() should use provided session ID."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                claude_session_id="custom-session-id",
            )

            assert node._claude_session_id == "custom-session-id"

    @pytest.mark.asyncio
    async def test_create_injects_session_id_in_command(self, mock_session: MagicMock) -> None:
        """create() should inject --session-id into command."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
            )

            # Check that command contains --session-id
            assert "--session-id" in node._command
            assert node._claude_session_id in node._command

    @pytest.mark.asyncio
    async def test_create_does_not_duplicate_session_id(self, mock_session: MagicMock) -> None:
        """create() should not inject --session-id if already present."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            # Command already has --session-id
            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions --session-id existing-id",
            )

            # Should not have duplicate --session-id
            count = node._command.count("--session-id")
            assert count == 1

    @pytest.mark.asyncio
    async def test_create_extracts_session_id_from_command(self, mock_session: MagicMock) -> None:
        """create() should extract --session-id from command when not provided."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            # Command has --session-id, but claude_session_id not provided
            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions --session-id from-command",
            )

            # Should use the session ID from the command
            assert node._claude_session_id == "from-command"

    @pytest.mark.asyncio
    async def test_create_replaces_mismatched_session_id(self, mock_session: MagicMock) -> None:
        """create() should replace --session-id in command when provided differs."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            # Command has different --session-id than provided
            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions --session-id old-id",
                claude_session_id="new-id",
            )

            # Should use provided session ID
            assert node._claude_session_id == "new-id"
            # Command should have the new session ID
            assert "--session-id new-id" in node._command
            assert "old-id" not in node._command
            # Should still have exactly one --session-id
            count = node._command.count("--session-id")
            assert count == 1

    @pytest.mark.asyncio
    async def test_session_id_in_to_info(self, mock_session: MagicMock) -> None:
        """to_info() should include claude_session_id in metadata."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()
        mock_inner.pane_id = "test-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
            )

            info = node.to_info()

            assert "claude_session_id" in info.metadata
            assert info.metadata["claude_session_id"] == node._claude_session_id


class TestClaudeWezTermFork:
    """Tests for ClaudeWezTermNode.fork() method."""

    def _create_mock_source_node(
        self, mock_session: MagicMock, mock_inner: MagicMock
    ) -> ClaudeWezTermNode:
        """Create a mock source node for fork tests."""
        node = object.__new__(ClaudeWezTermNode)
        node._created_via_create = True
        node.id = "source"
        node.session = mock_session
        node._inner = mock_inner
        node._command = "claude --dangerously-skip-permissions --session-id abc123"
        node._claude_session_id = "abc123"
        node._default_parser = MagicMock()
        node._default_parser.value = "CLAUDE"
        node._history_writer = None
        node._proxy_url = None
        node._ready_timeout = 60.0
        node._response_timeout = 1800.0
        node._forked_from = None
        node._fork_timestamp = None
        mock_session.nodes["source"] = node
        return node

    @pytest.mark.asyncio
    async def test_fork_creates_new_node(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should create a new node with forked session."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)

        # Mock the create call for the forked node
        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            assert forked.id == "forked"
            assert forked is not source
            assert "forked" in mock_session.nodes

    @pytest.mark.asyncio
    async def test_fork_uses_resume_and_fork_session_flags(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should use --resume and --fork-session in command."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            # Check command contains --resume with source session ID
            assert f"--resume {source._claude_session_id}" in forked._command
            assert "--fork-session" in forked._command

    @pytest.mark.asyncio
    async def test_fork_generates_new_session_id(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should generate new session ID for forked node."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            assert forked._claude_session_id is not None
            assert forked._claude_session_id != source._claude_session_id
            assert len(forked._claude_session_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_fork_without_session_id_raises(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should raise if source has no session ID."""
        source = self._create_mock_source_node(mock_session, mock_wezterm_node)
        source._claude_session_id = None

        with pytest.raises(ValueError, match="session ID not tracked"):
            await source.fork("forked")

    @pytest.mark.asyncio
    async def test_fork_validates_unique_id(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should raise if target ID exists."""
        source = self._create_mock_source_node(mock_session, mock_wezterm_node)
        mock_session.nodes["existing"] = MagicMock()

        with pytest.raises(ValueError, match="conflicts"):
            await source.fork("existing")

    @pytest.mark.asyncio
    async def test_fork_preserves_proxy_url(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should propagate proxy_url to forked node."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)
        source._proxy_url = "http://127.0.0.1:8080"

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            assert forked._proxy_url == "http://127.0.0.1:8080"

    @pytest.mark.asyncio
    async def test_fork_preserves_timeout_settings(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should preserve ready_timeout and response_timeout."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)
        source._ready_timeout = 120.0
        source._response_timeout = 3600.0

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            assert forked._ready_timeout == 120.0
            assert forked._response_timeout == 3600.0

    @pytest.mark.asyncio
    async def test_fork_sets_metadata(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should set forked_from and fork_timestamp metadata."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        with patch.object(WezTermNode, "_create_internal", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_forked_inner

            forked = await source.fork("forked")

            # Check fork metadata
            assert forked._forked_from == "source"
            assert forked._fork_timestamp is not None
            assert isinstance(forked._fork_timestamp, float)

            # Check it's exposed in to_info()
            info = forked.to_info()
            assert info.metadata["forked_from"] == "source"
            assert "fork_timestamp" in info.metadata

    @pytest.mark.asyncio
    async def test_fork_extracts_cwd_from_inner(
        self, mock_session: MagicMock, mock_wezterm_node: MagicMock
    ) -> None:
        """fork() should use cwd from inner node's backend."""
        from nerve.core.nodes.terminal.wezterm_node import WezTermNode

        source = self._create_mock_source_node(mock_session, mock_wezterm_node)

        mock_forked_inner = MagicMock()
        mock_forked_inner.backend = MagicMock()
        mock_forked_inner.backend.write = AsyncMock()
        mock_forked_inner.pane_id = "forked-pane"

        # Track what cwd was passed to create
        captured_cwd = None

        async def capture_create(*args, **kwargs):
            nonlocal captured_cwd
            captured_cwd = kwargs.get("cwd")
            return mock_forked_inner

        with patch.object(WezTermNode, "_create_internal", side_effect=capture_create):
            await source.fork("forked")

            # Should have used cwd from source's inner node
            assert captured_cwd == "/test/cwd"


class TestAsyncForkHandler:
    """Tests for async fork support in handler."""

    @pytest.mark.asyncio
    async def test_handler_handles_async_fork(self) -> None:
        """Handler should correctly await async fork methods."""
        from nerve.server.handlers.node_lifecycle_handler import NodeLifecycleHandler

        # Create mock session
        mock_session = MagicMock()
        mock_session.nodes = {}

        # Create mock source node with async fork
        mock_source = MagicMock()
        mock_source.id = "source"
        mock_source.persistent = True

        async def async_fork(new_id: str):
            forked = MagicMock()
            forked.id = new_id
            forked.persistent = True
            mock_session.nodes[new_id] = forked
            return forked

        mock_source.fork = async_fork
        mock_session.nodes["source"] = mock_source

        # Create handler with mocks
        handler = NodeLifecycleHandler(
            event_sink=AsyncMock(),
            node_factory=MagicMock(),
            proxy_manager=MagicMock(),
            validation=MagicMock(),
            session_registry=MagicMock(),
            server_name="test",
        )
        handler.session_registry.get_session.return_value = mock_session
        handler.validation.require_param = lambda params, key: params[key]
        handler.validation.get_node = lambda session, node_id: session.nodes[node_id]

        result = await handler.fork_node(
            {
                "session_id": "test",
                "source_id": "source",
                "target_id": "forked",
            }
        )

        assert result["node_id"] == "forked"
        assert result["forked_from"] == "source"
        assert "forked" in mock_session.nodes

    @pytest.mark.asyncio
    async def test_handler_handles_sync_fork(self) -> None:
        """Handler should correctly call sync fork methods."""
        from nerve.server.handlers.node_lifecycle_handler import NodeLifecycleHandler

        # Create mock session
        mock_session = MagicMock()
        mock_session.nodes = {}

        # Create mock source node with sync fork
        mock_source = MagicMock()
        mock_source.id = "source"
        mock_source.persistent = True

        def sync_fork(new_id: str):
            forked = MagicMock()
            forked.id = new_id
            forked.persistent = True
            mock_session.nodes[new_id] = forked
            return forked

        mock_source.fork = sync_fork
        mock_session.nodes["source"] = mock_source

        # Create handler with mocks
        handler = NodeLifecycleHandler(
            event_sink=AsyncMock(),
            node_factory=MagicMock(),
            proxy_manager=MagicMock(),
            validation=MagicMock(),
            session_registry=MagicMock(),
            server_name="test",
        )
        handler.session_registry.get_session.return_value = mock_session
        handler.validation.require_param = lambda params, key: params[key]
        handler.validation.get_node = lambda session, node_id: session.nodes[node_id]

        result = await handler.fork_node(
            {
                "session_id": "test",
                "source_id": "source",
                "target_id": "forked",
            }
        )

        assert result["node_id"] == "forked"
        assert result["forked_from"] == "source"
        assert "forked" in mock_session.nodes
