"""Multi-step workflow demo with node execution.

This workflow demonstrates step tracking in the TUI by executing
multiple nodes via ctx.run(). Each node execution creates a step
that shows up in the workflow TUI's steps list.

Prerequisites:
    You need at least one LLM node in your session. Create one with:
        nerve server node create claude --backend anthropic

Usage:
    In Commander:
        :load examples/workflows/multi_step_demo.py
        %number-game

    The workflow will:
        1. Ask the LLM to pick a number (Step 1)
        2. Ask the LLM to double it (Step 2)
        3. Ask the LLM to describe the result (Step 3)
"""

from nerve.core.workflow import Workflow, WorkflowContext


async def number_game(ctx: WorkflowContext) -> str:
    """A multi-step workflow that runs LLM nodes.

    Each ctx.run() call creates a visible step in the TUI.
    """
    # Get the node ID from input, default to "claude"
    node_id = ctx.input or "claude"

    # Step 1: Pick a number
    result1 = await ctx.run(
        node_id,
        "Pick a random number between 1 and 100. Reply with ONLY the number, nothing else.",
    )
    number = result1.get("output", "42").strip()

    # Step 2: Double it
    result2 = await ctx.run(
        node_id,
        f"Double this number: {number}. Reply with ONLY the result, nothing else.",
    )
    doubled = result2.get("output", "84").strip()

    # Step 3: Describe the result
    result3 = await ctx.run(
        node_id,
        f"Write a one-sentence fun fact about the number {doubled}.",
    )
    fun_fact = result3.get("output", "")

    return f"Started with {number}, doubled to {doubled}. Fun fact: {fun_fact}"


async def storyteller(ctx: WorkflowContext) -> str:
    """A creative workflow that builds a story step by step.

    Each step adds to the story, showing how workflows can
    chain node outputs together.
    """
    node_id = ctx.input or "claude"

    # Step 1: Create a character
    result1 = await ctx.run(
        node_id,
        "Create a fictional character in one sentence. Include their name and one quirky trait.",
    )
    character = result1.get("output", "").strip()

    # Step 2: Create a setting
    result2 = await ctx.run(
        node_id,
        f"Given this character: '{character}' - describe an unusual place they might visit in one sentence.",
    )
    setting = result2.get("output", "").strip()

    # Step 3: Create a twist
    result3 = await ctx.run(
        node_id,
        f"Character: '{character}'. Setting: '{setting}'. Write a surprising one-sentence plot twist.",
    )
    twist = result3.get("output", "").strip()

    return f"CHARACTER: {character}\n\nSETTING: {setting}\n\nTWIST: {twist}"


async def with_gate(ctx: WorkflowContext) -> str:
    """Workflow combining node execution with a human gate.

    Shows how to mix automated steps with human decision points.
    """
    node_id = ctx.input or "claude"

    # Step 1: Generate options
    result1 = await ctx.run(
        node_id,
        "Suggest 3 fun weekend activities. Number them 1, 2, 3. Keep each to one line.",
    )
    options = result1.get("output", "").strip()

    # Gate: Let human choose
    choice = await ctx.gate(
        f"Which activity?\n\n{options}",
        choices=["1", "2", "3"],
    )

    # Step 2: Elaborate on the choice
    result2 = await ctx.run(
        node_id,
        f"The user chose option {choice} from: {options}\n\nWrite a short enthusiastic response about why that's a great choice!",
    )

    return result2.get("output", "")


async def multi_gate_test(ctx: WorkflowContext) -> str:
    """Workflow with multiple gates for testing pane switching.

    This workflow has 4 gates interspersed with node executions
    to test the TUI's focus handling.
    """
    node_id = ctx.input or "claude"
    responses: list[str] = []

    # Gate 1: Get user's name
    name = await ctx.gate(
        "What's your name?",
    )
    responses.append(f"Name: {name}")

    # Step 1: Generate a greeting
    result1 = await ctx.run(
        node_id,
        f"Write a short, friendly greeting for someone named {name}. One sentence only.",
    )
    greeting = result1.get("output", "").strip()
    responses.append(f"Greeting: {greeting}")

    # Gate 2: Pick a topic
    topic = await ctx.gate(
        "What topic would you like to discuss?",
        choices=["Technology", "Nature", "Food", "Travel"],
    )
    responses.append(f"Topic: {topic}")

    # Step 2: Generate a fact about the topic
    result2 = await ctx.run(
        node_id,
        f"Tell me one interesting fact about {topic}. Keep it to 2 sentences max.",
    )
    fact = result2.get("output", "").strip()
    responses.append(f"Fact: {fact}")

    # Gate 3: Rate the fact
    rating = await ctx.gate(
        f'How interesting was that fact?\n\n"{fact}"',
        choices=["1 - Boring", "2 - Okay", "3 - Interesting", "4 - Amazing"],
    )
    responses.append(f"Rating: {rating}")

    # Step 3: React to rating
    result3 = await ctx.run(
        node_id,
        f"The user rated your fact about {topic} as '{rating}'. Write a brief, playful reaction (1 sentence).",
    )
    reaction = result3.get("output", "").strip()
    responses.append(f"Reaction: {reaction}")

    # Gate 4: Continue or end
    choice = await ctx.gate(
        "Would you like a bonus fact or end here?",
        choices=["Bonus fact please!", "I'm good, thanks"],
    )

    if "Bonus" in choice:
        result4 = await ctx.run(
            node_id,
            f"Give {name} one more surprising fact about {topic}. Make it fun!",
        )
        bonus = result4.get("output", "").strip()
        responses.append(f"Bonus: {bonus}")
    else:
        responses.append("User chose to end.")

    return "\n".join(responses)


# Register workflows
# Note: 'session' is injected by the Python executor
Workflow(id="number-game", session=session, fn=number_game)  # noqa: F821
Workflow(id="storyteller", session=session, fn=storyteller)  # noqa: F821
Workflow(id="with-gate", session=session, fn=with_gate)  # noqa: F821
Workflow(id="multi-gate", session=session, fn=multi_gate_test)  # noqa: F821

print("Registered 4 multi-step workflows: number-game, storyteller, with-gate, multi-gate")
print("Usage: %number-game claude  (or your LLM node ID)")
print("       %multi-gate claude   (4 gates for testing pane switching)")
