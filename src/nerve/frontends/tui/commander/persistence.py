"""Commander session persistence - save/load session state.

Provides :export and :import functionality to save and restore:
- Timeline blocks (inputs/outputs)
- Entity definitions (nodes, graphs, workflows)

Limitations (best effort):
- Workflows can't be serialized (Python functions)
- Graph input_fn lambdas can't be serialized
- Node conversation history is not preserved
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from nerve.frontends.tui.commander.blocks import Timeline

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.commander import Commander


async def save_session_state(commander: Commander) -> dict[str, Any]:
    """Collect session state for export.

    Args:
        commander: Commander instance to export from.

    Returns:
        Dict ready for JSON serialization containing:
        - version: Format version
        - session_name: Session identifier
        - saved_at: ISO timestamp
        - entities: {nodes, graphs, workflows}
        - blocks: Timeline blocks
    """
    nodes = await _collect_node_info(commander)
    graphs = await _collect_graph_info(commander)
    workflows = await _collect_workflow_info(commander)

    return {
        "version": "1.0",
        "session_name": commander.session_name,
        "saved_at": datetime.now().isoformat(),
        "entities": {
            "nodes": nodes,
            "graphs": graphs,
            "workflows": workflows,
        },
        "blocks": commander.timeline.to_dict()["blocks"],
    }


async def restore_session_state(commander: Commander, data: dict[str, Any]) -> dict[str, Any]:
    """Restore session state from saved data.

    Args:
        commander: Commander instance to restore into.
        data: Saved state from save_session_state().

    Returns:
        Dict with restore statistics:
        - nodes_created: Number of nodes created
        - graphs_created: Number of graphs created
        - workflows_skipped: Number of workflows skipped (can't restore)
        - blocks_restored: Number of timeline blocks restored
        - errors: List of error messages
    """
    nodes_created = 0
    graphs_created = 0
    errors: list[str] = []

    entities = data.get("entities", {})

    # Generate Python code to recreate entities
    code = _generate_restore_code(entities)

    if code.strip() and commander._adapter is not None:
        # Execute on server
        output, error = await commander._adapter.execute_python(code, {})
        if error:
            errors.append(f"Entity restore error: {error}")
        else:
            # Count created entities from output
            if output:
                for line in output.split("\n"):
                    if "Created node:" in line:
                        nodes_created += 1
                    elif "Created graph:" in line:
                        graphs_created += 1

    # Count skipped workflows
    workflows_skipped = len(entities.get("workflows", []))

    # Sync entities to pick up new ones
    await commander._sync_entities()

    # Restore timeline blocks - merge into existing timeline to preserve executor reference
    blocks_restored = 0
    blocks_data = data.get("blocks", [])
    if blocks_data:
        restored = Timeline.from_dict({"blocks": blocks_data})
        # Update existing timeline's blocks and counter, preserving the object reference
        commander.timeline.blocks = restored.blocks
        commander.timeline._next_number = restored._next_number
        blocks_restored = len(commander.timeline.blocks)

    return {
        "nodes_created": nodes_created,
        "graphs_created": graphs_created,
        "workflows_skipped": workflows_skipped,
        "blocks_restored": blocks_restored,
        "errors": errors,
    }


async def _collect_node_info(commander: Commander) -> list[dict[str, Any]]:
    """Collect node information for export.

    Extracts creation params from node metadata (from to_info()).
    Terminal nodes include command, cwd, pane_id in their metadata.
    """
    nodes = []

    for entity in commander.entities.values():
        if entity.type != "node":
            continue

        # Skip identity node (auto-created)
        if entity.id == "identity":
            continue

        # Metadata comes directly from node.to_info() which includes command, pane_id, etc.
        metadata = entity.metadata

        node_info = {
            "id": entity.id,
            "backend": _infer_backend(entity.node_type),
            "command": metadata.get("command"),
            "cwd": metadata.get("cwd"),
            "pane_id": metadata.get("pane_id"),
        }

        # Only include if we have enough info to recreate
        if node_info["command"] or node_info["backend"] in ("bash", "function"):
            nodes.append(node_info)

    return nodes


def _infer_backend(node_type: str) -> str:
    """Infer backend from node type string."""
    node_type_lower = node_type.lower()
    if "wezterm" in node_type_lower:
        if "claude" in node_type_lower:
            return "claude-wezterm"
        return "wezterm"
    if "bash" in node_type_lower:
        return "bash"
    if "pty" in node_type_lower:
        return "pty"
    return "pty"


async def _collect_graph_info(commander: Commander) -> list[dict[str, Any]]:
    """Collect graph information for export.

    Note: Graphs with lambda input_fn can't be fully serialized.
    Only static inputs and template strings are preserved.
    """
    graphs = []

    for entity in commander.entities.values():
        if entity.type != "graph":
            continue

        # For now, just save basic info
        # Full graph serialization would require server-side support
        graph_info = {
            "id": entity.id,
            "steps": [],  # Would need server query to get step details
        }
        graphs.append(graph_info)

    return graphs


async def _collect_workflow_info(commander: Commander) -> list[dict[str, Any]]:
    """Collect workflow information for export.

    Note: Workflows are Python functions and can't be serialized.
    Only id and description are saved.
    """
    workflows = []

    for entity in commander.entities.values():
        if entity.type != "workflow":
            continue

        workflow_info = {
            "id": entity.id,
            "description": entity.metadata.get("description", ""),
            "source_file": None,  # Would need tracking at load time
        }
        workflows.append(workflow_info)

    return workflows


def _generate_restore_code(entities: dict[str, Any]) -> str:
    """Generate Python code to recreate entities.

    Args:
        entities: Dict with nodes, graphs, workflows lists.

    Returns:
        Python code string to execute on server.
    """
    lines = []

    # Import statements
    lines.append("from nerve.core.nodes.terminal import PTYNode, WezTermNode, ClaudeWezTermNode")
    lines.append("from nerve.core.nodes.bash import BashNode")
    lines.append("from nerve.core.nodes.graph import Graph")
    lines.append("")

    # Recreate nodes
    for node in entities.get("nodes", []):
        node_id = node["id"]
        backend = node.get("backend", "pty")
        command = node.get("command")
        cwd = node.get("cwd")

        if backend == "bash":
            # BashNode is sync - use repr() for safe string escaping
            cwd_arg = f", cwd={repr(cwd)}" if cwd else ""
            lines.append(f"BashNode(id={repr(node_id)}, session=session{cwd_arg})")
            lines.append(f"print({repr(f'Created node: {node_id}')})")
        elif backend in ("pty", "wezterm", "claude-wezterm"):
            if not command:
                lines.append(f"# Skipping node {repr(node_id)} - no command available")
                continue

            # Determine node class
            if backend == "claude-wezterm":
                node_class = "ClaudeWezTermNode"
            elif backend == "wezterm":
                node_class = "WezTermNode"
            else:
                node_class = "PTYNode"

            # Build create call - use repr() for safe string escaping
            args = [f"id={repr(node_id)}", "session=session", f"command={repr(command)}"]
            if cwd:
                args.append(f"cwd={repr(cwd)}")

            lines.append(f"await {node_class}.create({', '.join(args)})")
            lines.append(f"print({repr(f'Created node: {node_id}')})")

    # Recreate graphs (basic - no steps for now)
    for graph in entities.get("graphs", []):
        graph_id = graph["id"]
        lines.append("")
        lines.append(f"Graph(id={repr(graph_id)}, session=session)")
        lines.append(f"print({repr(f'Created graph: {graph_id}')})")

    # Workflows can't be recreated - just comment
    workflows = entities.get("workflows", [])
    if workflows:
        lines.append("")
        lines.append("# Workflows cannot be auto-restored (Python functions)")
        lines.append("# Use :load <workflow.py> to reload workflow definitions")
        for wf in workflows:
            lines.append(f"# - {wf['id']}: {wf.get('description', '')}")

    return "\n".join(lines)
