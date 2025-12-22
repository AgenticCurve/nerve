"""NerveEngine - Wraps core with event emission.

The engine uses core primitives (Channels, DAG, etc.) and emits
events for state changes. It's the bridge between pure core
and the event-driven server world.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nerve.core import DAG, ChannelManager, Task
from nerve.core.channels import ChannelState
from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel
from nerve.core.channels.history import HistoryReader
from nerve.core.channels.pty import PTYChannel
from nerve.core.channels.wezterm import WezTermChannel
from nerve.core.parsers import get_parser
from nerve.core.types import ParserType
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
    - Uses core.ChannelManager, core.DAG, etc. for actual work
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
        ...     type=CommandType.CREATE_CHANNEL,
        ...     params={"channel_id": "my-claude", "command": "claude"},
        ... ))
        >>>
        >>> channel_id = result.data["channel_id"]  # "my-claude"
    """

    event_sink: EventSink
    _server_name: str = field(default="default")
    _channel_manager: ChannelManager | None = field(default=None, repr=False)
    _running_dags: dict[str, asyncio.Task] = field(default_factory=dict)
    _shutdown_requested: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Initialize channel manager with server name."""
        if self._channel_manager is None:
            self._channel_manager = ChannelManager(_server_name=self._server_name)

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._shutdown_requested

    async def execute(self, command: Command) -> CommandResult:
        """Execute a command.

        This is the single entry point for all operations.

        Args:
            command: The command to execute.

        Returns:
            CommandResult with success/failure and data.
        """
        handlers = {
            # Channel commands
            CommandType.CREATE_CHANNEL: self._create_channel,
            CommandType.CLOSE_CHANNEL: self._close_channel,
            CommandType.LIST_CHANNELS: self._list_channels,
            CommandType.GET_CHANNEL: self._get_channel,
            CommandType.RUN_COMMAND: self._run_command,
            CommandType.SEND_INPUT: self._send_input,
            CommandType.SEND_INTERRUPT: self._send_interrupt,
            CommandType.WRITE_DATA: self._write_data,
            CommandType.GET_BUFFER: self._get_buffer,
            CommandType.GET_HISTORY: self._get_history,
            # DAG commands
            CommandType.EXECUTE_DAG: self._execute_dag,
            CommandType.CANCEL_DAG: self._cancel_dag,
            # Server control
            CommandType.SHUTDOWN: self._shutdown,
            CommandType.PING: self._ping,
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
        channel_id: str | None = None,
    ) -> None:
        """Emit an event through the sink."""
        event = Event(
            type=event_type,
            data=data or {},
            channel_id=channel_id,
        )
        await self.event_sink.emit(event)

    # =========================================================================
    # Channel Commands
    # =========================================================================

    async def _create_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new channel.

        Requires channel_id (name) in params. Names must be unique.
        """
        channel_id = params.get("channel_id")
        if not channel_id:
            raise ValueError("Channel name is required")

        command = params.get("command")  # e.g., "claude" or ["claude", "--flag"]
        cwd = params.get("cwd")
        backend = params.get("backend", "pty")  # "pty" or "wezterm"
        pane_id = params.get("pane_id")  # For attaching to existing WezTerm pane
        history = params.get("history", True)  # Enable history by default

        # ChannelManager.create_terminal enforces uniqueness
        channel = await self._channel_manager.create_terminal(
            channel_id=channel_id,
            command=command,
            backend=backend,
            cwd=cwd,
            pane_id=pane_id,
            history=history,
        )

        await self._emit(
            EventType.CHANNEL_CREATED,
            data={
                "command": command,
                "cwd": cwd,
                "backend": backend,
                "pane_id": getattr(channel, "pane_id", None),
            },
            channel_id=channel.id,
        )

        # Start monitoring the channel
        asyncio.create_task(self._monitor_channel(channel))

        return {"channel_id": channel.id}

    async def _close_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Close a channel."""
        channel_id = params.get("channel_id")

        closed = await self._channel_manager.close(channel_id)
        if not closed:
            raise ValueError(f"Channel not found: {channel_id}")

        await self._emit(EventType.CHANNEL_CLOSED, channel_id=channel_id)

        return {"closed": True}

    async def _list_channels(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all channels."""
        channel_ids = self._channel_manager.list()
        channels_info = []
        for cid in channel_ids:
            channel = self._channel_manager.get(cid)
            if channel:
                # Use to_info() to get full channel metadata including last_input
                if hasattr(channel, "to_info"):
                    channel_info = channel.to_info()
                    info = {
                        "id": cid,
                        "type": channel_info.channel_type.value,
                        "state": channel_info.state.name,
                        **channel_info.metadata,
                    }
                else:
                    # Fallback for channels without to_info
                    info = {
                        "id": cid,
                        "type": channel.channel_type.value,
                        "state": channel.state.name,
                    }
                    if hasattr(channel, "backend_type"):
                        bt = channel.backend_type
                        info["backend"] = bt.value if hasattr(bt, "value") else bt
                    if hasattr(channel, "command"):
                        info["command"] = channel.command
                    if hasattr(channel, "pane_id"):
                        info["pane_id"] = channel.pane_id
                channels_info.append(info)

        return {
            "channels": channel_ids,
            "channels_info": channels_info,
        }

    async def _get_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get channel info."""
        channel_id = params.get("channel_id")
        channel = self._channel_manager.get(channel_id)

        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        result = {
            "channel_id": channel.id,
            "type": channel.channel_type.value,
            "state": channel.state.name,
        }
        if hasattr(channel, "backend_type"):
            result["backend"] = channel.backend_type.value
        if hasattr(channel, "pane_id"):
            result["pane_id"] = channel.pane_id

        return result

    # =========================================================================
    # Interaction Commands
    # =========================================================================

    async def _run_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run a command in a channel (fire and forget).

        This starts a program that takes over the terminal (like claude, python, etc.)
        without waiting for a response. Use SEND_INPUT to interact with it after.
        """
        channel_id = params.get("channel_id")
        command = params["command"]

        channel = self._channel_manager.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        await channel.run(command)

        return {"started": True, "command": command}

    async def _send_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send input to a channel."""
        channel_id = params.get("channel_id")
        text = params["text"]
        parser_str = params.get("parser")  # None means use channel's default
        stream = params.get("stream", False)
        submit = params.get("submit")  # Custom submit sequence (optional)

        channel = self._channel_manager.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        # Convert parser string to ParserType, or None to use channel's default
        parser_type = ParserType(parser_str) if parser_str else None

        await self._emit(EventType.CHANNEL_BUSY, channel_id=channel_id)

        if stream:
            # Stream output chunks as events
            actual_parser = parser_type or ParserType.NONE
            async for chunk in channel.send_stream(text, parser=actual_parser):
                await self._emit(
                    EventType.OUTPUT_CHUNK,
                    data={"chunk": chunk},
                    channel_id=channel_id,
                )

            # Parse final response
            parser = get_parser(actual_parser)
            response = parser.parse(channel.buffer)
        else:
            # Wait for complete response (channel uses its default parser if None)
            response = await channel.send(text, parser=parser_type, submit=submit)

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
            channel_id=channel_id,
        )

        await self._emit(EventType.CHANNEL_READY, channel_id=channel_id)

        return {
            "response": {
                "raw": response.raw,
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in response.sections
                ],
                "tokens": response.tokens,
                "is_complete": response.is_complete,
                "is_ready": response.is_ready,
            }
        }

    async def _send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt to a channel."""
        channel_id = params.get("channel_id")

        channel = self._channel_manager.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        await channel.interrupt()

        return {"interrupted": True}

    async def _write_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write raw data to a channel (no waiting)."""
        channel_id = params.get("channel_id")
        data = params["data"]

        channel = self._channel_manager.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        await channel.write(data)

        return {"written": len(data)}

    async def _get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get channel buffer."""
        channel_id = params.get("channel_id")
        lines = params.get("lines")

        channel = self._channel_manager.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        if lines:
            buffer = channel.read_tail(lines)
        else:
            buffer = await channel.read()

        return {"buffer": buffer}

    async def _get_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get channel history.

        Reads the JSONL history file for a channel.

        Parameters:
            channel_id: The channel ID (required)
            server_name: Server name (optional, defaults to engine's server name)
            last: Limit to last N entries (optional)
            op: Filter by operation type (optional)
            inputs_only: Filter to input operations only (optional)

        Returns:
            Dict with channel_id, server_name, entries, and total count.
        """
        channel_id = params.get("channel_id")
        if not channel_id:
            raise ValueError("channel_id is required")

        server_name = params.get("server_name", self._server_name)
        last = params.get("last")
        op = params.get("op")
        inputs_only = params.get("inputs_only", False)

        try:
            reader = HistoryReader.create(
                channel_id=channel_id,
                server_name=server_name,
                base_dir=self._channel_manager._history_base_dir,
            )

            # Apply filters
            if inputs_only:
                entries = reader.get_inputs_only()
            elif op:
                entries = reader.get_by_op(op)
            else:
                entries = reader.get_all()

            # Apply limit if specified
            if last is not None and last < len(entries):
                entries = entries[-last:]

            return {
                "channel_id": channel_id,
                "server_name": server_name,
                "entries": entries,
                "total": len(entries),
            }

        except FileNotFoundError:
            # Fail soft - return empty results with note
            return {
                "channel_id": channel_id,
                "server_name": server_name,
                "entries": [],
                "total": 0,
                "note": "No history found for this channel",
            }

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
            channel_id = task_data.get("channel_id")
            text = task_data.get("text", "")
            parser_str = task_data.get("parser", "none")
            depends_on = task_data.get("depends_on", [])

            async def make_executor(cid: str, txt: str, parser: str):
                async def execute(ctx: dict[str, Any]) -> Any:
                    # Substitute variables
                    formatted = txt.format(**ctx)
                    channel = self._channel_manager.get(cid)
                    if not channel:
                        raise ValueError(f"Channel not found: {cid}")
                    response = await channel.send(formatted, parser=ParserType(parser))
                    return response.raw

                return execute

            dag.add_task(
                Task(
                    id=task_id,
                    execute=await make_executor(channel_id, text, parser_str),
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
    # Server Control Commands
    # =========================================================================

    async def _shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        """Shutdown the server.

        Returns immediately after initiating shutdown. Cleanup happens async.
        """
        # Set shutdown flag first so serve loop will exit
        self._shutdown_requested = True

        # Emit shutdown event
        await self._emit(EventType.SERVER_SHUTDOWN)

        # Schedule cleanup in background (don't await)
        asyncio.create_task(self._cleanup_on_shutdown())

        return {"shutdown": True}

    async def _cleanup_on_shutdown(self) -> None:
        """Background cleanup during shutdown."""
        # Cancel all running DAGs
        for _dag_id, task in self._running_dags.items():
            task.cancel()
        self._running_dags.clear()

        # Close all channels (this can take time)
        await self._channel_manager.close_all()

    async def _ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ping the server to check if it's alive."""
        return {
            "pong": True,
            "channels": len(self._channel_manager.list()),
            "dags": len(self._running_dags),
        }

    # =========================================================================
    # Internal
    # =========================================================================

    async def _monitor_channel(self, channel: PTYChannel | WezTermChannel | ClaudeOnWezTermChannel) -> None:
        """Monitor channel for state changes.

        This runs in the background and emits events when
        the channel state changes.
        """
        last_state = channel.state

        while channel.state != ChannelState.CLOSED:
            await asyncio.sleep(0.5)

            if channel.state != last_state:
                if channel.state == ChannelState.OPEN:
                    await self._emit(EventType.CHANNEL_READY, channel_id=channel.id)
                elif channel.state == ChannelState.BUSY:
                    await self._emit(EventType.CHANNEL_BUSY, channel_id=channel.id)

                last_state = channel.state
