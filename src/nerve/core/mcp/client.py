"""MCPClient - low-level MCP protocol client.

Handles stdio transport to MCP servers using JSON-RPC 2.0 protocol.
Supports MCP protocol version 2024-11-05.

For V1, only stdio transport is supported. Message framing uses
newline-delimited JSON (one JSON object per line).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, cast

from nerve.core.mcp.errors import MCPConnectionError, MCPError


@dataclass
class MCPToolInfo:
    """Tool information from MCP server.

    Attributes:
        name: Tool name (e.g., "read_file").
        description: Human-readable description.
        input_schema: JSON Schema for tool parameters.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPClient:
    """Low-level MCP protocol client.

    Handles stdio transport to MCP servers using JSON-RPC 2.0.
    Operations are serialized (one at a time) for V1.

    Example:
        >>> client = await MCPClient.connect(
        ...     command="npx",
        ...     args=["@modelcontextprotocol/server-filesystem", "/tmp"],
        ... )
        >>> tools = await client.list_tools()
        >>> result = await client.call_tool("read_file", {"path": "/tmp/foo.txt"})
        >>> await client.close()
    """

    _process: asyncio.subprocess.Process
    _reader: asyncio.StreamReader
    _writer: asyncio.StreamWriter
    _request_id: int = field(default=0, init=False)
    _timeout: float = field(default=30.0, init=False)

    def _next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    @classmethod
    async def connect(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
    ) -> MCPClient:
        """Launch MCP server process and establish connection.

        Args:
            command: Command to launch MCP server (e.g., "npx", "python").
            args: Command arguments.
            env: Additional environment variables for MCP server process.
            cwd: Working directory for MCP server process.
            timeout: Timeout for MCP operations in seconds.

        Returns:
            Connected MCPClient ready for tool operations.

        Raises:
            MCPConnectionError: If connection or handshake fails.
        """
        args = args or []

        # Build environment
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        try:
            # Launch subprocess with stdio
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
                cwd=cwd,
            )
        except FileNotFoundError:
            raise MCPConnectionError(f"Command not found: {command}") from None
        except Exception as e:
            raise MCPConnectionError(f"Failed to start MCP server: {e}") from e

        if process.stdin is None or process.stdout is None:
            process.terminate()
            raise MCPConnectionError("Failed to establish stdio pipes")

        client = cls(
            _process=process,
            _reader=process.stdout,
            _writer=process.stdin,
        )
        client._timeout = timeout

        # Initialize MCP handshake
        try:
            await client._initialize()
        except Exception as e:
            await client.close()
            raise MCPConnectionError(f"MCP initialization failed: {e}") from e

        return client

    async def _initialize(self) -> None:
        """Perform MCP initialization handshake."""
        # Send initialize request
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "nerve", "version": "0.1.0"},
                },
            }
        )

        # Wait for response
        response = await self._receive()
        if "error" in response:
            raise MCPError(f"Initialize failed: {response['error']}")

        # Send initialized notification
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self) -> list[MCPToolInfo]:
        """Get list of available tools from server.

        Returns:
            List of MCPToolInfo describing available tools.

        Raises:
            MCPError: If server returns an error.
            MCPConnectionError: If communication fails.
        """
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            }
        )

        response = await self._receive()

        if "error" in response:
            raise MCPError(f"list_tools failed: {response['error']}")

        tools = response.get("result", {}).get("tools", [])

        return [
            MCPToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool on the MCP server.

        Args:
            name: Tool name.
            args: Tool arguments.

        Returns:
            Tool result (text content extracted from response).

        Raises:
            MCPError: If tool execution fails.
            MCPConnectionError: If communication fails.
        """
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )

        response = await self._receive()

        if "error" in response:
            error_msg = response["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            raise MCPError(f"Tool '{name}' failed: {error_msg}")

        # Extract content from result (may contain multiple content blocks)
        content = response.get("result", {}).get("content", [])
        if not content:
            return ""

        # Concatenate text from all content blocks
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
            elif block:
                text_parts.append(str(block))

        return "\n\n".join(text_parts) if text_parts else ""

    async def close(self) -> None:
        """Close the MCP connection and terminate server process."""
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass  # Best effort close

        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()
        except Exception:
            pass  # Process may have already exited

    async def _send(self, message: dict[str, Any]) -> None:
        """Send JSON-RPC message.

        Args:
            message: JSON-RPC message dict.

        Raises:
            MCPConnectionError: If write fails.
        """
        try:
            data = json.dumps(message)
            self._writer.write(f"{data}\n".encode())
            await self._writer.drain()
        except Exception as e:
            raise MCPConnectionError(f"Failed to send message: {e}") from e

    async def _receive(self) -> dict[str, Any]:
        """Receive JSON-RPC message with timeout.

        Returns:
            Parsed JSON-RPC response.

        Raises:
            MCPConnectionError: If read fails or times out.
        """
        try:
            line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self._timeout,
            )
            if not line:
                raise MCPConnectionError("MCP server closed connection")
            return cast(dict[str, Any], json.loads(line.decode()))
        except TimeoutError:
            raise MCPConnectionError(
                f"MCP server did not respond within {self._timeout}s"
            ) from None
        except json.JSONDecodeError as e:
            raise MCPConnectionError(f"Invalid JSON from MCP server: {e}") from e
        except Exception as e:
            if isinstance(e, MCPConnectionError):
                raise
            raise MCPConnectionError(f"Failed to receive message: {e}") from e
