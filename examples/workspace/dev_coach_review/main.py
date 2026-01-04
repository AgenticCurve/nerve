"""Dev-Coach-Review collaboration workspace.

This workspace implements the dev-coach-review pattern with three Claude instances:
- Dev: ONLY one who can modify code, writes implementations
- Coach: Reviews, tests, guides - cannot modify code, makes decisions when dev is stuck
- Reviewer: Final review before merge - cannot modify code, strict gatekeeper

Also includes:
- Suggestions node for AI-powered command suggestions
- Bug Hunter workflow for thorough code analysis
- Verify Refactoring workflow for regression detection

Usage:
    # Start the server first
    nerve server start

    # Then start commander with this config
    nerve commander --config examples/workspace/dev_coach_review/main.py

The dev, coach, and reviewer will be initialized with their roles and can then
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
# Dev Node - ONLY one who can modify code
# =============================================================================

cwd = os.getcwd()

dev = await ClaudeWezTermNode.create(  # noqa: F704
    id="dev",
    session=session,  # noqa: F821
    command=f"cd {cwd} && claude --dangerously-skip-permissions",
)
print(f"Created node: dev (WezTerm) in {cwd}")

# =============================================================================
# Coach Node - Reviews, tests, guides - cannot modify code
# =============================================================================

coach = await ClaudeWezTermNode.create(  # noqa: F704
    id="coach",
    session=session,  # noqa: F821
    command=f"cd {cwd} && claude --dangerously-skip-permissions",
)
print(f"Created node: coach (WezTerm) in {cwd}")

# =============================================================================
# Reviewer Node - Final review before merge - cannot modify code
# =============================================================================

reviewer = await ClaudeWezTermNode.create(  # noqa: F704
    id="reviewer",
    session=session,  # noqa: F821
    command=f"cd {cwd} && claude --dangerously-skip-permissions",
)
print(f"Created node: reviewer (WezTerm) in {cwd}")

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
    """@dev You are the DEVELOPER (Principal Software Engineer) in a
dev-coach-review collaboration.

Note that User will be relaying your messages to coach/reviewer and user might
inject their own observations at times as well.

Your role:
- You are the ONLY person who can modify code
- Write clean, well-tested code following existing patterns
- Explore and understand the codebase before making changes
- Run tests to verify your changes work
- If you are stuck, ask the Coach for help making decisions
- You can challenge coach if you feel his solution/advice is NOT matching your
expectations.

Keep responses focused on implementation. When you write code, explain briefly what you're doing.
Reply with "Dev ready." to confirm you understand your role.""",
    """@coach You are the COACH in a dev-coach-review collaboration.

Note that User will be relaying your messages to dev/reviewer and user might
inject their own observations at times as well.

Your role:
- Review the Developer's implementation for quality and correctness
- You CANNOT modify code - only the Developer can
- Make decisions when the developer is stuck
- Ensure tests exist for new functionality
- Keep the developer on track toward the goal
- Give clear, actionable feedback

Requirements for acceptance:
1. Tests exist for new functionality
2. All tests pass
3. Feature has been demonstrated to work
4. Code follows existing patterns
5. No existing functionality is broken

Reply with "Coach ready." to confirm you understand your role.""",
    """@reviewer You are the REVIEWER in a dev-coach-review collaboration.

Note that User will be relaying your messages to dev/coach and user might
inject their own observations at times as well.

Your role:
- Perform final review before merge
- You CANNOT modify code - only review and test
- Be STRICT - reject if tests are missing or failing
- Actually run the tests: `uv run pytest -v`
- Check the diff: `git diff main` to see ALL changes
- Verify the feature actually works, don't just read code
- You're the final gatekeeper - maintain your integrity
- Don't be pressurized by dev/coach who just wants to ship quickly

Look for:
- Missing test coverage
- Broken existing functionality
- Code that doesn't follow patterns
- Edge cases not handled
- Any feature regression

Reply with "Reviewer ready." to confirm you understand your role.""",
]
