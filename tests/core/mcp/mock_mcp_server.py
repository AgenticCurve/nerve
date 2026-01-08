#!/usr/bin/env python3
"""Mock MCP server for testing.

This script implements a minimal MCP server over stdio for testing purposes.
It responds to:
- initialize: Returns server capabilities
- tools/list: Returns test tools
- tools/call: Executes test tools

Usage:
    python mock_mcp_server.py [--fail-init] [--fail-call]
"""

from __future__ import annotations

import json
import sys


def send_response(response: dict) -> None:
    """Send JSON-RPC response."""
    print(json.dumps(response), flush=True)


def handle_request(request: dict, fail_call: bool = False) -> dict | None:
    """Handle a JSON-RPC request."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    # Handle notifications (no id)
    if method == "notifications/initialized":
        return None  # No response for notifications

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp-server", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo the input message",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Message to echo",
                                }
                            },
                            "required": ["message"],
                        },
                    },
                    {
                        "name": "add",
                        "description": "Add two numbers",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "a": {"type": "number", "description": "First number"},
                                "b": {"type": "number", "description": "Second number"},
                            },
                            "required": ["a", "b"],
                        },
                    },
                    {
                        "name": "fail",
                        "description": "Always fails (for testing)",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if fail_call:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -1, "message": "Simulated call failure"},
            }

        if tool_name == "echo":
            message = tool_args.get("message", "")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Echo: {message}"}]},
            }

        if tool_name == "add":
            a = tool_args.get("a", 0)
            b = tool_args.get("b", 0)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(a + b)}]},
            }

        if tool_name == "fail":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -1, "message": "Tool always fails"},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> None:
    """Run the mock MCP server."""
    fail_init = "--fail-init" in sys.argv
    fail_call = "--fail-call" in sys.argv

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        if fail_init and request.get("method") == "initialize":
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -1, "message": "Simulated init failure"},
                }
            )
            continue

        response = handle_request(request, fail_call=fail_call)
        if response is not None:
            send_response(response)


if __name__ == "__main__":
    main()
