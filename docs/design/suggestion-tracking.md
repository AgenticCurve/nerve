# Suggestion Tracking System Design

## Purpose

Capture comprehensive data about the suggestion system to enable:
1. **ML Training** - Fine-tune suggestion models on real user behavior
2. **Analytics** - Understand suggestion effectiveness
3. **Debugging** - Diagnose why suggestions fail

> **Privacy Note:** This system captures user input/output data. JSONL logging
> should be opt-in and users should be aware that their commands are being recorded.

---

## Mental Model

```
Block N completes
    ↓
fetch() called → LLM generates suggestions → stored as "pending record"
    ↓
User sees suggestions in placeholder (first suggestion auto-displayed)
    ↓
User may cycle through suggestions (Tab/Shift-Tab)
    ↓
User submits input → becomes Block N+1
    ↓
Finalize record: link to Block N+1, determine if suggestion was used
```

**Key insight:** Suggestions belong to the NEXT block (the one created from user input), not the block that triggered the fetch.

---

## Data Model

### SuggestionRecord

```python
@dataclass
class SuggestionRecord:
    """Complete record of suggestion generation and user response.

    Captures the full ML training pipeline:
    - What context was sent to the LLM
    - What the LLM returned
    - How the user interacted with suggestions
    - What the user ultimately did
    """

    # === Context Sent to LLM ===
    context: dict[str, Any]
    # Structure:
    # {
    #     "nodes": ["claude", "bash", ...],
    #     "graphs": ["pipeline", ...],
    #     "workflows": ["debug", ...],
    #     "blocks": [
    #         {"input": "...", "output": "...", "success": True, "error": None},
    #         ...
    #     ],
    #     "cwd": "/path/to/project"
    # }

    # === LLM Request (what was sent to the model) ===
    llm_request: dict[str, Any] | None = None
    # Structure:
    # {
    #     "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
    #     "model": "gpt-4o-mini",
    #     "temperature": 0.7,
    #     "max_tokens": 256,
    #     "top_p": 1.0,
    #     ... any other params passed to the LLM
    # }

    # === LLM Response (what came back) ===
    llm_response: dict[str, Any] | None = None
    # Structure:
    # {
    #     "raw_content": "1. @claude explain this error\n2. @bash cat logs.txt\n...",
    #     "model": "gpt-4o-mini",           # Actual model used (may differ from requested)
    #     "usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
    #     "finish_reason": "stop",
    #     "latency_ms": 234.5,
    # }

    # === Suggestion Node Metadata ===
    suggestion_node_version: str | None = None  # Version of suggestion prompt/node

    # === Suggestions Returned ===
    suggestions: list[str]                     # Parsed suggestions from LLM

    # === User Viewing Behavior ===
    cycle_count: int = 0                       # How many times Tab/Shift-Tab pressed
    viewed_indices: list[int] = field(default_factory=list)
    # ^ Order preserved, may contain duplicates if user cycled back.
    #   Example: [0, 1, 2, 1, 0] means user cycled forward then back.
    #   Repeated indices indicate indecision - valuable signal.
    displayed_index_at_submit: int = -1        # Which suggestion was showing (-1 = none/hint)

    # === User Selection ===
    accepted_index: int | None = None          # Which suggestion was picked (None = typed manually)
    actual_input: str = ""                     # What user actually submitted
    match_type: str = "none"                   # "exact", "partial", "prefix", "none"

    # === Timing ===
    fetch_start_ts: float = 0.0                # When fetch() started
    fetch_end_ts: float = 0.0                  # When suggestions arrived
    submit_ts: float = 0.0                     # When user submitted input
    time_to_action_ms: float = 0.0             # submit - fetch_end (user thinking time)

    # === Session Context ===
    session_name: str = ""
    server_name: str = ""                      # For multi-server deployments
    trigger_block_number: int = -1             # Block that triggered fetch
    result_block_number: int | None = None     # Block created from user input (None for : commands)
    context_block_count: int = 0               # How many blocks were in context
```

### Match Types

| `match_type` | Meaning |
|--------------|---------|
| `"exact"` | User accepted suggestion verbatim |
| `"partial"` | User started with suggestion, modified it |
| `"prefix"` | User typed prefix of a suggestion (word-by-word accept) |
| `"none"` | User typed something completely different |

---

## Storage Strategy

### 1. Block Metadata (Lightweight - Persists with Timeline)

Block metadata must stay **lightweight** to avoid slowing down the TUI.
Only store essential outcome data, not the full LLM request/response.

```python
# Lightweight record for block metadata
block.metadata["suggestion"] = {
    "suggestions": ["@claude explain", "@bash ls"],  # What was offered
    "accepted_index": 0,                              # Which one picked (None = typed manually)
    "match_type": "exact",                            # exact/partial/prefix/none
    "cycle_count": 2,                                 # How much they browsed
    "time_to_action_ms": 1234.5,                      # Decision time
}
```

**What's NOT in block metadata:**
- ❌ Full context (blocks, nodes, etc.) - already in timeline
- ❌ LLM request/response - too heavy, goes to JSONL only
- ❌ Raw LLM output - too heavy

**Pros:**
- Fast - minimal memory overhead
- Automatically persists with `:export`
- Enough to answer "was this suggestion-assisted?"

### 2. JSONL File (Full Data - Self-Contained ML Training)

**Location:** `~/.nerve/session_history/<server-name>/<session-name>/suggestion_history.jsonl`

Example paths:
- `~/.nerve/session_history/local/my-project/suggestion_history.jsonl`
- `~/.nerve/session_history/prod-server/debug-session/suggestion_history.jsonl`

Each line is a complete, self-contained training record:

```jsonl
{
  "ts": 1704067200.0,
  "session": "my-project",
  "server": "local",
  "trigger_block": 5,
  "result_block": 6,

  "context": {
    "nodes": ["claude", "bash", "python"],
    "graphs": ["pipeline"],
    "workflows": ["debug"],
    "blocks": [
      {"input": "@claude explain async", "output": "Async is...", "success": true},
      {"input": "@bash ls", "output": "file1.py\nfile2.py", "success": true}
    ],
    "cwd": "/home/user/project"
  },

  "llm_request": {
    "messages": [
      {"role": "system", "content": "You are a command suggestion assistant..."},
      {"role": "user", "content": "{\"nodes\": [...], \"blocks\": [...]}"}
    ],
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 256
  },

  "llm_response": {
    "raw_content": "1. @claude explain this error\n2. @bash cat logs.txt\n3. @python debug.py",
    "model": "gpt-4o-mini",
    "usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
    "finish_reason": "stop",
    "latency_ms": 234.5
  },

  "suggestions": ["@claude explain this error", "@bash cat logs.txt", "@python debug.py"],
  "suggestion_node_version": "v1.0",

  "viewed_indices": [0, 1, 0],
  "cycle_count": 2,
  "displayed_index_at_submit": 0,
  "accepted_index": 0,
  "actual_input": "@claude explain this error",
  "match_type": "exact",

  "time_to_action_ms": 1234.5
}
```

**Design Principle:** JSONL is the **primary ML training artifact**. Each record must be
completely self-contained so ML pipelines can process it without external dependencies.
This includes:
- Full context (not a hash)
- Complete LLM request (messages, model, params)
- Complete LLM response (raw output, usage stats, latency)
- User behavior and outcome

**Pros:**
- Append-only (O(1) writes)
- Each line is a complete training example
- No cross-referencing needed - process line by line
- Can recreate the exact LLM call for debugging/replay
- Aggregates across sessions for large-scale training

**Toggle:** Environment variable `NERVE_SUGGESTION_HISTORY=1` or config setting

---

## Implementation Flow

### 0. SuggestionNode Returns LLM Debug Info

The SuggestionNode must return not just the suggestions, but the full LLM interaction:

```python
# In SuggestionNode.execute()
async def execute(self, input_text: str) -> dict[str, Any]:
    context = json.loads(input_text)

    # Build the messages
    messages = [
        {"role": "system", "content": self.system_prompt},
        {"role": "user", "content": json.dumps(context)},
    ]

    # Prepare request params
    request_params = {
        "model": self.model,
        "temperature": self.temperature,
        "max_tokens": self.max_tokens,
        # ... any other params
    }

    start_time = time.monotonic()
    response = await self.llm_client.chat(messages=messages, **request_params)
    latency_ms = (time.monotonic() - start_time) * 1000

    suggestions = self._parse_suggestions(response.content)

    return {
        "success": True,
        "output": suggestions,
        "llm_debug": {
            "request": {
                "messages": messages,
                **request_params,
            },
            "response": {
                "raw_content": response.content,
                "model": response.model,  # Actual model used
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "finish_reason": response.finish_reason,
                "latency_ms": latency_ms,
            },
            "version": "v1.0",  # Prompt version for A/B testing
        }
    }
```

### 1. When Suggestions Arrive (`fetch()` completes)

```python
# In SuggestionManager.fetch()
async def fetch(self) -> None:
    context = self._gather_context()
    fetch_start = time.monotonic()

    result = await self.adapter.execute_on_node("suggestions", json.dumps(context))

    fetch_end = time.monotonic()

    if result.get("success"):
        self.suggestions = result.get("output", [])
        self.current_idx = 0

        # Extract LLM debug info if available
        llm_debug = result.get("llm_debug", {})

        # Create pending record with full LLM interaction
        self._pending_record = SuggestionRecord(
            context=context,
            suggestions=self.suggestions,

            # LLM request/response for ML training
            llm_request=llm_debug.get("request"),
            llm_response=llm_debug.get("response"),
            suggestion_node_version=llm_debug.get("version"),

            fetch_start_ts=fetch_start,
            fetch_end_ts=fetch_end,
            context_block_count=len(context.get("blocks", [])),
            session_name=self._session_name,
            server_name=self._server_name,
            trigger_block_number=len(self.timeline.blocks) - 1,
            viewed_indices=[0],  # First suggestion is auto-displayed
        )
```

### 2. When User Cycles Through Suggestions

```python
# In SuggestionManager.cycle_next()
def cycle_next(self) -> None:
    if not self.suggestions:
        return

    # Update index FIRST
    if self.current_idx < 0:
        self.current_idx = 0
    else:
        self.current_idx = (self.current_idx + 1) % len(self.suggestions)

    # THEN track what user is NOW viewing
    if self._pending_record:
        self._pending_record.cycle_count += 1
        self._pending_record.viewed_indices.append(self.current_idx)


# In SuggestionManager.cycle_prev()
def cycle_prev(self) -> None:
    if not self.suggestions:
        return

    # Update index FIRST
    if self.current_idx < 0:
        self.current_idx = len(self.suggestions) - 1
    else:
        self.current_idx = (self.current_idx - 1) % len(self.suggestions)

    # THEN track what user is NOW viewing
    if self._pending_record:
        self._pending_record.cycle_count += 1
        self._pending_record.viewed_indices.append(self.current_idx)
```

### 3. When User Submits Input (`dispatch()` called)

```python
# In SuggestionManager
def finalize_record(self, actual_input: str, result_block_number: int | None) -> SuggestionRecord | None:
    """Finalize pending record with user's actual action.

    Args:
        actual_input: What the user typed/submitted.
        result_block_number: Block number created (None for : commands).

    Returns:
        Finalized record, or None if no pending record or input is a : command.
    """
    if self._pending_record is None:
        return None

    # Skip recording for : commands - they don't create blocks
    # and aren't what suggestions are trying to predict
    if actual_input.startswith(":"):
        self._pending_record = None
        return None

    record = self._pending_record
    record.actual_input = actual_input
    record.submit_ts = time.monotonic()
    record.time_to_action_ms = (record.submit_ts - record.fetch_end_ts) * 1000
    record.displayed_index_at_submit = self.current_idx
    record.result_block_number = result_block_number

    # Determine match type
    record.match_type, record.accepted_index = self._classify_match(
        actual_input, record.suggestions
    )

    self._pending_record = None
    return record

def _classify_match(self, actual: str, suggestions: list[str]) -> tuple[str, int | None]:
    """Classify how user input relates to suggestions."""
    for i, suggestion in enumerate(suggestions):
        if actual == suggestion:
            return ("exact", i)
        if actual.startswith(suggestion):
            return ("partial", i)  # User extended a suggestion
        if suggestion.startswith(actual):
            return ("prefix", i)   # User accepted prefix (word-by-word)
    return ("none", None)
```

### 4. In InputDispatcher

```python
# In InputDispatcher.dispatch()
async def dispatch(self, user_input: str) -> None:
    cmd = self.commander

    # Finalize suggestion record BEFORE routing
    # Returns None for : commands (we don't track those)
    suggestion_record = cmd._suggestions.finalize_record(user_input, result_block_number=None)

    # ... existing routing logic ...

    # After block is created (in handle_entity_message, handle_python, etc.):
    if suggestion_record:
        suggestion_record.result_block_number = block.number

        # LIGHTWEIGHT metadata for block (no LLM data - keeps TUI fast)
        block.metadata["suggestion"] = {
            "suggestions": suggestion_record.suggestions,
            "accepted_index": suggestion_record.accepted_index,
            "match_type": suggestion_record.match_type,
            "cycle_count": suggestion_record.cycle_count,
            "time_to_action_ms": suggestion_record.time_to_action_ms,
        }

        # FULL record to JSONL (fire-and-forget async to avoid blocking TUI)
        if settings.suggestion_history_enabled:
            asyncio.create_task(append_to_history_async(suggestion_record))
```

---

## Metrics & Analysis

### Key Questions This Data Answers

| Question | Fields Used |
|----------|-------------|
| What % of suggestions are accepted? | `accepted_index`, `match_type` |
| How long do users think before acting? | `time_to_action_ms` |
| Do users browse suggestions before deciding? | `cycle_count`, `viewed_indices` |
| Which suggestion position is most accepted? | `accepted_index` distribution |
| Does more context = better suggestions? | `context_block_count` vs `match_type` |
| When do users ignore suggestions entirely? | `match_type == "none"` cases |

### Negative Signals (Valuable for Training)

1. **Viewed but rejected:** `viewed_indices` contains index, but `accepted_index` is different/None
2. **Long thinking time + rejection:** `time_to_action_ms` high AND `match_type == "none"`
3. **Cycled many times:** `cycle_count` high (suggestions weren't helpful)
4. **Partial match:** User had to modify suggestion (not quite right)
5. **Cycled back:** `viewed_indices` has duplicates (e.g., `[0,1,2,1,0]`) - indecision

### ML Training Use Cases

With the self-contained JSONL, you can:

1. **Fine-tune on accepted suggestions**
   - Input: context blocks
   - Output: `actual_input` where `match_type == "exact"`

2. **Learn to rank suggestions**
   - Use `accepted_index` to train ranking models
   - Position bias analysis (is suggestion #1 always picked?)

3. **Preference learning (DPO/RLHF)**
   - Positive: accepted suggestions
   - Negative: viewed but rejected suggestions

4. **Temperature/param optimization**
   - Correlate `llm_request.temperature` with acceptance rate
   - Find optimal params per context type

5. **Prompt engineering**
   - Compare `suggestion_node_version` performance
   - A/B test system prompts

6. **Cost optimization**
   - Analyze `llm_response.usage` vs acceptance rate
   - Find the minimum tokens needed for good suggestions

---

## Future Enhancements

### 1. Embeddings for Similarity Analysis

Store embedding of context + suggestions for clustering analysis.
Useful for finding similar contexts that led to different outcomes.

### 2. Per-Suggestion Dwell Time

Currently we track total `time_to_action_ms`. We could track how long
each suggestion was displayed before the user cycled away.

### 3. Partial Input Tracking

Track what the user typed character-by-character to understand
how suggestions influenced their typing behavior.

---

## File Locations

| File | Purpose |
|------|---------|
| `SuggestionNode` (server-side) | Return `llm_debug` with full request/response |
| `suggestion_manager.py` | Add `_pending_record`, `finalize_record()`, cycling tracking |
| `suggestion_record.py` | New file with `SuggestionRecord` dataclass |
| `suggestion_history.py` | New file with JSONL append/read utilities |
| `input_dispatcher.py` | Wire up `finalize_record()` and block metadata |
| `blocks.py` | Already has `metadata` field - no changes needed |

---

## Configuration

```python
# Environment variables or config file
NERVE_SUGGESTION_HISTORY = "1"  # Enable JSONL logging (opt-in for privacy)

# Path structure (not configurable, follows session organization)
# ~/.nerve/session_history/<server-name>/<session-name>/suggestion_history.jsonl
```

**Benefits of per-session storage:**
- Easy to delete a session's history
- No single giant file
- Natural grouping by server/session
- Can aggregate across sessions for training: `cat ~/.nerve/session_history/*/*/suggestion_history.jsonl`

---

## Summary

| Aspect | Decision |
|--------|----------|
| **ML training storage** | JSONL file - full self-contained records |
| **Timeline storage** | `Block.metadata["suggestion"]` - lightweight (no LLM data) |
| Timing model | Suggestions belong to NEXT block |
| Cycling tracking | Yes - `cycle_count`, `viewed_indices` (with duplicates) |
| First suggestion | Auto-added to `viewed_indices` on fetch |
| : commands | Skipped (not tracked) |
| Context in JSONL | Full context (self-contained for ML) |
| Context in block metadata | None (already in timeline) |
| LLM request/response | JSONL only (too heavy for block metadata) |
| Match classification | exact / partial / prefix / none |
| Opt-in | `NERVE_SUGGESTION_HISTORY=1` to enable JSONL logging |
