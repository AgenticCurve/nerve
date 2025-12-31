# Testing Graph in Commander

Simple test for seamless graph integration where graphs look identical to nodes.

## Quick Start

Run the setup helper:
```bash
python examples/test_graph_in_commander.py
```

Or follow the manual steps below.

## Step-by-Step Setup

### 1. Start the nerve server

```bash
nerve server start graph-test
```

### 2. Create a session

```bash
nerve server session create default --server graph-test
```

### 3. Create two Claude nodes

```bash
nerve server node create claude1 \
  --server graph-test \
  --session default \
  --type ClaudeWezTermNode \
  --command claude

nerve server node create claude2 \
  --server graph-test \
  --session default \
  --type ClaudeWezTermNode \
  --command claude
```

### 4. Create the graph

**Option A: Using the helper script (recommended)**

```bash
python examples/test_graph_in_commander.py
```

This script uses the new CREATE_GRAPH API to register the graph with steps in one command.

**Option B: Via REPL**

```bash
nerve repl --server graph-test --session default
```

Then in the REPL:
```
add pick_number claude1 "Pick a random number between 1 and 100. Reply with ONLY the number."
add double_it claude2 "Double this number: {pick_number}. Reply with ONLY the doubled number." --depends-on pick_number
save number_doubler --output double_it
quit
```

Both create a graph called `number_doubler` that:
- Has `claude1` pick a random number
- Has `claude2` double it
- Returns only the final doubled number

### 5. Launch commander

```bash
nerve commander /tmp/nerve-graph-test.sock default
```

## Test Commands in Commander

### Discovery (explicit inspection)

```
:entities              # Shows ALL (nodes + graphs)
:nodes                 # Shows ONLY nodes (claude1, claude2)
:graphs                # Shows ONLY graphs (number_doubler)
:info number_doubler   # Graph details
```

**Expected**: Graph appears in lists when asked, but not obvious otherwise.

### Seamless Execution (transparency test)

```
@number_doubler
```

**Expected**:
- Executes like a node
- Shows ONLY the final doubled number
- No indication it's a graph
- Block looks identical to node blocks

### Comparison Test

```
@claude1 Say hello
@claude2 What is 2+2?
@number_doubler
:timeline
```

**Expected**: All three blocks look nearly identical.

### Variable Expansion

```
@number_doubler
:::N                      # Final output only
:::N['output']            # Same
:::N['attributes']        # See internal steps (power users)
```

**Expected**:
- `:::N` returns just the number (transparent)
- `:::N['attributes']` shows execution details (explicit)

## What You're Testing

✅ **Transparency**: Can't tell `@number_doubler` is a graph from usage
✅ **Discovery**: Only `:graphs` and `:info` reveal it's a graph
✅ **Visual Identity**: Graph blocks styled like node blocks
✅ **Variable Expansion**: Works the same

## Cleanup

```bash
nerve server stop graph-test
```
