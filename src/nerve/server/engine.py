"""NerveEngine - Wraps core with event emission.

The engine uses core primitives (Session, DAG, etc.) and emits
events for state changes. It's the bridge between pure core
and the event-driven server world.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nerve.core import DAG, CLIType, Session, SessionManager, Task
from nerve.server.protocols import (
    Command,
    CommandResult,
    CommandType,
    Event,
    EventSink,
    EventType,
)


@dataclass
class NerveEngine:
    """Main nerve engine - wraps core with event emission.

    The engine:
    - Uses core.Session, core.DAG, etc. for actual work
    - Emits events through EventSink for state changes
    - Handles commands from transport layer

    This layer knows about core, but not about:
    - Specific transports (that's the transport layer)
    - Frontends (that's the frontends layer)

    Example:
        >>> sink = MyEventSink()
        >>> engine = NerveEngine(event_sink=sink)
        >>>
        >>> result = await engine.execute(Command(
        ...     type=CommandType.CREATE_SESSION,
        ...     params={"cli_type": "claude", "cwd": "/project"},
        ... ))
        >>>
        >>> session_id = result.data["session_id"]
    """

    event_sink: EventSink
    _session_manager: SessionManager = field(default_factory=SessionManager)
    _running_dags: dict[str, asyncio.Task] = field(default_factory=dict)

    async def execute(self, command: Command) -> CommandResult:
        """Execute a command.

        This is the single entry point for all operations.

        Args:
            command: The command to execute.

        Returns:
            CommandResult with success/failure and data.
        """
        handlers = {
            CommandType.CREATE_SESSION: self._create_session,
            CommandType.CLOSE_SESSION: self._close_session,
            CommandType.LIST_SESSIONS: self._list_sessions,
            CommandType.GET_SESSION: self._get_session,
            CommandType.SEND_INPUT: self._send_input,
            CommandType.SEND_INTERRUPT: self._send_interrupt,
            CommandType.GET_BUFFER: self._get_buffer,
            CommandType.EXECUTE_DAG: self._execute_dag,
            CommandType.CANCEL_DAG: self._cancel_dag,
        }

        handler = handlers.get(command.type)
        if not handler:
            return CommandResult(
                success=False,
                error=f"Unknown command type: {command.type}",
                request_id=command.request_id,
            )

        try:
            data = await handler(command.params)
            return CommandResult(
                success=True,
                data=data,
                request_id=command.request_id,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )

    async def _emit(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> None:
        """Emit an event through the sink."""
        event = Event(
            type=event_type,
            data=data or {},
            session_id=session_id,
        )
        await self.event_sink.emit(event)

    # =========================================================================
    # Session Commands
    # =========================================================================

    async def _create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new session."""
        cli_type = CLIType(params.get("cli_type", "claude"))
        cwd = params.get("cwd")
        session_id = params.get("session_id")

        session = await self._session_manager.create(
            cli_type=cli_type,
            cwd=cwd,
            session_id=session_id,
        )

        await self._emit(
            EventType.SESSION_CREATED,
            data={"cli_type": cli_type.value, "cwd": cwd},
            session_id=session.id,
        )

        # Start monitoring the session
        asyncio.create_task(self._monitor_session(session))

        return {"session_id": session.id}

    async def _close_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Close a session."""
        session_id = params["session_id"]

        closed = await self._session_manager.close(session_id)
        if not closed:
            raise ValueError(f"Session not found: {session_id}")

        await self._emit(EventType.SESSION_CLOSED, session_id=session_id)

        return {"closed": True}

    async def _list_sessions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all sessions."""
        session_ids = self._session_manager.list()
        return {"sessions": session_ids}

    async def _get_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get session info."""
        session_id = params["session_id"]
        session = self._session_manager.get(session_id)

        if not session:
            raise ValueError(f"Session not found: {session_id}")

        return {
            "session_id": session.id,
            "cli_type": session.cli_type.value,
            "state": session.state.name,
        }

    # =========================================================================
    # Interaction Commands
    # =========================================================================

    async def _send_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send input to a session."""
        session_id = params["session_id"]
        text = params["text"]
        stream = params.get("stream", False)

        session = self._session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        await self._emit(EventType.SESSION_BUSY, session_id=session_id)

        if stream:
            # Stream output chunks as events
            async for chunk in session.send_stream(text):
                await self._emit(
                    EventType.OUTPUT_CHUNK,
                    data={"chunk": chunk},
                    session_id=session_id,
                )

            # Parse final response
            response = session.parser.parse(session.buffer)
        else:
            # Wait for complete response
            response = await session.send(text)

        await self._emit(
            EventType.OUTPUT_PARSED,
            data={
                "raw": response.raw,
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in response.sections
                ],
                "tokens": response.tokens,
            },
            session_id=session_id,
        )

        await self._emit(EventType.SESSION_READY, session_id=session_id)

        return {"response": response.raw}

    async def _send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt to a session."""
        session_id = params["session_id"]

        session = self._session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        await session.interrupt()

        return {"interrupted": True}

    async def _get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get session buffer."""
        session_id = params["session_id"]
        lines = params.get("lines")

        session = self._session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if lines:
            buffer = session.pty.read_tail(lines)
        else:
            buffer = session.buffer

        return {"buffer": buffer}

    # =========================================================================
    # DAG Commands
    # =========================================================================

    async def _execute_dag(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a DAG."""
        dag_id = params.get("dag_id", "dag_0")
        tasks_data = params["tasks"]

        # Build DAG from task definitions
        dag = DAG()

        for task_data in tasks_data:
            task_id = task_data["id"]
            session_id = task_data.get("session_id")
            text = task_data.get("text", "")
            depends_on = task_data.get("depends_on", [])

            async def make_executor(sid: str, txt: str):
                async def execute(ctx: dict[str, Any]) -> Any:
                    # Substitute variables
                    formatted = txt.format(**ctx)
                    session = self._session_manager.get(sid)
                    if not session:
                        raise ValueError(f"Session not found: {sid}")
                    response = await session.send(formatted)
                    return response.raw

                return execute

            dag.add_task(
                Task(
                    id=task_id,
                    execute=await make_executor(session_id, text),
                    depends_on=depends_on,
                )
            )

        await self._emit(EventType.DAG_STARTED, data={"dag_id": dag_id})

        # Execute with event callbacks
        results = await dag.run(
            on_task_start=lambda tid: asyncio.create_task(
                self._emit(EventType.TASK_STARTED, data={"task_id": tid})
            ),
            on_task_complete=lambda r: asyncio.create_task(
                self._emit(
                    EventType.TASK_COMPLETED
                    if r.status.name == "COMPLETED"
                    else EventType.TASK_FAILED,
                    data={"task_id": r.task_id, "output": str(r.output)[:500]},
                )
            ),
        )

        await self._emit(
            EventType.DAG_COMPLETED,
            data={"dag_id": dag_id, "task_count": len(results)},
        )

        return {
            "dag_id": dag_id,
            "results": {
                tid: {"status": r.status.name, "output": str(r.output)[:500]}
                for tid, r in results.items()
            },
        }

    async def _cancel_dag(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running DAG."""
        dag_id = params["dag_id"]

        task = self._running_dags.get(dag_id)
        if task:
            task.cancel()
            del self._running_dags[dag_id]
            return {"cancelled": True}

        return {"cancelled": False, "error": "DAG not found"}

    # =========================================================================
    # Internal
    # =========================================================================

    async def _monitor_session(self, session: Session) -> None:
        """Monitor session for state changes.

        This runs in the background and emits events when
        the session state changes.
        """
        from nerve.core.types import SessionState

        last_state = session.state

        while session.state != SessionState.STOPPED:
            await asyncio.sleep(0.5)

            if session.state != last_state:
                if session.state == SessionState.READY:
                    await self._emit(EventType.SESSION_READY, session_id=session.id)
                elif session.state == SessionState.BUSY:
                    await self._emit(EventType.SESSION_BUSY, session_id=session.id)

                last_state = session.state
