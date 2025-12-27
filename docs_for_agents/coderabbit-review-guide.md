# CodeRabbit Review Guide

This guide documents how to retrieve and process CodeRabbit code reviews using two methods:
1. **CodeRabbit CLI** - For fresh reviews of uncommitted or committed changes
2. **GitHub PR Comments** - For reviews already posted to a pull request

## Method 1: CodeRabbit CLI

### Installation
```bash
# Install via npm
npm install -g coderabbit
```

### Authentication
```bash
coderabbit auth
```

### Running Reviews

#### Review uncommitted changes
```bash
coderabbit review --type uncommitted --plain
```

#### Review committed changes against a base branch
```bash
coderabbit review --type committed --base main --plain
```

#### Review all changes (both committed and uncommitted)
```bash
coderabbit review --type all --plain
```

### CLI Options
- `--plain` - Output in plain text format (non-interactive)
- `--type <type>` - Review type: `all`, `committed`, `uncommitted` (default: `all`)
- `--base <branch>` - Base branch for comparison
- `--config <files>` - Additional instructions (e.g., `claude.md`, `coderabbit.yaml`)

### Saving Output for Reference
```bash
coderabbit review --type committed --base main --plain 2>&1 | tee /tmp/coderabbit-review.txt
```

---

## Method 2: GitHub PR Comments

The CLI runs a fresh review, but **GitHub PR comments may contain different issues** because:
- PR comments are generated when commits are pushed
- CLI reviews analyze the current state
- Incremental reviews on GitHub accumulate across multiple pushes

### Get PR Number
```bash
gh pr view --json number -q '.number'
```

### Fetch All Review Comments
```bash
# Get PR number first
PR_NUM=$(gh pr view --json number -q '.number')

# Fetch and parse review comments
gh api "repos/OWNER/REPO/pulls/${PR_NUM}/comments" 2>&1 | python3 -c "
import json, sys
data = json.load(sys.stdin)
for c in data:
    print(f\"File: {c['path']}\")
    print(f\"Line: {c.get('line') or c.get('original_line')}\")
    body = c['body'][:400].replace('\n', ' ')
    print(f\"Body: {body}...\")
    print('---')
"
```

### One-liner for Current Repo
```bash
gh api "repos/$(gh repo view --json nameWithOwner -q '.nameWithOwner')/pulls/$(gh pr view --json number -q '.number')/comments" | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    print(f\"File: {c['path']}\nLine: {c.get('line') or c.get('original_line')}\nBody: {c['body'][:300]}...\n---\")
"
```

---

## Understanding Issue Severity

CodeRabbit categorizes issues by type and severity:

### Issue Types
| Type | Description |
|------|-------------|
| `potential_issue` | Bugs, crashes, security issues - **fix these** |
| `refactor_suggestion` | Code quality improvements |
| `nitpick` | Style, naming, minor improvements - optional |

### Severity Levels (in PR comments)
| Emoji | Level | Action |
|-------|-------|--------|
| 🔴 Critical | Must fix before merge |
| 🟠 Major | Should fix - potential bugs |
| 🟡 Minor | Good to fix - edge cases, typos |
| 🔵 Trivial | Optional - style nitpicks |

---

## Common Issue Categories

### 1. File Handle Leaks
**Problem:** `json.load(open(f))` without context manager
```python
# Bad
data = json.load(open(file_path))

# Good
with open(file_path, encoding="utf-8") as f:
    data = json.load(f)
```

### 2. Missing Encoding
**Problem:** `open()` without explicit encoding
```python
# Bad
with open(file_path) as f:

# Good
with open(file_path, encoding="utf-8") as f:
```

### 3. Bare Exception Handling
**Problem:** `except Exception:` catches too much
```python
# Bad
except Exception:
    return False

# Good
except (OSError, ValueError, json.JSONDecodeError):
    return False
```

### 4. Edge Case Crashes
**Problem:** Not handling empty lists, None values, etc.
```python
# Bad - crashes if list is empty
if items[-1].value == expected:

# Good
if items and items[-1].value == expected:
```

### 5. Unused Variables
**Problem:** Assigned but never used
```python
# Bad
result = compute_value()  # never used

# Good - just remove the line
```

### 6. Typos in User-Facing Text
**Problem:** Spelling errors in prompts, messages
```python
# Bad
"Enusre the value is correct"

# Good
"Ensure the value is correct"
```

### 7. Usage Documentation Mismatch
**Problem:** Docstring says one thing, code requires another
```python
# Bad - relative imports require module execution
"""
Usage:
    python path/to/script.py
"""
from .module import thing

# Good
"""
Usage:
    python -m path.to.script
"""
from .module import thing
```

---

## Recommended Workflow

1. **Before creating PR:** Run CLI review on uncommitted changes
   ```bash
   coderabbit review --type uncommitted --plain
   ```

2. **After pushing:** Check GitHub PR comments for any issues the CLI missed
   ```bash
   gh api "repos/OWNER/REPO/pulls/NUMBER/comments" | python3 -c "..."
   ```

3. **Prioritize fixes:**
   - 🔴 Critical / 🟠 Major `potential_issue` → Always fix
   - 🟡 Minor `potential_issue` → Fix typos, edge cases
   - `refactor_suggestion` → Consider if time permits
   - `nitpick` → Optional, skip for local tools

4. **Re-run review after fixes** to verify issues are resolved

---

## Notes

- **CLI vs PR comments may differ** - Always check both sources
- **Examples with hardcoded paths** - Often intentional, skip unless it's a library
- **Thread safety nitpicks** - Usually fine for single-user CLI tools
- **Mutable globals in examples** - Nitpick, not a bug for demo code
