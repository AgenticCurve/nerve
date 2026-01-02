"""Driver-Navigator pair programming workspace.

This workspace implements the driver-navigator pair programming pattern with
two Claude instances:
- Driver: Writes the code, focuses on implementation details
- Navigator: Reviews code, thinks strategically, catches issues

Also includes:
- Suggestions node for AI-powered command suggestions
- Bug Hunter workflow for thorough code analysis
- Verify Refactoring workflow for regression detection

Usage:
    # Start the server first
    nerve server start

    # Then start commander with this config
    nerve commander --config examples/workspace/driver_navigator/main.py

The driver and navigator will be initialized with their roles and can then
collaborate on coding tasks.
"""

import os
import sys
from pathlib import Path

# Add this directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from workflow_bug_hunter import bug_hunter_workflow
from workflow_verify_refactoring import verify_refactoring_workflow

from nerve.core.nodes.llm.suggestion import SuggestionNode
from nerve.core.nodes.terminal import ClaudeWezTermNode
from nerve.core.workflow import Workflow

# =============================================================================
# Driver Node - Writes code, implements solutions
# =============================================================================

cwd = os.getcwd()

driver = await ClaudeWezTermNode.create(  # noqa: F704
    id="driver",
    session=session,  # noqa: F821
    command=f"cd {cwd} && claude --dangerously-skip-permissions",
)
print(f"Created node: driver (WezTerm) in {cwd}")

# =============================================================================
# Navigator Node - Reviews, strategizes, catches issues
# =============================================================================

navigator = await ClaudeWezTermNode.create(  # noqa: F704
    id="navigator",
    session=session,  # noqa: F821
    command=f"cd {cwd} && claude --dangerously-skip-permissions",
)
print(f"Created node: navigator (WezTerm) in {cwd}")

# =============================================================================
# Suggestions Node - AI-powered command suggestions
# =============================================================================

SuggestionNode(
    id="suggestions",
    session=session,  # noqa: F821
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    model="google/gemini-3-flash-preview",
    debug_dir="/tmp/nerve-debug",
)
print("Created node: suggestions (SuggestionNode)")

# =============================================================================
# Bug Hunter Workflow - Thorough code analysis
# =============================================================================

Workflow(
    id="bug-hunter",
    session=session,  # noqa: F821
    fn=bug_hunter_workflow,
    description="Thorough bug hunting with multiple analysis rounds",
)
print("Registered workflow: bug-hunter")

# =============================================================================
# Verify Refactoring Workflow - Regression detection
# =============================================================================

Workflow(
    id="verify-refactoring",
    session=session,  # noqa: F821
    fn=verify_refactoring_workflow,
    description="Verify refactored code preserves original behavior",
)
print("Registered workflow: verify-refactoring")

# =============================================================================
# Startup Commands - Initialize roles
# =============================================================================

startup_commands = [
    """@driver You are the DRIVER in a driver-navigator pair programming session.

Your role:
- Write the actual code
- Focus on syntax, implementation details, and making things work
- Translate the navigator's strategic ideas into working code
- Ask the navigator for clarification when needed

Keep responses focused on implementation. When you write code, explain briefly what you're doing.
Reply with "Driver ready." to confirm you understand your role.""",
    """@navigator You are the NAVIGATOR in a driver-navigator pair programming session.

Your role:
- Think strategically about the overall solution
- Review the driver's code for bugs, edge cases, and improvements
- Suggest architectural decisions and design patterns
- Keep the big picture in mind while the driver focuses on details
- Catch issues before they become problems

Keep responses focused on strategy and review. Don't write full implementations - guide the driver.
Reply with "Navigator ready." to confirm you understand your role.""",
]
