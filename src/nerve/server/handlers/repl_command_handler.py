"""ReplCommandHandler - Handles REPL meta-commands.

This handler processes REPL introspection commands:
- show: Display graph structure
- dry: Show execution order
- validate: Validate graph
- list: List nodes or graphs
- read: Read node buffer
"""

from __future__ import annotations

import io
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.session import Session
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class ReplCommandHandler:
    """Handles REPL meta-commands: show, dry, validate, list, read.

    Domain: REPL introspection and graph visualization
    Distinction: Meta-commands vs Python execution

    State: None (uses session registry for access)
    """

    validation: ValidationHelpers
    session_registry: SessionRegistry

    async def execute_repl_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute REPL command (command interface).

        Args:
            params: Must contain "command" (command name like "show", "dry").
                    May contain "args" (list of command arguments).
                    May contain "session_id" (uses default if not provided).

        Returns:
            dict with "output" (formatted command output) and "error" (if any).
        """
        session = self.session_registry.get_session(params.get("session_id"))
        command = params.get("command", "")
        args = params.get("args", [])

        handlers = {
            "show": self._show,
            "dry": self._dry,
            "validate": self._validate,
            "list": self._list,
            "read": self._read,
        }

        handler = handlers.get(command)
        if not handler:
            return {"output": "", "error": f"Unknown REPL command: {command}"}

        try:
            output = await handler(session, args)
            return {"output": output, "error": None}
        except Exception as e:
            return {
                "output": "",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            }

    async def _show(self, session: Session, args: list[str]) -> str:
        """Show graph structure.

        Args:
            session: Session to query.
            args: [graph_id] - graph to show.

        Returns:
            Formatted graph structure.
        """
        output_buffer = io.StringIO()

        graph_id = args[0] if args else None
        graph = session.get_graph(graph_id) if graph_id else None

        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        if not graph.list_steps():
            output_buffer.write("No steps defined\n")
        else:
            output_buffer.write("\nGraph Structure:\n")
            output_buffer.write("-" * 40 + "\n")
            for step_id in graph.list_steps():
                step = graph.get_step(step_id)
                deps = step.depends_on if step else []
                output_buffer.write(f"  {step_id}\n")
                if deps:
                    output_buffer.write(f"    depends on: {', '.join(deps)}\n")
            output_buffer.write("-" * 40 + "\n")

        return output_buffer.getvalue()

    async def _dry(self, session: Session, args: list[str]) -> str:
        """Show dry-run execution order.

        Args:
            session: Session to query.
            args: [graph_id] - graph to dry-run.

        Returns:
            Execution order listing.
        """
        output_buffer = io.StringIO()

        graph_id = args[0] if args else None
        graph = session.get_graph(graph_id) if graph_id else None

        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        order = graph.execution_order()
        output_buffer.write("\nExecution order:\n")
        for i, step_id in enumerate(order, 1):
            output_buffer.write(f"  [{i}] {step_id}\n")

        return output_buffer.getvalue()

    async def _validate(self, session: Session, args: list[str]) -> str:
        """Validate graph.

        Args:
            session: Session to query.
            args: [graph_id] - graph to validate.

        Returns:
            Validation result.
        """
        output_buffer = io.StringIO()

        graph_id = args[0] if args else None
        graph = session.get_graph(graph_id) if graph_id else None

        if not graph:
            raise ValueError(f"Graph not found: {graph_id}")

        errors = graph.validate()
        if errors:
            output_buffer.write("Validation FAILED:\n")
            for err in errors:
                output_buffer.write(f"  - {err}\n")
        else:
            output_buffer.write("Validation PASSED\n")

        return output_buffer.getvalue()

    async def _list(self, session: Session, args: list[str]) -> str:
        """List nodes or graphs.

        Args:
            session: Session to query.
            args: [what] - "nodes" or "graphs" (default: nodes).

        Returns:
            List of items.
        """
        output_buffer = io.StringIO()

        what = args[0] if args else "nodes"

        if what == "graphs":
            graphs = session.list_graphs()
            if graphs:
                output_buffer.write("\nGraphs:\n")
                for g in graphs:
                    output_buffer.write(f"  - {g}\n")
            else:
                output_buffer.write("No graphs defined\n")
        else:  # nodes
            if session.nodes:
                output_buffer.write("\nNodes:\n")
                for name, node in session.nodes.items():
                    if hasattr(node, "state"):
                        info = node.state.name
                    else:
                        info = type(node).__name__
                    output_buffer.write(f"  {name}: {info}\n")
            else:
                output_buffer.write("No nodes defined\n")

        return output_buffer.getvalue()

    async def _read(self, session: Session, args: list[str]) -> str:
        """Read node buffer.

        Args:
            session: Session to query.
            args: [node_name] - node to read.

        Returns:
            Node buffer content.
        """
        if not args:
            raise ValueError("Usage: read <node>")

        node_name = args[0]
        read_node = session.get_node(node_name)
        if not read_node:
            raise ValueError(f"Node not found: {node_name}")

        if hasattr(read_node, "read"):
            buffer_content = await read_node.read()
            return str(buffer_content)
        else:
            raise ValueError("Node does not support read")
