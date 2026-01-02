"""Driver-Navigator pair programming workspace.

This workspace implements the driver-navigator pair programming pattern with
two Claude instances:
- Driver: Writes the code, focuses on implementation details
- Navigator: Reviews code, thinks strategically, catches issues

Usage:
    # Start the server first
    nerve server start

    # Then start commander with this config
    nerve commander --config examples/workspace/driver_navigator.py

The driver and navigator will be initialized with their roles and can then
collaborate on coding tasks.
"""

from nerve.core.nodes.terminal import ClaudeWezTermNode

# =============================================================================
# Driver Node - Writes code, implements solutions
# =============================================================================

driver = await ClaudeWezTermNode.create(  # noqa: F704
    id="driver",
    session=session,  # noqa: F821
    command="claude --dangerously-skip-permissions",
)
print("Created node: driver (WezTerm)")

# =============================================================================
# Navigator Node - Reviews, strategizes, catches issues
# =============================================================================

navigator = await ClaudeWezTermNode.create(  # noqa: F704
    id="navigator",
    session=session,  # noqa: F821
    command="claude --dangerously-skip-permissions",
)
print("Created node: navigator (WezTerm)")

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
