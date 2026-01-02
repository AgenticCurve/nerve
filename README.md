Hello World

## Suggestion Tracking (ML Training Data)

The Commander TUI can record suggestion interactions for ML training and analytics.

### Enable Recording

```bash
export NERVE_SUGGESTION_HISTORY=1
nerve commander
```

### What's Captured

| Data | Storage | Purpose |
|------|---------|---------|
| Suggestions offered | Block metadata | Timeline persistence |
| User cycling behavior | Block metadata | Which suggestions were viewed |
| Match type (exact/partial/prefix/none) | Block metadata | Acceptance classification |
| Full LLM request/response | JSONL file | ML training |
| Context sent to suggestion node | JSONL file | ML training |

### Data Location

```
~/.nerve/session_history/<server>/<session>/suggestion_history.jsonl
```

Each line is a self-contained JSON record suitable for ML training pipelines.
