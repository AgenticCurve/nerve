# PRD: Multi-Provider Support for ClaudeWezTermNode

## Problem Statement

Currently, `ClaudeWezTermNode` only works with Anthropic's API directly. Users who want to:

1. Use OpenAI models (GPT-4, GPT-4.1) as the backend for Claude Code
2. Use other OpenAI-compatible APIs (Azure OpenAI, local models via Ollama/vLLM)
3. Use Anthropic-compatible APIs (GLM-4.5, other Claude-compatible endpoints)
4. Compare model performance across providers
5. Log/debug all requests regardless of provider

...must manually start a proxy server, set environment variables, and manage the proxy lifecycle separately from their Nerve nodes. This creates operational overhead and breaks the abstraction that Nerve provides.

**Goal**: Allow users to create a `ClaudeWezTermNode` that transparently uses any LLM provider as the backend, with Nerve managing all the complexity.

---

## Core Concept: API Formats

Different LLM providers use different API formats:

| API Format | Description | Examples |
|------------|-------------|----------|
| `anthropic` | Anthropic Messages API | Anthropic Claude, GLM-4.5 |
| `openai` | OpenAI Chat Completions API | OpenAI GPT-4, Azure OpenAI, Ollama, vLLM |
| `gemini` | Google Gemini API | Google Gemini (future) |

## Proxy Behavior

**Key principle: Proxy is OPTIONAL. Default behavior (no provider config) works exactly as before.**

| Configuration | Proxy? | Behavior |
|--------------|--------|----------|
| No `provider` config | **No proxy** | Direct to Anthropic API (existing behavior) |
| `provider` with `api_format="anthropic"` | **Passthrough proxy** | Forwards as-is, logs requests |
| `provider` with `api_format="openai"` | **Transform proxy** | Converts Anthropic ↔ OpenAI |
| `provider` with `api_format="gemini"` | **Transform proxy** | Converts Anthropic ↔ Gemini (future) |

### Why Passthrough Proxy for Anthropic-format APIs?

Even if the API format matches Anthropic's, routing through a proxy provides:

1. **Request/response logging** - Debug and audit all LLM interactions
2. **Model override** - Use a different model name than what Claude Code sends
3. **Future flexibility** - Can add rate limiting, caching, retries without changing nodes

### Proxy Types

```
NO PROXY (default - direct to Anthropic):
┌──────────────┐                          ┌──────────────────┐
│ Claude Code  │─────────────────────────►│ Anthropic API    │
│              │◄─────────────────────────│                  │
└──────────────┘                          └──────────────────┘

PASSTHROUGH PROXY (api_format="anthropic"):
┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐
│ Claude Code  │───►│ Passthrough Proxy │───►│ GLM-4.5 API      │
│ (Anthropic)  │    │ - Log request     │    │ (Anthropic fmt)  │
│              │◄───│ - Rebase URL      │◄───│                  │
└──────────────┘    │ - Override model  │    └──────────────────┘
                    └───────────────────┘

TRANSFORM PROXY (api_format="openai"):
┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐
│ Claude Code  │───►│ Transform Proxy   │───►│ OpenAI API       │
│ (Anthropic)  │    │ - Log request     │    │ (OpenAI fmt)     │
│              │◄───│ - Transform A→O   │◄───│                  │
└──────────────┘    │ - Transform O→A   │    └──────────────────┘
                    └───────────────────┘
```

## Challenges

### 1. Protocol Translation Required

Claude Code speaks Anthropic's Messages API format. OpenAI uses a different Chat Completions API format. A translation proxy must:
- Transform requests: Anthropic format → OpenAI format
- Transform responses: OpenAI format → Anthropic format
- Handle streaming SSE events with different schemas
- Map tool calls between formats

We already have `OpenAIProxyServer` that does this (`src/nerve/gateway/openai_proxy.py`).

### 2. Client/Server Architecture Complexity

Nerve has a client/server separation:
- **Client side**: `NerveClient` with `RemoteNode` proxies
- **Server side**: `NerveEngine` with actual node instances
- **Transport layer**: Unix socket, TCP, HTTP, or in-process

Nodes are always instantiated on the server side. A proxy server for OpenAI must also run on the server side, not embedded in the node itself.

### 3. Lifecycle Management

Each node needs its own proxy instance because:
- Different nodes may use different OpenAI API keys
- Different nodes may use different models
- Isolation prevents cross-contamination of requests
- Clean shutdown: when node dies, its proxy dies

The proxy must:
- Start BEFORE the node (so Claude Code can connect)
- Stay alive while node is running
- Stop AFTER the node stops
- Handle crashes gracefully

### 4. Port Management

Each proxy needs a unique port. With multiple nodes, we need:
- Auto-assignment of free ports
- No collisions between concurrent nodes
- Cleanup of ports when proxies stop

### 5. Environment Variable Injection

Claude Code reads `ANTHROPIC_BASE_URL` to determine where to send requests. Since we spawn Claude in a WezTerm pane (shell), we must:
- Export the env var in the shell before running `claude`
- Ensure it's set before Claude starts (timing matters)

---

## Solution Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           NerveEngine                               │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ ProxyManager                                                 │   │
│  │   _proxies: dict[node_id, ProxyInstance]                     │   │
│  │                                                              │   │
│  │   ┌─────────────────┐  ┌─────────────────┐                   │   │
│  │   │ ProxyInstance   │  │ ProxyInstance   │                   │   │
│  │   │ node: "claude1" │  │ node: "claude2" │                   │   │
│  │   │ port: 34561     │  │ port: 34562     │                   │   │
│  │   │ provider: openai│  │ provider: openai│                   │   │
│  │   └────────┬────────┘  └────────┬────────┘                   │   │
│  └────────────┼─────────────────────┼───────────────────────────┘   │
│               │                     │                               │
│  ┌────────────┴─────────────────────┴───────────────────────────┐  │
│  │ Session                                                       │  │
│  │  ├─ claude1: ClaudeWezTermNode                               │  │
│  │  │    └─ ANTHROPIC_BASE_URL=http://127.0.0.1:34561           │  │
│  │  │                                                            │  │
│  │  └─ claude2: ClaudeWezTermNode                               │  │
│  │       └─ ANTHROPIC_BASE_URL=http://127.0.0.1:34562           │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Components

#### 1. ProxyManager (NEW)

Location: `src/nerve/server/proxy_manager.py`

Responsibilities:
- Start/stop proxy instances for nodes
- Track active proxies by node_id
- Auto-assign ports
- Health check before returning
- Cleanup on engine shutdown

```python
class ProxyManager:
    async def start_proxy(self, node_id: str, config: ProxyConfig) -> ProxyInstance
    async def stop_proxy(self, node_id: str) -> None
    def get_proxy_url(self, node_id: str) -> str | None
    async def stop_all(self) -> None
```

#### 2. ProviderConfig (NEW)

Location: `src/nerve/server/proxy_manager.py`

```python
@dataclass
class ProviderConfig:
    """Configuration for a custom LLM provider.

    When provided to ClaudeWezTermNode, a proxy will be started
    to handle the connection to this provider.
    """
    api_format: str        # "anthropic", "openai", "gemini" (future)
    base_url: str          # Upstream URL (e.g., "https://api.openai.com/v1")
    api_key: str           # Provider API key
    model: str | None = None  # Model to use; None = keep original from request (passthrough only)
    debug_dir: str | None = None  # None = auto-set to {session_log_dir}/proxy/{node_id}/

    def __post_init__(self):
        # Transform proxies require model to be specified
        if self.needs_transform and self.model is None:
            raise ValueError(f"model is required for api_format='{self.api_format}'")

    @property
    def needs_transform(self) -> bool:
        """Whether this provider needs format transformation."""
        return self.api_format != "anthropic"

    @property
    def proxy_type(self) -> str:
        """Which proxy implementation to use."""
        if self.api_format == "anthropic":
            return "passthrough"
        elif self.api_format == "openai":
            return "openai"
        elif self.api_format == "gemini":
            return "gemini"  # future
        else:
            raise ValueError(f"Unknown api_format: {self.api_format}")
```

**Model behavior:**
- For `api_format="openai"` (transform): `model` is **required** - specifies which OpenAI model to use
- For `api_format="anthropic"` (passthrough): `model` is **optional** - if `None`, keeps original model from Claude Code's request; if set, overrides it

**Debug directory:**
- If `debug_dir` is `None`, automatically set to `{session.history_base_dir}/../logs/proxy/{node_id}/`
- Request/response logs saved in same format as existing OpenAI proxy

#### 3. ProxyInstance (NEW)

Location: `src/nerve/server/proxy_manager.py`

```python
@dataclass
class ProxyInstance:
    node_id: str
    port: int
    server: Any  # OpenAIProxyServer or PassthroughProxyServer
    task: asyncio.Task
    config: ProviderConfig
```

**Cleanup Behavior:**

Each node has its own isolated proxy instance. When a node is stopped/deleted:

1. **Only that node's proxy is stopped** - other nodes' proxies continue running
2. **Port is freed** - the port becomes available for new proxies
3. **Graceful shutdown** - proxy completes in-flight requests before stopping
4. **Task cleanup** - asyncio task is awaited to ensure clean termination

```python
async def stop_proxy(self, node_id: str) -> None:
    """Stop proxy for a specific node. Other nodes unaffected."""
    instance = self._proxies.pop(node_id, None)
    if instance:
        # Signal shutdown
        instance.server._shutdown_event.set()
        # Wait for graceful termination (completes in-flight requests)
        await instance.task
        # Port is now freed and available for reuse
```

**Isolation guarantee:** Stopping node "claude-1" only affects proxy on port 34561. Node "claude-2" with proxy on port 34562 continues working uninterrupted.

#### 4. NerveEngine Changes

Location: `src/nerve/server/engine.py`

Changes:
- Add `_proxy_manager: ProxyManager` field
- In `_create_node()`: if `provider` config is present, start proxy before creating node
- In `_delete_node()`: if node has proxy, stop proxy after stopping node
- In `stop()`: call `_proxy_manager.stop_all()`

#### 5. ClaudeWezTermNode Changes

Location: `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

Changes:
- Add `proxy_url: str | None` parameter to `create()`
- If `proxy_url` is set, export `ANTHROPIC_BASE_URL` in shell before running claude

---

## API Design

### Creating Nodes with Different Providers

**Via SDK (NerveClient):**

```python
from nerve import NerveClient, ProviderConfig

client = await NerveClient.connect("/tmp/nerve.sock")

# 1. Default: Direct to Anthropic (NO PROXY - existing behavior)
node = await client.create_node(
    "claude",
    backend="claude-wezterm",
    command="claude --dangerously-skip-permissions",
    # No provider config = direct to Anthropic, no proxy
)

# 2. OpenAI backend (transform proxy)
node = await client.create_node(
    "claude-openai",
    backend="claude-wezterm",
    command="claude --dangerously-skip-permissions",
    provider=ProviderConfig(
        api_format="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-...",
        model="gpt-4.1",
    ),
)

# 3. Anthropic-format API (passthrough proxy for logging)
node = await client.create_node(
    "claude-glm",
    backend="claude-wezterm",
    command="claude --dangerously-skip-permissions",
    provider=ProviderConfig(
        api_format="anthropic",  # Same format, just different endpoint
        base_url="https://api.glm.ai/v1",
        api_key="glm-...",
        model="glm-4.5",
    ),
)

# 4. Local Ollama (OpenAI-compatible, transform proxy)
node = await client.create_node(
    "claude-ollama",
    backend="claude-wezterm",
    command="claude --dangerously-skip-permissions",
    provider=ProviderConfig(
        api_format="openai",
        base_url="http://localhost:11434/v1",
        api_key="",  # Ollama doesn't need key
        model="llama3.1:70b",
    ),
)

# All nodes use the same API!
response = await node.send("Hello!")
```

**Via CLI:**

```bash
# Default: Direct to Anthropic (no proxy)
nerve node create my-claude \
    --backend claude-wezterm \
    --command "claude --dangerously-skip-permissions"

# OpenAI backend
nerve node create my-claude \
    --backend claude-wezterm \
    --command "claude --dangerously-skip-permissions" \
    --api-format openai \
    --provider-base-url "https://api.openai.com/v1" \
    --provider-api-key "sk-..." \
    --provider-model "gpt-4.1"

# Anthropic-format API (e.g., GLM-4.5) with model override
nerve node create my-claude \
    --backend claude-wezterm \
    --command "claude --dangerously-skip-permissions" \
    --api-format anthropic \
    --provider-base-url "https://api.glm.ai/v1" \
    --provider-api-key "glm-..." \
    --provider-model "glm-4.5"

# Anthropic-format API without model override (keeps original)
nerve node create my-claude \
    --backend claude-wezterm \
    --command "claude --dangerously-skip-permissions" \
    --api-format anthropic \
    --provider-base-url "https://api.glm.ai/v1" \
    --provider-api-key "glm-..."
    # No --provider-model = keeps whatever Claude Code sends

# With custom debug directory
nerve node create my-claude \
    --backend claude-wezterm \
    --command "claude --dangerously-skip-permissions" \
    --api-format openai \
    --provider-base-url "https://api.openai.com/v1" \
    --provider-api-key "sk-..." \
    --provider-model "gpt-4.1" \
    --provider-debug-dir "/tmp/proxy-logs"
```

**Via YAML config:**

```yaml
nodes:
  # No provider = direct to Anthropic
  claude-default:
    backend: claude-wezterm
    command: "claude --dangerously-skip-permissions"

  # OpenAI backend
  claude-openai:
    backend: claude-wezterm
    command: "claude --dangerously-skip-permissions"
    provider:
      api_format: openai
      base_url: https://api.openai.com/v1
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1

  # Anthropic-format API with model override
  claude-glm:
    backend: claude-wezterm
    command: "claude --dangerously-skip-permissions"
    provider:
      api_format: anthropic
      base_url: https://api.glm.ai/v1
      api_key: ${GLM_API_KEY}
      model: glm-4.5

  # Anthropic-format API without model override
  claude-glm-passthrough:
    backend: claude-wezterm
    command: "claude --dangerously-skip-permissions"
    provider:
      api_format: anthropic
      base_url: https://api.glm.ai/v1
      api_key: ${GLM_API_KEY}
      # model omitted = keeps original from request
```

**Note:** Environment variables in YAML config use `${VAR}` syntax and are expanded by Nerve at config load time.

### Node Lifecycle

```
create_node(provider="openai")
        │
        ▼
┌───────────────────────────┐
│ 1. ProxyManager.start()   │
│    - Find free port       │
│    - Start OpenAIProxy    │
│    - Wait for /health OK  │
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 2. ClaudeWezTermNode      │
│    - Spawn WezTerm pane   │
│    - export ANTHROPIC_... │
│    - Run claude command   │
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 3. Node Ready             │
│    - Claude talks to proxy│
│    - Proxy talks to OpenAI│
└───────────────────────────┘

        ... node in use ...

delete_node()
        │
        ▼
┌───────────────────────────┐
│ 4. ClaudeWezTermNode.stop │
│    - Close WezTerm pane   │
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 5. ProxyManager.stop()    │
│    - Signal shutdown      │
│    - Wait for cleanup     │
│    - Release port         │
└───────────────────────────┘
```

---

## Implementation Plan

### Phase 1: PassthroughProxyServer

We already have `OpenAIProxyServer` for transform proxies. We need a simpler passthrough proxy.

1. Create `src/nerve/gateway/passthrough_proxy.py`

```python
@dataclass
class PassthroughProxyConfig:
    """Configuration for passthrough proxy server."""
    host: str = "127.0.0.1"
    port: int = 0  # 0 = auto-assign
    upstream_base_url: str = ""
    upstream_api_key: str = ""
    upstream_model: str | None = None  # None = keep original model from request
    debug_dir: str | None = None  # None = defaults to session log dir

@dataclass
class PassthroughProxyServer:
    """Proxy that forwards Anthropic-format requests as-is.

    Used for Anthropic-compatible APIs (GLM-4.5, etc.) where
    the upstream speaks the same format as Claude Code.
    """
    config: PassthroughProxyConfig

    async def serve(self) -> None:
        """Start the proxy server."""
        ...

    async def stop(self) -> None:
        """Stop the proxy server."""
        ...

    # Endpoints: POST /v1/messages, GET /health, POST /api/shutdown
```

**Behavior:**
- **API key replacement**: Replaces `x-api-key` header with `config.upstream_api_key` before forwarding
- **Model override**: If `config.upstream_model` is set, replaces `model` field in request body; if `None`, keeps original model from Claude Code
- **Headers forwarded**: `anthropic-version`, `content-type` forwarded as-is
- **Streaming**: Full SSE passthrough - events forwarded without modification
- **Logging**: Requests/responses logged to `debug_dir` in same format as OpenAI proxy

2. Add tests: `tests/gateway/test_passthrough_proxy.py`

| Test | Description |
|------|-------------|
| `test_passthrough_forward` | Request forwarded correctly to upstream |
| `test_passthrough_api_key_replaced` | `x-api-key` header replaced with config value |
| `test_passthrough_model_override` | Model replaced when `config.upstream_model` is set |
| `test_passthrough_model_preserve` | Model kept when `config.upstream_model=None` |
| `test_passthrough_streaming` | SSE events forwarded correctly |
| `test_passthrough_logging` | Requests logged to `debug_dir` |
| `test_passthrough_upstream_error` | 5xx from upstream surfaced correctly |

### Phase 2: ProxyManager

1. Create `src/nerve/server/proxy_manager.py`
   - `ProviderConfig` dataclass (already defined in Components section)
   - `ProxyInstance` dataclass
   - `ProxyManager` class with start/stop/get methods
   - Port auto-assignment with `socket.bind(("", 0))`
   - Health check polling
   - Selects correct proxy type based on `config.needs_transform`

2. Add tests: `tests/server/test_proxy_manager.py`
   - Test start/stop lifecycle
   - Test multiple concurrent proxies
   - Test health check timeout
   - Test cleanup on stop_all
   - Test correct proxy type selection (passthrough vs transform)

### Phase 3: NerveEngine Integration

1. Modify `src/nerve/server/engine.py`
   - Add `_proxy_manager` field
   - Update `_create_node()` to handle provider parameter
   - Update `_delete_node()` to stop proxy
   - Update `stop()` to cleanup all proxies

2. Update `src/nerve/server/protocols.py`
   - Add provider-related fields to CreateNode command params

3. Add tests: `tests/server/test_engine_proxy.py`
   - Test node creation with provider=openai
   - Test node deletion stops proxy
   - Test engine stop cleans up all proxies

### Phase 4: ClaudeWezTermNode Changes

1. Modify `src/nerve/core/nodes/terminal/claude_wezterm_node.py`
   - Add `proxy_url` parameter to `create()`
   - Export `ANTHROPIC_BASE_URL` if proxy_url is set

2. Add tests: `tests/core/nodes/test_claude_wezterm_proxy.py`
   - Test node creation with proxy_url
   - Verify env var is exported

### Phase 5: SDK/CLI Integration

1. Update `src/nerve/frontends/sdk/client.py`

```python
async def create_node(
    self,
    name: str,
    command: str | list[str] | None = None,
    cwd: str | None = None,
    backend: str = "pty",                      # DEFAULT: preserves existing behavior
    provider: ProviderConfig | None = None,    # DEFAULT: no proxy (direct to Anthropic)
    response_timeout: float = 1800.0,
    ready_timeout: float = 60.0,
) -> RemoteNode:
```

2. Update `src/nerve/frontends/cli/server/node.py`
   - Add CLI flags for provider configuration

3. Add integration tests

**Backward Compatibility:**

All new parameters must default to values that preserve existing behavior:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `backend` | `"pty"` | Current SDK default - creates PTYNode |
| `provider` | `None` | No proxy, direct to Anthropic |
| `proxy_url` | `None` | No env var override in node |

**Existing behavior preserved:**

| Scenario | Before | After |
|----------|--------|-------|
| `client.create_node("x", "bash")` | PTYNode, direct | PTYNode, direct ✓ |
| `nerve node create x --command bash` | PTYNode | PTYNode ✓ |
| `ClaudeWezTermNode.create(...)` no provider | Direct to Anthropic | Direct to Anthropic ✓ |
| Engine with no provider param | Direct to Anthropic | Direct to Anthropic ✓ |

---

## Testing Strategy

### Unit Tests

| Component | Test File | Coverage |
|-----------|-----------|----------|
| PassthroughProxyServer | `test_passthrough_proxy.py` | forward, api key, model override, streaming, logging |
| ProxyManager | `test_proxy_manager.py` | start, stop, port assignment, health check, proxy type selection |
| NerveEngine | `test_engine_proxy.py` | create with provider, delete cleanup |
| ClaudeWezTermNode | `test_claude_wezterm_proxy.py` | proxy_url env var |

### Integration Tests

| Scenario | Description |
|----------|-------------|
| Full lifecycle (openai) | Create node with `api_format=openai` → send message → delete node |
| Full lifecycle (passthrough) | Create node with `api_format=anthropic` → send message → delete node |
| Passthrough logging | Verify requests logged to debug_dir for passthrough proxy |
| Multiple nodes | Create 2 nodes with different providers, verify separate ports |
| **Node isolation** | Create 2 nodes → delete node1 → verify node2's proxy still works |
| **Port reuse** | Create node → delete node → create new node → verify can reuse freed port |
| Failure recovery | Proxy dies → node should error gracefully |
| Engine shutdown | Stop engine → all proxies cleaned up |

### Manual Testing

1. Start nerve server
2. Create node with `provider=openai`
3. Verify proxy is running (`curl http://127.0.0.1:<port>/health`)
4. Send message through node
5. Check `.nerve/logs/` for request traces
6. Delete node
7. Verify proxy is stopped

---

## Future Considerations

### Additional API Formats

Currently supported:
- No provider config → Direct to Anthropic (no proxy)
- `api_format="anthropic"` → Passthrough proxy
- `api_format="openai"` → Transform proxy (Anthropic ↔ OpenAI)

Future formats that would need new proxy implementations:

```python
# Future: Gemini format
node = await client.create_node(
    "claude-gemini",
    backend="claude-wezterm",
    command="claude --dangerously-skip-permissions",
    provider=ProviderConfig(
        api_format="gemini",  # NEW format
        base_url="https://generativelanguage.googleapis.com/v1",
        api_key="...",
        model="gemini-pro",
    ),
)
# Would need: GeminiTransformProxy (Anthropic ↔ Gemini)
```

### Proxy Pooling (Not in Scope)

For high-throughput scenarios, we might want:
- Shared proxy pools per provider/key combination
- Connection reuse across nodes
- Load balancing

This is out of scope for initial implementation.

### Credentials Management (Not in Scope)

Currently, API keys are passed directly. Future improvements:
- Integration with secrets managers
- Environment variable references in config
- Key rotation support

---

## Error Handling

Errors from proxies must be surfaced clearly to users with actionable messages.

| Error | Exception Type | User-Facing Message |
|-------|----------------|---------------------|
| Missing provider config keys | `ValueError` | `Provider config missing required keys: {missing}. Required: {required}` |
| Port allocation retry exhausted | `ProxyStartError` | `Failed to start proxy for node '{node_id}' after {max_retries} attempts` |
| Proxy fails to start | `ProxyStartError` | `Failed to start proxy: {reason}` |
| Health check timeout | `ProxyHealthError` | `Health check timeout on port {port} (attempt {n}/{max})` |
| Upstream unreachable | `UpstreamError` | `Cannot reach {base_url}: {reason}` |
| Upstream 401 | `AuthenticationError` | `Invalid API key for {base_url}` |
| Upstream 429 | `RateLimitError` | `Rate limited by provider` |
| Upstream 5xx | `UpstreamError` | `Upstream server error: {status} {message}` |
| Proxy crashes mid-session | `ProxyDisconnectedError` | `Proxy disconnected unexpectedly` |

**Error propagation:**
1. Proxy catches upstream errors and maps to appropriate Anthropic error format
2. Node receives error in Anthropic format (same as if talking to real Anthropic)
3. Claude Code sees error and can retry or surface to user
4. Proxy logs error to debug_dir for debugging

**Retry behavior:**
- Port allocation retries up to 5 times with exponential backoff (0.1s, 0.2s, 0.3s, 0.4s, 0.5s)
- Handles both EADDRINUSE (port taken) and health check timeouts
- Logs each retry attempt for diagnostics

---

## Security and Robustness

### Port Allocation Race Condition (TOCTOU)

**Problem**: The original implementation had a TOCTOU (Time-Of-Check-Time-Of-Use) race condition where `_find_free_port()` would bind to port 0, get an assigned port, close the socket, and return the port number. Between closing the socket and the proxy binding to that port, another process could grab it.

**Solution**: Implemented retry logic in `ProxyManager.start_proxy()`:

```python
# Retry up to 5 times to handle TOCTOU races
for attempt in range(max_retries):
    port = _find_free_port()

    try:
        # Create and start proxy
        server = await self._create_proxy(port, config)
        task = asyncio.create_task(server.serve())
        await self._wait_for_health(port)
        return instance  # Success!

    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            # Port was taken between check and use - retry
            logger.debug(f"Port {port} already in use (TOCTOU race), retrying...")
            await asyncio.sleep(0.1 * (attempt + 1))  # Backoff
            continue
        raise
```

**Benefits**:
- Handles race conditions gracefully with automatic retry
- Exponential backoff prevents tight retry loops
- Clear logging for diagnostics
- Fails with clear error after max retries

### Provider Configuration Validation

**Problem**: Missing required keys in provider configuration (e.g., `api_format`, `base_url`, `api_key`) would raise unclear `KeyError` exceptions.

**Solution**: Added validation in `NerveEngine._create_node()` before constructing `ProviderConfig`:

```python
# Validate required keys are present
required_keys = ["api_format", "base_url", "api_key"]
missing = [k for k in required_keys if k not in provider_dict]
if missing:
    raise ValueError(
        f"Provider config missing required keys: {', '.join(missing)}. "
        f"Required: {', '.join(required_keys)}"
    )
```

**Benefits**:
- Clear, actionable error messages
- Lists all missing keys at once (not one at a time)
- Fails fast before attempting proxy creation

### Shell Injection Prevention

**Problem**: The `proxy_url` was directly interpolated into a shell `export` command without escaping, creating a potential shell injection vulnerability:

```python
# UNSAFE (before):
export_cmd = f"export ANTHROPIC_BASE_URL={proxy_url}"
```

While `proxy_url` is internally generated (`http://127.0.0.1:{port}`), defense-in-depth requires proper escaping.

**Solution**: Added `shlex.quote()` to properly escape the value:

```python
# SAFE (after):
import shlex
export_cmd = f"export ANTHROPIC_BASE_URL={shlex.quote(proxy_url)}"
```

**Benefits**:
- Prevents shell injection even if `proxy_url` generation changes
- Defense-in-depth security posture
- No performance impact
- Follows security best practices

---

## Success Criteria

1. **Existing behavior unchanged**: Creating node without `provider` config works exactly as before (direct to Anthropic, no proxy)
2. **OpenAI support**: User can create node with `api_format="openai"` and it works with GPT-4
3. **Anthropic-compatible support**: User can create node with `api_format="anthropic"` for other Anthropic-format APIs (GLM-4.5, etc.)
4. **Same node API**: All nodes work identically regardless of backend (same `send()`, `execute()` methods)
5. **Automatic lifecycle**: Proxy starts before node, stops when node is deleted
6. **Multiple nodes**: Different nodes can use different providers/keys simultaneously
7. **Request logging**: All proxied requests are logged to `.nerve/logs/`
8. **Error handling**: Errors from proxy are surfaced clearly to user
