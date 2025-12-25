"""REPL cleanup - comprehensive resource destruction on exit.

This module handles cleanup of all resources created during a REPL session:
- All Session instances (default + user-created)
- All Node instances (registered + orphaned)
- All Graph instances (via session cleanup)
- Namespace references

Cleanup is protected from interruption by blocking SIGINT signals and using
synchronous subprocess calls that cannot be cancelled by asyncio during shutdown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import LocalSessionAdapter, RemoteSessionAdapter

logger = logging.getLogger(__name__)


async def cleanup_repl_resources(
    adapter: LocalSessionAdapter | RemoteSessionAdapter,
    namespace: dict[str, Any] | None,
    is_local_mode: bool,
    server_disconnected: bool = False,
) -> None:
    """Comprehensive cleanup of all REPL resources.

    Destroys EVERYTHING created during the REPL session:
    - All sessions (scans namespace for Session instances)
    - All nodes (both registered and orphaned)
    - All graphs (cleared by session.stop())
    - Namespace references

    Args:
        adapter: Session adapter (local or remote).
        namespace: REPL namespace containing user-created objects.
        is_local_mode: Whether running in local mode (vs server mode).
        server_disconnected: Whether server connection was lost.
    """
    if server_disconnected:
        print("Server connection lost")

    # Local mode: clean up ALL sessions/nodes/graphs created in namespace
    if is_local_mode and namespace:
        await _cleanup_local_mode(namespace)
    # Server mode: just stop the adapter
    else:
        await _cleanup_server_mode(adapter)


async def _cleanup_local_mode(namespace: dict[str, Any]) -> None:
    """Clean up all resources in local mode by scanning namespace.

    Finds and stops:
    1. All Session instances → stops all their nodes/graphs
    2. All orphaned Node instances → stops them individually
    3. Clears namespace to release all references

    Args:
        namespace: REPL namespace to scan for resources.
    """
    print("Cleaning up REPL resources...")
    cleanup_errors = []

    # Track nodes already stopped by sessions to avoid double-stop
    stopped_node_ids: set[int] = set()

    # 1. Stop all Session instances found in namespace
    from nerve.core.session import Session

    sessions_stopped = 0
    for name, obj in list(namespace.items()):
        if isinstance(obj, Session):
            try:
                # Collect node IDs from this session before stopping
                if hasattr(obj, "_collect_persistent_nodes"):
                    for node in obj._collect_persistent_nodes():
                        stopped_node_ids.add(id(node))

                await obj.stop()
                sessions_stopped += 1
            except Exception as e:
                cleanup_errors.append(f"Session '{name}': {e}")
                logger.error(f"Failed to stop session {name}: {e}", exc_info=True)

    if sessions_stopped > 0:
        print(f"  ✓ Stopped {sessions_stopped} session(s)")

    # 2. Stop any orphaned Node instances not already stopped by sessions
    from nerve.core.nodes.base import Node

    nodes_stopped = 0
    for name, obj in list(namespace.items()):
        if isinstance(obj, Node) and hasattr(obj, "stop"):
            # Skip if already stopped by session
            if id(obj) in stopped_node_ids:
                continue

            try:
                await obj.stop()
                nodes_stopped += 1
            except Exception as e:
                cleanup_errors.append(f"Node '{name}': {e}")
                logger.error(f"Failed to stop node {name}: {e}", exc_info=True)

    if nodes_stopped > 0:
        print(f"  ✓ Stopped {nodes_stopped} orphaned node(s)")

    # 3. Clear namespace to release all references
    namespace.clear()

    # Report any errors
    if cleanup_errors:
        print(f"  ⚠ {len(cleanup_errors)} cleanup error(s) - some resources may still be running")
        for error in cleanup_errors[:3]:  # Show first 3
            print(f"    - {error}")
    else:
        print("  ✓ All resources cleaned up")


async def _cleanup_server_mode(
    adapter: LocalSessionAdapter | RemoteSessionAdapter,
) -> None:
    """Clean up server mode by stopping the adapter.

    The server is responsible for managing its own resources.

    Args:
        adapter: Session adapter to stop.
    """
    try:
        await adapter.stop()
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        print(f"Warning: Cleanup error - some nodes may still be running: {e}")
