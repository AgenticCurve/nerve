"""Prompts for the debate agent.

Edit these prompts to customize agent behavior.
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

ROUNDS = 3

# =============================================================================
# PROMPTS
# =============================================================================

# Initial topic for the debate
DEBATE_TOPIC = "Is Python better than JavaScript?"

# Prompt template for Python advocate
PYTHON_ADVOCATE_PROMPT = "[Round {round_num}] You're arguing FOR Python. Opponent said: {message}. Keep it under 100 words."

# Prompt template for JavaScript advocate
JS_ADVOCATE_PROMPT = "[Round {round_num}] You're arguing FOR JavaScript. Opponent said: {message}. Keep it under 100 words."
