"""PythonExecutor - Executes Python code in isolated namespaces.

SECURITY BOUNDARY:
- Isolates arbitrary code execution
- Per-session namespace isolation
- Clear audit point for security reviews
- Future: sandboxing, resource limits, permissions
"""

from __future__ import annotations

import asyncio
import io
import json
import traceback
from code import compile_command
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.session import Session
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class PythonExecutor:
    """Executes Python code in isolated namespaces.

    SECURITY BOUNDARY:
    - Isolates arbitrary code execution
    - Per-session namespace isolation
    - Clear audit point for security reviews
    - Future: sandboxing, resource limits, permissions

    State: _namespaces (session → namespace dict)
    """

    validation: ValidationHelpers
    session_registry: SessionRegistry

    # Owned state: per-session namespaces
    _namespaces: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def execute_python(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute Python code in session namespace (command interface).

        This is the command handler entry point. Delegates to execute().

        Args:
            params: Must contain "code" (Python code string).
                    May contain "session_id" (uses default if not provided).

        Returns:
            dict with "output" (captured stdout/result) and "error" (if any).
        """
        session = self.session_registry.get_session(params.get("session_id"))
        code = params.get("code", "")
        return await self.execute(code, session)

    async def execute(self, code: str, session: Session) -> dict[str, Any]:
        """Execute Python code in session namespace (core logic).

        Args:
            code: Python code string to execute.
            session: Session for namespace isolation.

        Returns:
            {"output": str, "error": str|None}
        """
        if not code.strip():
            return {"output": "", "error": None}

        namespace = self._get_or_create_namespace(session)

        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # Handle async code (contains await)
                if "await " in code:
                    await self._execute_async(code, namespace)
                else:
                    result = self._execute_sync(code, namespace)
                    if result is not None:
                        return result

            # Get captured output
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()

            if error_output:
                output = error_output if not output else output + "\n" + error_output

            return {
                "output": output,
                "error": None,
            }

        except SyntaxError as e:
            return {
                "output": "",
                "error": f"SyntaxError: {e}",
            }
        except Exception as e:
            return {
                "output": "",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            }

    def _get_or_create_namespace(self, session: Session) -> dict[str, Any]:
        """Get or initialize namespace for session.

        Args:
            session: Session for namespace lookup.

        Returns:
            Namespace dict for the session.
        """
        session_id = session.name
        if session_id not in self._namespaces:
            self._namespaces[session_id] = self._create_default_namespace(session)
        return self._namespaces[session_id]

    def _create_default_namespace(self, session: Session) -> dict[str, Any]:
        """Create default namespace with nerve imports.

        Args:
            session: Session to include in namespace.

        Returns:
            Namespace dict with useful imports and session reference.
        """
        from nerve.core import ParserType
        from nerve.core.nodes import (
            ExecutionContext,
            FunctionNode,
        )
        from nerve.core.nodes.bash import BashNode
        from nerve.core.nodes.graph import Graph
        from nerve.core.nodes.llm import OpenRouterNode
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )
        from nerve.core.session import Session as SessionClass

        return {
            "asyncio": asyncio,
            # Node classes (use with session parameter)
            "BashNode": BashNode,
            "FunctionNode": FunctionNode,
            "Graph": Graph,
            "OpenRouterNode": OpenRouterNode,
            "PTYNode": PTYNode,
            "WezTermNode": WezTermNode,
            "ClaudeWezTermNode": ClaudeWezTermNode,
            # Other useful classes
            "ExecutionContext": ExecutionContext,
            "Session": SessionClass,
            "ParserType": ParserType,
            # Pre-configured instances
            "session": session,  # The actual session
            "context": ExecutionContext(session=session),  # Pre-configured context
        }

    async def _execute_async(self, code: str, namespace: dict[str, Any]) -> None:
        """Execute async code (contains 'await').

        Args:
            code: Python code string containing await.
            namespace: Namespace for execution.
        """
        # Wrap in async function that returns local variables
        async_code = "async def __repl_async__():\n"
        for line in code.split("\n"):
            async_code += f"    {line}\n"
        async_code += "    return locals()\n"

        # Compile and execute the function definition
        exec(compile(async_code, "<repl>", "exec"), namespace)

        # Call the async function and get its local variables
        func_locals = await namespace["__repl_async__"]()

        # Update namespace with variables from the function
        # (skip private variables and built-in names)
        for key, value in func_locals.items():
            if not key.startswith("_"):
                namespace[key] = value
                # Print value if it's a standalone expression result
                if key == "result" and value is not None:
                    print(self._pretty_print_value(value))

    def _execute_sync(self, code: str, namespace: dict[str, Any]) -> dict[str, Any] | None:
        """Execute synchronous code.

        Args:
            code: Python code string.
            namespace: Namespace for execution.

        Returns:
            Error dict if incomplete code, None otherwise.
        """
        # Try to compile as a complete statement
        code_obj = compile_command(code, "<repl>", "single")

        if code_obj is None:
            # Incomplete code
            return {
                "output": "",
                "error": "SyntaxError: unexpected EOF while parsing (incomplete code)",
            }

        # Execute synchronous code
        exec(code_obj, namespace)
        return None

    @staticmethod
    def _pretty_print_value(value: Any) -> str:
        """Pretty-print a value for REPL display.

        Handles special cases like ParsedResponse objects and converts them to JSON.

        Args:
            value: Value to pretty-print.

        Returns:
            Formatted string representation.
        """

        def convert_to_serializable(obj: Any) -> Any:
            if is_dataclass(obj) and not isinstance(obj, type):
                return asdict(obj)
            elif isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_serializable(item) for item in obj]
            else:
                return obj

        try:
            serializable = convert_to_serializable(value)
            return json.dumps(serializable, indent=2)
        except (TypeError, ValueError):
            # Fall back to repr if JSON serialization fails
            return repr(value)
