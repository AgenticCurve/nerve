"""Prompts for the dev_coach_consultants agent.

Edit these prompts to customize agent behavior.
Five Claude agents collaborate:
- Developer: Does the work, talks only to Coach
- Coach: Reviews, consults experts, synthesizes feedback
- Consultant 1/2/3: Provide independent advice to Coach
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

ACCEPTANCE_PHRASE = "I ACCEPT AND WE ARE DONE."
MAX_ROUNDS = 50

# Paths
DEV_CWD = "/Users/pb/agentic-curve/projects/nerve"
COACH_CWD = "/Users/pb/agentic-curve/projects/nerve"
CONSULTANT_CWD = "/Users/pb/agentic-curve/projects/nerve"
OUTPUT_FILE = "/tmp/dev-coach-consultants-output.md"
LOG_FILE = "/tmp/dev-coach-consultants-conversation.log"

# =============================================================================
# WARMUP - Optional system-like instructions sent once before task begins
# =============================================================================

DEV_WARMUP = ""
COACH_WARMUP = ""
CONSULTANT_1_WARMUP = ""
CONSULTANT_2_WARMUP = ""
CONSULTANT_3_WARMUP = ""

# =============================================================================
# TASK
# =============================================================================

INITIAL_TASK = """Explore this codebase and understand its architecture.

Please:
1. Read the README and key source files
2. Understand the project structure
3. Identify the main components and how they interact

Provide a summary of your findings."""

TASK_REFRESHER = """Remember: We are exploring the codebase architecture."""

# =============================================================================
# PROMPTS - Developer (Dev only talks to Coach)
# =============================================================================

DEV_INITIAL_PROMPT = """You are a Senior Software Developer.

{initial_task}

{additional_context}

You are working with a Coach who will review your work and guide you.
Start by understanding the task and providing your initial work."""

DEV_LOOP_PROMPT_TEMPLATE = """The Coach reviewed your work and provided feedback:

\"\"\"
{coach_response}
\"\"\"

{task_refresher}

Please:
1. Address each point raised
2. Explore further if needed
3. Provide an updated, complete response

The coach will accept when satisfied."""

# =============================================================================
# PROMPTS - Coach (coordinates everything, Dev doesn't know about consultants)
# =============================================================================

# --- Coach initial thoughts (first round) ---

COACH_INITIAL_THOUGHTS_TEMPLATE = """You are a Technical Coach reviewing a developer's work.

{initial_task}

{additional_context}

The Developer just provided their initial work:

\"\"\"
{dev_response}
\"\"\"

Please review this work and share your initial thoughts:
1. What's good about this work?
2. What concerns or gaps do you see?
3. What questions do you have?

Be thorough - your thoughts will inform further review."""

# --- Coach loop thoughts (subsequent rounds) ---

COACH_LOOP_THOUGHTS_TEMPLATE = """You are a Technical Coach reviewing updated work from the developer.

The Developer addressed your previous feedback:

\"\"\"
{dev_response}
\"\"\"

{task_refresher}

Please review this updated work and share your thoughts:
1. Did they address your previous concerns?
2. What's improved?
3. What still needs work?

Be thorough - your thoughts will inform further review."""

# --- Coach synthesize (combines own thoughts + consultant advice) ---

COACH_SYNTHESIZE_TEMPLATE = """You are a Technical Coach. You've reviewed the developer's work and consulted with experts.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

YOUR INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

CONSULTANT 1's ADVICE:
\"\"\"
{consultant_1_advice}
\"\"\"

CONSULTANT 2's ADVICE:
\"\"\"
{consultant_2_advice}
\"\"\"

CONSULTANT 3's ADVICE:
\"\"\"
{consultant_3_advice}
\"\"\"

{task_refresher}

Now synthesize all of this into clear, actionable feedback for the developer.
Do NOT mention the consultants - the developer doesn't know about them.
Present the feedback as your own coaching guidance.

If the work is FULLY SATISFACTORY and ready, respond with EXACTLY:
"{acceptance_phrase}"

Otherwise, provide your synthesized feedback."""

# =============================================================================
# PROMPTS - Consultants (provide independent advice to Coach)
# =============================================================================

CONSULTANT_1_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #1) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""

CONSULTANT_2_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #2) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""

CONSULTANT_3_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #3) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""
