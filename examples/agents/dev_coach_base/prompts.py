"""Prompts for the dev_coach_base agent.

Edit these prompts to customize agent behavior.
Two Claude agents collaborate on a task:
- Developer: Does the technical work, explores code, proposes solutions
- Coach: Reviews, critiques, guides, and accepts when satisfied
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

# Termination
ACCEPTANCE_PHRASE = "I ACCEPT AND I HAVE NO MORE CHANGES TO SUGGEST."
MAX_ROUNDS = 50

# Paths
DEV_CWD = "/Users/pb/agentic-curve/projects/nerve"  # Developer's working directory
COACH_CWD = "/Users/pb/agentic-curve/projects/nerve"  # Coach's working directory
OUTPUT_FILE = "/tmp/dev-coach-output.md"
LOG_FILE = "/tmp/dev-coach-conversation.log"

# =============================================================================
# WARMUP - Optional system-like instructions sent once before task begins
# =============================================================================

DEV_WARMUP = ""  # Leave empty to skip warmup
# Example:
# DEV_WARMUP = """You are an expert Python developer. You write clean, tested code.
# Always run tests before claiming something works."""

COACH_WARMUP = ""  # Leave empty to skip warmup
# Example:
# COACH_WARMUP = """You are a strict but fair technical coach. You don't accept
# work without tests. You make decisions quickly when the developer is stuck."""

# =============================================================================
# TASK - Define what the agents are working on
# =============================================================================

INITIAL_TASK = """
We will soon be developing a new feature. But before that we need to setup our
existing project for success. Please find the tests/ we will need in place before
starting the new feature.

Ensure the tests/ we write ONLY cover existing functionality and do NOT cover the new feature.

We want to ensure that we DONT break any of the existing functionality while adding these new tests.

You can find the specs for the new feature in:
CHANNEL_HISTORY_PRD.md
"""

TASK_REFRESHER = """
We will soon be developing a new feature. But before that we need to setup our
existing project for success. Please find the tests/ we will need in place before
starting the new feature.

Ensure the tests/ we write ONLY cover existing functionality and do NOT cover the new feature.

We want to ensure that we DONT break any of the existing functionality while adding these new tests.

You can find the specs for the new feature in:
CHANNEL_HISTORY_PRD.md
"""

# =============================================================================
# PROMPTS - Edit these to customize agent behavior
# =============================================================================

# --- Initial prompts (priming) ---

DEV_INITIAL_PROMPT = """You are a Senior Software Developer.

{initial_task}

You are working with a Coach who will review your work and guide you toward a complete solution.

You need to make sure our codebase is ready for the new feature.
You are the ONLY one who can make changes to the codebase and write tests.
You can ask coach for decisions if you're stuck.

"""

COACH_INITIAL_PROMPT_TEMPLATE = """You are a Technical Coach. A Developer is working on a task:

{initial_task}

The Developer just provided their initial analysis:

\"\"\"
{dev_response}
\"\"\"

Your role:
1. Critically evaluate the work
2. Identify gaps, risks, or issues
3. Ask probing questions or suggest improvements
4. Guide toward a complete, high-quality solution
5. You cannot make any changes.
6. You need to make design decisions that developer is stuck with.
7. You are the final authority.
8. You can read and review any file but you cannot make changes to any file.
9. ENSURE THE DEVELOPER ADDS TESTS FOR EXISTING FUNCTIONALITY AND NOT FOR THE NEW FEATURE.
10. ENSURE THE DEVELOPER DOES NOT BREAK ANY EXISTING FUNCTIONALITY WHILE ADDING THESE NEW TESTS.

Original thoughts regarding the feature are in: CHANNEL_HISTORY_PRD.md

If you are FULLY SATISFIED and the work is complete, respond with EXACTLY:
"{acceptance_phrase}".

Note, use that phrase ONLY when you've NO MORE FEEDBACK at all.

Otherwise, provide your feedback for the next iteration. Catch bugs and feature regressions."""

# --- Loop prompts (iterations) ---

DEV_LOOP_PROMPT_TEMPLATE = """The Coach reviewed your work and provided feedback:

\"\"\"
{coach_response}
\"\"\"

{task_refresher}

Please:
1. Address each point the coach raised
2. Explore further if needed
3. Provide an updated, complete response
4. Update the document (if needed) REFACTORED_DIR_ARCHITECTURE.md

The coach will accept when satisfied."""

COACH_LOOP_PROMPT_TEMPLATE = """The Developer addressed your feedback:

\"\"\"
{dev_response}
\"\"\"

{task_refresher}

Dev has this bad habit of jumping ahead and writing unwanted code.

Ensure they add the wanted tests, refactor existing code for the new feature and no feature regression.
Give grades to dev on their work and clearly tell them what's missing. Run tests as well.

Review their updated work. If you are FULLY SATISFIED, respond with EXACTLY:
"{acceptance_phrase}"

Otherwise, provide your next round of feedback."""
