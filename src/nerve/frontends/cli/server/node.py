"""Node subcommands for server."""

from __future__ import annotations

import rich_click as click

from nerve.frontends.cli.output import error_exit, output_json_or_table, print_table
from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import async_server_command, build_params, server_connection
from nerve.server.protocols import NODE_TYPE_TO_BACKEND

# Node type choices for CLI (must match NODE_TYPE_TO_BACKEND keys)
NODE_TYPE_CHOICES = [
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",  # Terminal nodes
    "BashNode",  # Stateless bash
    "IdentityNode",  # Stateless identity (echo)
    "OpenRouterNode",
    "GLMNode",  # Single-shot LLM
    "StatefulLLMNode",  # Stateful chat
    "SuggestionNode",  # Suggestion generation
    "MCPNode",  # MCP server connection
]


@server.group()
def node() -> None:
    """Manage nodes.

    Nodes are persistent execution contexts that maintain state across
    interactions. They can run any process: AI CLIs (Claude, Gemini),
    shells (bash, zsh), interpreters (Python, Node), or other programs.

    **Commands:**

        nerve server node list      List nodes in a session

        nerve server node create    Create a new node

        nerve server node delete    Delete a node

        nerve server node send      Send input and get response
    """
    pass


@node.command("list")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@async_server_command
async def node_list(server_name: str, session_id: str | None, json_output: bool) -> None:
    """List all nodes in a session.

    Shows nodes in the specified session (or default session).

    **Examples:**

        nerve server node list

        nerve server node list --server myproject

        nerve server node list --server myproject --session my-workspace

        nerve server node list --json
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        params = build_params(session_id=session_id)

        result = await client.send_command(
            Command(
                type=CommandType.GET_SESSION,
                params=params,
            )
        )

        if result.success and result.data:
            nodes_info = result.data.get("nodes_info", [])
            session_display_name = result.data.get("name", "default")  # Capture for closure

            def show_table() -> None:
                if nodes_info:
                    rows = []
                    for info in nodes_info:
                        name = info.get("id", "?")
                        backend = info.get("backend", info.get("type", "?"))
                        state = info.get("state", "?")
                        last_input = info.get("last_input", "")
                        if last_input:
                            last_input = last_input[:30]
                        rows.append([name, backend, state, last_input])
                    print_table(
                        ["NAME", "BACKEND", "STATE", "LAST INPUT"],
                        rows,
                        widths=[20, 18, 10, 30],
                    )
                else:
                    click.echo(f"No nodes in session '{session_display_name}'")

            output_json_or_table(nodes_info, json_output, show_table)
        else:
            error_exit(result.error or "Unknown error")


@node.command("create")
@click.argument("name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option(
    "--command", "-c", default=None, help="Command to run (e.g., 'claude' or 'my-cli --flag')"
)
@click.option(
    "--type",
    "-t",
    "node_type",
    type=click.Choice(NODE_TYPE_CHOICES),
    default="PTYNode",
    help="Node type (stateful: PTYNode, WezTermNode, ClaudeWezTermNode, StatefulLLMNode; stateless: BashNode, IdentityNode, OpenRouterNode, GLMNode, SuggestionNode)",
)
@click.option(
    "--pane-id", default=None, help="Attach to existing WezTerm pane (wezterm backend only)"
)
@click.option(
    "--history/--no-history",
    default=True,
    help="Enable/disable history logging (default: enabled)",
)
@click.option(
    "--api-format",
    type=click.Choice(["anthropic", "openai"]),
    default=None,
    help="Provider API format (anthropic or openai). Enables proxy.",
)
@click.option(
    "--provider-base-url",
    default=None,
    help="Provider base URL (e.g., https://api.openai.com/v1)",
)
@click.option(
    "--provider-api-key",
    default=None,
    help="Provider API key",
)
@click.option(
    "--provider-model",
    default=None,
    help="Model to use (required for openai format, optional for anthropic)",
)
@click.option(
    "--provider-debug-dir",
    default=None,
    help="Directory for proxy debug logs",
)
@click.option(
    "--transparent",
    is_flag=True,
    default=False,
    help="Transparent logging mode: forward original auth headers (no API key needed)",
)
@click.option(
    "--log-headers",
    is_flag=True,
    default=False,
    help="Include request/response headers in debug logs (for research)",
)
# Stateless node options (BashNode, OpenRouterNode, GLMNode)
@click.option(
    "--cwd",
    default=None,
    help="Working directory (BashNode, MCPNode, terminal nodes)",
)
@click.option(
    "--bash-timeout",
    type=float,
    default=None,
    help="Execution timeout in seconds (BashNode only, default: 120.0)",
)
@click.option(
    "--api-key",
    default=None,
    help="API key for LLM provider (LLM nodes: OpenRouterNode, GLMNode)",
)
@click.option(
    "--llm-model",
    default=None,
    help="Model name, e.g., 'anthropic/claude-3-haiku' or 'glm-4.7' (LLM nodes)",
)
@click.option(
    "--llm-base-url",
    default=None,
    help="Base URL for LLM API (LLM nodes, uses provider default if not set)",
)
@click.option(
    "--llm-timeout",
    type=float,
    default=None,
    help="Request timeout in seconds (LLM nodes, default: 120.0)",
)
@click.option(
    "--llm-debug-dir",
    default=None,
    help="Directory for request/response debug logs (LLM nodes)",
)
@click.option(
    "--thinking",
    is_flag=True,
    default=False,
    help="Enable thinking/reasoning mode (GLMNode only)",
)
# StatefulLLMNode-specific options
@click.option(
    "--llm-provider",
    type=click.Choice(["openrouter", "glm"]),
    default=None,
    help="LLM provider for chat node (StatefulLLMNode only)",
)
@click.option(
    "--system",
    default=None,
    help="System prompt for chat node (StatefulLLMNode only)",
)
@click.option(
    "--http-backend",
    type=click.Choice(["aiohttp", "openai"]),
    default="aiohttp",
    help="HTTP backend for LLM nodes (aiohttp or openai SDK, default: aiohttp)",
)
# Tool calling options (StatefulLLMNode only)
@click.option(
    "--tool",
    "tool_node_ids",
    multiple=True,
    help="Node ID to use as tool (repeatable). Node must exist and be tool-capable.",
)
@click.option(
    "--tool-choice",
    type=click.Choice(["auto", "none", "required"]),
    default=None,
    help="Tool choice mode: auto (default), none (disable), required (must use tool)",
)
@click.option(
    "--force-tool",
    default=None,
    help="Force specific tool by name (alternative to --tool-choice)",
)
@click.option(
    "--parallel-tool-calls/--no-parallel-tool-calls",
    default=None,
    help="Enable/disable parallel tool calls (default: provider decides)",
)
# MCPNode options
@click.option(
    "--mcp-args",
    "mcp_args",
    multiple=True,
    help="Arguments for MCP server command (MCPNode only, repeatable)",
)
@async_server_command
async def node_create(
    name: str,
    server_name: str,
    session_id: str | None,
    command: str | None,
    node_type: str,
    pane_id: str | None,
    history: bool,
    api_format: str | None,
    provider_base_url: str | None,
    provider_api_key: str | None,
    provider_model: str | None,
    provider_debug_dir: str | None,
    transparent: bool,
    log_headers: bool,
    # Stateless node options
    cwd: str | None,
    bash_timeout: float | None,
    api_key: str | None,
    llm_model: str | None,
    llm_base_url: str | None,
    llm_timeout: float | None,
    llm_debug_dir: str | None,
    thinking: bool,
    # StatefulLLMNode options
    llm_provider: str | None,
    system: str | None,
    # HTTP backend option
    http_backend: str,
    # Tool calling options
    tool_node_ids: tuple[str, ...],
    tool_choice: str | None,
    force_tool: str | None,
    parallel_tool_calls: bool | None,
    # MCPNode options
    mcp_args: tuple[str, ...],
) -> None:
    """Create a new node.

    NAME is the node name (required, must be unique).
    Names must be lowercase alphanumeric with dashes, 1-32 characters.

    **Examples:**

        nerve server node create my-claude --server myproject --command claude

        nerve server node create gemini-1 --server myproject --command gemini

        nerve server node create attached --server myproject --type WezTermNode --pane-id 4

        nerve server node create claude --server myproject --type ClaudeWezTermNode --command claude

    **With OpenAI provider (starts a proxy):**

        nerve server node create claude-openai --server myproject \\
            --type ClaudeWezTermNode \\
            --command "claude --dangerously-skip-permissions" \\
            --api-format openai \\
            --provider-base-url https://api.openai.com/v1 \\
            --provider-api-key sk-... \\
            --provider-model gpt-4.1

    **With Anthropic-format provider (passthrough proxy):**

        nerve server node create claude-glm --server myproject \\
            --type ClaudeWezTermNode \\
            --command "claude --dangerously-skip-permissions" \\
            --api-format anthropic \\
            --provider-base-url https://api.glm.ai/v1 \\
            --provider-api-key glm-... \\
            --provider-model glm-4.5

    **With debug logging:**

        nerve server node create claude-openai --server myproject \\
            --type ClaudeWezTermNode \\
            --command "claude --dangerously-skip-permissions" \\
            --api-format openai \\
            --provider-base-url https://api.openai.com/v1 \\
            --provider-api-key sk-... \\
            --provider-model gpt-4.1 \\
            --provider-debug-dir /tmp/proxy-logs

    **Transparent logging (no API key needed, uses OAuth auth):**

        nerve server node create claude-log --server myproject \\
            --type ClaudeWezTermNode \\
            --command "claude --dangerously-skip-permissions" \\
            --transparent \\
            --provider-debug-dir /tmp/proxy-logs

    **Stateless nodes (BashNode - runs commands, no state between calls):**

        nerve server node create my-bash --server myproject \\
            --type BashNode \\
            --cwd /tmp

        nerve server node send my-bash "ls -la"
        nerve server node send my-bash "pwd"

    **Stateless nodes (OpenRouterNode - LLM API calls, no conversation history):**

        nerve server node create my-llm --server myproject \\
            --type OpenRouterNode \\
            --api-key $OPENROUTER_API_KEY \\
            --llm-model anthropic/claude-3-haiku

        nerve server node send my-llm "What is 2+2?"
        nerve server node send my-llm "What is 3+3?"

    **MCP nodes (MCPNode - connects to MCP server, exposes tools):**

        nerve server node create notebooklm --server myproject \\
            --type MCPNode \\
            --command notebooklm-mcp

        nerve server node create fs-mcp --server myproject \\
            --type MCPNode \\
            --command npx \\
            --mcp-args @modelcontextprotocol/server-filesystem \\
            --mcp-args /tmp
    """
    from nerve.core.validation import validate_name
    from nerve.server.protocols import Command, CommandType

    try:
        validate_name(name, "node")
    except ValueError as e:
        error_exit(str(e))

    # Validate provider options
    if transparent:
        # Transparent mode: only requires --transparent (and optionally --provider-debug-dir)
        if api_format or provider_base_url or provider_api_key:
            error_exit(
                "--transparent cannot be combined with --api-format, "
                "--provider-base-url, or --provider-api-key"
            )
        if node_type != "ClaudeWezTermNode":
            error_exit("--transparent requires --type ClaudeWezTermNode")
        # Set defaults for transparent mode
        api_format = "anthropic"
        provider_base_url = "https://api.anthropic.com"
    else:
        # Normal provider mode: all three options required together
        provider_opts = [api_format, provider_base_url, provider_api_key]
        if any(provider_opts) and not all(provider_opts):
            error_exit(
                "--api-format, --provider-base-url, and --provider-api-key "
                "must all be specified together"
            )

        if api_format == "openai" and not provider_model:
            error_exit("--provider-model is required for openai format")

        if api_format and node_type != "ClaudeWezTermNode":
            error_exit("Provider options require --type ClaudeWezTermNode")

    # Validate stateless node options
    if node_type == "BashNode":
        # BashNode doesn't need special validation, uses command and cwd
        pass
    elif node_type in ("OpenRouterNode", "GLMNode", "SuggestionNode"):
        # Stateless LLM nodes require api_key and llm_model
        if not api_key:
            error_exit(f"--api-key is required for {node_type}")
        if not llm_model:
            error_exit(f"--llm-model is required for {node_type}")
        # --thinking only valid for GLMNode
        if thinking and node_type != "GLMNode":
            error_exit("--thinking is only valid for GLMNode")
        # --llm-provider and --system are for StatefulLLMNode
        if llm_provider:
            error_exit("--llm-provider is only valid for StatefulLLMNode")
    elif node_type == "StatefulLLMNode":
        # Chat node requires api_key, llm_model, and llm_provider
        if not api_key:
            error_exit("--api-key is required for StatefulLLMNode")
        if not llm_model:
            error_exit("--llm-model is required for StatefulLLMNode")
        if not llm_provider:
            error_exit("--llm-provider is required for StatefulLLMNode (openrouter or glm)")
        # --thinking only valid if provider is glm
        if thinking and llm_provider != "glm":
            error_exit("--thinking is only valid when --llm-provider is glm")
        # --force-tool and --tool-choice are mutually exclusive
        if force_tool and tool_choice:
            error_exit("--force-tool and --tool-choice are mutually exclusive")
    else:
        # Non-LLM nodes shouldn't use LLM options
        if api_key or llm_model or llm_base_url or llm_timeout:
            error_exit(
                "--api-key, --llm-model, --llm-base-url, --llm-timeout "
                "are only valid for LLM nodes (OpenRouterNode, GLMNode, SuggestionNode, StatefulLLMNode)"
            )
        if thinking:
            error_exit("--thinking is only valid for GLMNode or StatefulLLMNode with glm provider")
        if llm_provider or system:
            error_exit("--llm-provider and --system are only valid for StatefulLLMNode")
        if cwd and node_type not in (
            "PTYNode",
            "WezTermNode",
            "ClaudeWezTermNode",
            "BashNode",
            "MCPNode",
        ):
            error_exit("--cwd is only valid for BashNode, MCPNode, and terminal nodes")
        if bash_timeout:
            error_exit("--bash-timeout is only valid for BashNode")

    # Tool options are only valid for StatefulLLMNode
    if node_type != "StatefulLLMNode":
        if tool_node_ids:
            error_exit("--tool is only valid for StatefulLLMNode")
        if tool_choice:
            error_exit("--tool-choice is only valid for StatefulLLMNode")
        if force_tool:
            error_exit("--force-tool is only valid for StatefulLLMNode")
        if parallel_tool_calls is not None:
            error_exit("--parallel-tool-calls is only valid for StatefulLLMNode")

    # MCP options validation
    if node_type == "MCPNode":
        if not command:
            error_exit("--command is required for MCPNode (MCP server executable)")
    elif mcp_args:
        error_exit("--mcp-args is only valid for MCPNode")

    # Map node type to wire protocol backend value
    backend = NODE_TYPE_TO_BACKEND.get(node_type, "pty")

    async with server_connection(server_name) as client:
        params: dict[str, object] = {
            "node_id": name,
            "backend": backend,
            "history": history,
        }
        if session_id:
            params["session_id"] = session_id
        if command:
            params["command"] = command
        if pane_id:
            params["pane_id"] = pane_id
        if cwd:
            params["cwd"] = cwd

        # Add BashNode options
        if bash_timeout is not None:
            params["bash_timeout"] = bash_timeout

        # Add LLM node options (OpenRouterNode, GLMNode, LLMChatNode)
        if api_key:
            params["api_key"] = api_key
        if llm_model:
            params["llm_model"] = llm_model
        if llm_base_url:
            params["llm_base_url"] = llm_base_url
        if llm_timeout is not None:
            params["llm_timeout"] = llm_timeout
        if llm_debug_dir:
            params["llm_debug_dir"] = llm_debug_dir
        if thinking:
            params["llm_thinking"] = thinking
        if llm_provider:
            params["llm_provider"] = llm_provider
        if system:
            params["llm_system"] = system
        # Add HTTP backend for LLM nodes
        if http_backend != "aiohttp":  # Only send if not default
            params["http_backend"] = http_backend

        # Add tool calling options (LLMChatNode only)
        if tool_node_ids:
            params["tool_node_ids"] = list(tool_node_ids)
        if force_tool:
            # Convert --force-tool to tool_choice format
            params["tool_choice"] = {"type": "function", "function": {"name": force_tool}}
        elif tool_choice:
            params["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            params["parallel_tool_calls"] = parallel_tool_calls

        # Add provider config if specified
        if api_format:
            provider_config: dict[str, str | bool | None] = {
                "api_format": api_format,
                "base_url": provider_base_url,
                "api_key": provider_api_key,
                "model": provider_model,
                "transparent": transparent,
                "log_headers": log_headers,
            }
            if provider_debug_dir:
                provider_config["debug_dir"] = provider_debug_dir
            params["provider"] = provider_config

        # Add MCP options
        if mcp_args:
            params["mcp_args"] = list(mcp_args)

        result = await client.send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params=params,
            )
        )

        if result.success:
            proxy_url = result.data.get("proxy_url") if result.data else None
            if proxy_url:
                click.echo(f"Created node: {name} (proxy: {proxy_url})")
            else:
                click.echo(f"Created node: {name}")
        else:
            error_exit(result.error or "Unknown error")


@node.command("delete")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@async_server_command
async def node_delete(node_name: str, server_name: str, session_id: str | None) -> None:
    """Delete a node.

    Stops the node, closes its terminal/pane, and removes it from the server.

    **Arguments:**

        NODE_NAME     The node to delete

    **Examples:**

        nerve server node delete my-claude --server local

        nerve server node delete my-shell -s myproject

        nerve server node delete claude --server myproject --session my-workspace
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        params = build_params(node_id=node_name, session_id=session_id)

        result = await client.send_command(
            Command(
                type=CommandType.DELETE_NODE,
                params=params,
            )
        )

        if result.success:
            click.echo(f"Deleted node: {node_name}")
        else:
            error_exit(result.error or "Unknown error")


@node.command("run")
@click.argument("node_name")
@click.argument("command")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@async_server_command
async def node_run(node_name: str, command: str, server_name: str) -> None:
    """Start a program in a node (fire and forget).

    Use this to launch programs that take over the terminal,
    like claude, python, vim, etc. This does NOT wait for the
    program to be ready - use 'send' to interact with it after.

    **Arguments:**

        NODE_NAME     The node to run in

        COMMAND       The program/command to start

    **Examples:**

        nerve server node run my-shell claude --server myproject

        nerve server node run my-shell python --server myproject

        nerve server node run my-shell "gemini --flag" --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        result = await client.send_command(
            Command(
                type=CommandType.RUN_COMMAND,
                params={
                    "node_id": node_name,
                    "command": command,
                },
            )
        )

        if result.success:
            click.echo(f"Started: {command}")
        else:
            error_exit(result.error or "Unknown error")


@node.command("read")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--lines", "-n", default=None, type=int, help="Only show last N lines")
@async_server_command
async def node_read(node_name: str, server_name: str, lines: int | None) -> None:
    """Read the output buffer of a node.

    Shows all output from the node since it was created.

    **Arguments:**

        NODE_NAME     The node to read from

    **Examples:**

        nerve server node read my-shell --server local

        nerve server node read my-shell --server local --lines 50
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        params: dict[str, str | int] = {"node_id": node_name}
        if lines:
            params["lines"] = lines

        result = await client.send_command(
            Command(
                type=CommandType.GET_BUFFER,
                params=params,
            )
        )

        if result.success and result.data:
            click.echo(result.data.get("buffer", ""))
        else:
            error_exit(result.error or "Unknown error")


@node.command("send")
@click.argument("node_name")
@click.argument("text")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option(
    "--parser",
    "-p",
    type=click.Choice(["claude", "gemini", "none"]),
    default=None,
    help="Parser for output. Default: auto-detect from node type.",
)
@click.option(
    "--submit",
    default=None,
    help="Submit sequence (e.g., '\\n', '\\r', '\\x1b\\r'). Default: auto based on parser.",
)
@async_server_command
async def node_send(
    node_name: str, text: str, server_name: str, parser: str | None, submit: str | None
) -> None:
    """Send input to a node and get JSON response.

    **Arguments:**

        NODE_NAME     The node to send to

        TEXT          The text/prompt to send

    **Examples:**

        nerve server node send my-claude "Explain this code" --server myproject

        nerve server node send my-shell "ls" --server myproject --parser none
    """
    import json

    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        params = {
            "node_id": node_name,
            "text": text,
        }
        # Only include parser if explicitly set (let node use its default)
        if parser is not None:
            params["parser"] = parser
        # Decode escape sequences in submit string (e.g., "\\x1b" -> actual escape)
        if submit:
            params["submit"] = submit.encode().decode("unicode_escape")

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=params,
            )
        )

        if not result.success:
            # Output error as JSON
            click.echo(json.dumps({"error": result.error}, indent=2))
        elif result.data:
            # Output response as JSON
            response = result.data.get("response", {})
            click.echo(json.dumps(response, indent=2))


@node.command("write")
@click.argument("node_name")
@click.argument("data")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@async_server_command
async def node_write(node_name: str, data: str, server_name: str) -> None:
    """Write raw data to a node (no waiting).

    Low-level write for testing and debugging. Does not wait for response.
    Use escape sequences like \\x1b for Escape, \\r for CR, \\n for LF.

    **Arguments:**

        NODE_NAME     The node to write to

        DATA          Raw data to write (escape sequences supported)

    **Examples:**

        nerve server node write my-shell "Hello" --server local

        nerve server node write my-shell "\\x1b" --server local  # Send Escape

        nerve server node write my-shell "\\r" --server local    # Send CR
    """
    from nerve.server.protocols import Command, CommandType

    # Decode escape sequences
    decoded_data = data.encode().decode("unicode_escape")

    async with server_connection(server_name) as client:
        result = await client.send_command(
            Command(
                type=CommandType.WRITE_DATA,
                params={
                    "node_id": node_name,
                    "data": decoded_data,
                },
            )
        )

        if result.success:
            click.echo(f"Wrote {len(decoded_data)} bytes")
        else:
            error_exit(result.error or "Unknown error")


@node.command("interrupt")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@async_server_command
async def node_interrupt(node_name: str, server_name: str) -> None:
    """Send interrupt (Ctrl+C) to a node.

    Cancels the current operation in the node.

    **Arguments:**

        NODE_NAME     The node to interrupt

    **Examples:**

        nerve server node interrupt my-claude --server local
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        result = await client.send_command(
            Command(
                type=CommandType.SEND_INTERRUPT,
                params={"node_id": node_name},
            )
        )

        if result.success:
            click.echo("Interrupt sent")
        else:
            error_exit(result.error or "Unknown error")


@node.command("fork")
@click.argument("source")
@click.argument("target", required=False)
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option(
    "--execute",
    "-e",
    "execute_text",
    default=None,
    help="Send a message to the forked node immediately after creation",
)
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@async_server_command
async def node_fork(
    source: str,
    target: str | None,
    server_name: str,
    session_id: str | None,
    execute_text: str | None,
    json_output: bool,
) -> None:
    """Fork a node with copied state.

    Creates a new node by copying the state from SOURCE node.
    For StatefulLLMNode, this copies the entire conversation history,
    allowing you to branch conversations.

    **Arguments:**

        SOURCE     The node to fork (e.g., 'claude')

        TARGET     Name for the forked node (optional, auto-generated if not provided)

    **Examples:**

        nerve server node fork claude
        # Creates claude_fork_1 with same conversation history

        nerve server node fork claude researcher
        # Creates 'researcher' with same conversation history

        nerve server node fork claude researcher --execute "Now focus on security analysis"
        # Fork and immediately send a message

        nerve server node fork claude --session my-workspace
        # Fork in specific session
    """
    import json

    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        # Auto-generate target name if not provided
        if not target:
            # First, list nodes to find a unique name
            params = build_params(session_id=session_id)
            list_result = await client.send_command(
                Command(type=CommandType.LIST_NODES, params=params)
            )
            existing_nodes = set()
            if list_result.success and list_result.data:
                existing_nodes = {info["id"] for info in list_result.data.get("nodes_info", [])}

            # Generate unique name
            base_name = f"{source}_fork"
            counter = 1
            target = f"{base_name}_{counter}"
            while target in existing_nodes:
                counter += 1
                target = f"{base_name}_{counter}"

        # Fork the node
        fork_params = build_params(
            source_id=source,
            target_id=target,
            session_id=session_id,
        )

        result = await client.send_command(
            Command(
                type=CommandType.FORK_NODE,
                params=fork_params,
            )
        )

        if not result.success:
            error_exit(result.error or "Fork failed")
            return

        forked_id = result.data.get("node_id", target) if result.data else target
        forked_from = result.data.get("forked_from", source) if result.data else source

        # Execute message on forked node if requested
        execute_result = None
        execute_error = None
        if execute_text:
            exec_params = build_params(
                node_id=forked_id,
                text=execute_text,
                session_id=session_id,
            )
            exec_result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params=exec_params,
                )
            )
            if exec_result.success and exec_result.data:
                execute_result = exec_result.data.get("response", {})
            elif not exec_result.success:
                # Fork succeeded but execute failed - report the error
                execute_error = exec_result.error or "Execute failed"

        # Output
        if json_output:
            output_data = {
                "node_id": forked_id,
                "forked_from": forked_from,
            }
            if execute_result:
                output_data["execute_result"] = execute_result
            if execute_error:
                output_data["execute_error"] = execute_error
            click.echo(json.dumps(output_data, indent=2))
        else:
            click.echo(f"Forked: {source} → {forked_id}")
            if execute_error:
                click.echo(f"Warning: Execute failed: {execute_error}", err=True)
            elif execute_result:
                # Show response output
                output = execute_result.get("output", "")
                if output:
                    click.echo(f"\nResponse:\n{output}")


@node.command("history")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option(
    "--session", "session_name", default="default", help="Session name (default: default)"
)
@click.option("--last", "-n", "limit", type=int, default=None, help="Show only last N entries")
@click.option(
    "--op",
    type=click.Choice(["send", "send_stream", "write", "run", "read", "interrupt", "delete"]),
    help="Filter by operation type",
)
@click.option("--seq", type=int, default=None, help="Get entry by sequence number")
@click.option("--inputs-only", is_flag=True, help="Show only input operations (send, write, run)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@click.option("--summary", is_flag=True, help="Show summary statistics")
def node_history(
    node_name: str,
    server_name: str,
    session_name: str,
    limit: int | None,
    op: str | None,
    seq: int | None,
    inputs_only: bool,
    json_output: bool,
    summary: bool,
) -> None:
    """View history for a node.

    Reads the JSONL history file for the specified node.
    History is stored in .nerve/history/<server>/<session>/<node>.jsonl

    **Arguments:**

        NODE_NAME     The node to view history for

    **Examples:**

        nerve server node history my-claude

        nerve server node history my-claude --last 10

        nerve server node history my-claude --server prod --session my-session

        nerve server node history my-claude --op send

        nerve server node history my-claude --inputs-only --json

        nerve server node history my-claude --summary
    """
    import json
    from pathlib import Path

    from nerve.core.nodes.history import HistoryReader
    from nerve.frontends.cli.output import print_history_entries, print_history_summary

    try:
        # Default base directory
        base_dir = Path.cwd() / ".nerve" / "history"

        reader = HistoryReader.create(
            node_id=node_name,
            server_name=server_name,
            session_name=session_name,
            base_dir=base_dir,
        )

        # Get entries based on filters
        if seq is not None:
            entry = reader.get_by_seq(seq)
            if entry is None:
                error_exit(f"No entry with sequence number {seq}")
            entries = [entry]
        elif inputs_only:
            entries = reader.get_inputs_only()
        elif op:
            entries = reader.get_by_op(op)
        else:
            entries = reader.get_all()

        # Apply limit if specified
        if limit is not None:
            entries = entries[-limit:] if limit < len(entries) else entries

        if not entries:
            click.echo("No history entries found")
            return

        # Summary mode
        if summary:
            print_history_summary(entries, node_name, server_name, session_name)
            return

        if json_output:
            click.echo(json.dumps(entries, indent=2, default=str))
        else:
            print_history_entries(entries)

    except FileNotFoundError:
        error_exit(
            f"No history found for node '{node_name}' in session '{session_name}' on server '{server_name}'"
        )
