"""Developer-Coach collaboration pattern.

Ported from wezterm's dag_dev_coach.py.

A structured loop where:
- A "Developer" agent works on a task
- A "Coach" agent reviews and provides feedback
- Loop continues until Coach accepts completion

This pattern is useful for:
- Code review workflows
- Iterative refinement tasks
- Quality-gated implementations
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from nerve.core.types import ParsedResponse


@runtime_checkable
class Agent(Protocol):
    """Protocol for agents that can send messages and receive responses."""

    async def send(self, text: str) -> ParsedResponse:
        """Send input and get response."""
        ...


# Default prompt templates
DEFAULT_DEV_PROMPT = """You are a SENIOR DEVELOPER working with a legendary coach who reviews your work.

## YOUR TASK:
{task}

## YOUR WORKFLOW:
1. PLAN first - explain your approach before coding
2. Make INCREMENTAL changes - small, focused commits
3. COMMIT regularly with clear, descriptive messages
4. RUN commands to verify your work compiles/runs/passes tests
5. RESPOND to coach feedback and fix any issues raised

## IMPORTANT RULES:
- You are NOT done until your coach explicitly says "APPROVED" or "LGTM"
- When coach approves, you can make final touches or ask follow-up questions
- When YOU are satisfied and have no more changes/questions, say EXACTLY:
  "TASK COMPLETED SUCCESSFULLY" or "FINISHED SUCCESSFULLY"
- ONLY use these exact phrases when you're truly done and don't need more review
- After you say this, coach will respond with "I ACCEPT TASK COMPLETION" to end the session
- Take coach feedback seriously - they have high standards
- If you're stuck, explain what you've tried
- Show your work - run commands, show output

## COLLABORATION:
- You CAN discuss ideas with your coach before implementing
- Ask questions if something is unclear
- Propose alternatives and discuss trade-offs
- Seek to reach mutual understanding - aim for "eureka moments"
- It's a dialogue, not just receiving orders

## COACH'S LAST MESSAGE:
{coach_message}

Now continue working. You can implement, ask questions, or discuss approaches."""


DEFAULT_COACH_PROMPT = """You are a LEGENDARY CODING COACH with extremely high standards. A senior developer is working on a task and you're reviewing their work.

## THE TASK BEING WORKED ON:
{task}

## YOUR ROLE:
1. REVIEW the developer's code changes critically
2. CHECK that code actually works - run commands to test/verify
3. VERIFY logic, edge cases, error handling, code style
4. POINT OUT bugs, issues, potential improvements
5. Be SPECIFIC in feedback - tell them exactly what needs fixing
6. Make design decisions based on the codebase when developer is stuck
7. Single source of truth is the codebase - verify claims against it

## CRITICAL RULES:
- NEVER make code changes yourself - always ask the developer to fix issues
- You REVIEW and GUIDE, the developer IMPLEMENTS
- You CAN run commands to test/verify the code, but don't write/edit code
- Be STRICT - don't let sloppy code pass
- Only say "APPROVED" when work TRULY meets high standards

## TASK COMPLETION PROTOCOL:
- After you approve, developer may still ask questions or make final touches
- When developer says "TASK COMPLETED SUCCESSFULLY" or "FINISHED SUCCESSFULLY":
  - If you have ANY remaining feedback, give it (don't accept yet)
  - If you truly have NOTHING more to add, respond with ONLY:
    "I ACCEPT TASK COMPLETION"
  - This MUST be a one-liner. No additional feedback allowed when accepting.

## COLLABORATION:
- Engage in dialogue - answer the developer's questions thoughtfully
- Explain the WHY behind your feedback, not just the WHAT
- Help them reach understanding - guide them to "eureka moments"
- If they propose alternatives, discuss trade-offs honestly
- Be a mentor, not a dictator - but maintain high standards

## DEVELOPER'S LAST MESSAGE:
{dev_message}

Review, guide, and respond. Remember: guide them to the solution, don't implement it yourself."""


@dataclass
class DevCoachConfig:
    """Configuration for Developer-Coach loop.

    Attributes:
        task: The task description for both agents.
        max_rounds: Maximum number of rounds (safety limit).
        dev_prompt_template: Prompt template for developer.
        coach_prompt_template: Prompt template for coach.
        acceptance_phrases: Phrases that indicate coach acceptance.
        completion_phrases: Phrases that indicate developer completion.
        on_dev_turn: Callback after developer's turn.
        on_coach_turn: Callback after coach's turn.
        on_complete: Callback when loop completes.
    """

    task: str
    max_rounds: int = 50
    dev_prompt_template: str = DEFAULT_DEV_PROMPT
    coach_prompt_template: str = DEFAULT_COACH_PROMPT
    acceptance_phrases: list[str] = field(
        default_factory=lambda: [
            "I ACCEPT TASK COMPLETION",
        ]
    )
    completion_phrases: list[str] = field(
        default_factory=lambda: [
            "TASK COMPLETED SUCCESSFULLY",
            "FINISHED SUCCESSFULLY",
        ]
    )
    on_dev_turn: Callable[[int, str], None] | None = None
    on_coach_turn: Callable[[int, str], None] | None = None
    on_complete: Callable[[int, str], None] | None = None


@dataclass
class DevCoachResult:
    """Result of a Developer-Coach session.

    Attributes:
        completed: Whether the task was accepted.
        rounds: Number of rounds executed.
        final_dev_message: Developer's last message.
        final_coach_message: Coach's last message.
        history: Full conversation history.
    """

    completed: bool
    rounds: int
    final_dev_message: str
    final_coach_message: str
    history: list[dict[str, str]] = field(default_factory=list)


class DevCoachLoop:
    """Developer-Coach collaboration loop.

    Orchestrates a back-and-forth between a developer agent and a
    coach agent until the coach accepts task completion.

    Example:
        >>> config = DevCoachConfig(
        ...     task="Implement a binary search function",
        ...     max_rounds=10,
        ... )
        >>>
        >>> loop = DevCoachLoop(
        ...     developer=dev_session,
        ...     coach=coach_session,
        ...     config=config,
        ... )
        >>>
        >>> result = await loop.run()
        >>> print(f"Completed in {result.rounds} rounds")
    """

    def __init__(
        self,
        developer: Agent,
        coach: Agent,
        config: DevCoachConfig,
    ):
        """Initialize the loop.

        Args:
            developer: Agent for the developer (e.g., PTYNode, WezTermNode).
            coach: Agent for the coach (e.g., PTYNode, WezTermNode).
            config: Loop configuration.
        """
        self.developer = developer
        self.coach = coach
        self.config = config
        self._history: list[dict[str, str]] = []

    def _extract_response_text(self, response: ParsedResponse) -> str:
        """Extract text content from response."""
        # Get the last text section, or raw if no sections
        for section in reversed(response.sections):
            if section.type == "text":
                return section.content
        return response.raw

    def _is_accepted(self, message: str) -> bool:
        """Check if coach has accepted task completion."""
        msg_upper = message.upper()
        return any(phrase.upper() in msg_upper for phrase in self.config.acceptance_phrases)

    def _is_completion_claimed(self, message: str) -> bool:
        """Check if developer claims completion."""
        msg_upper = message.upper()
        return any(phrase.upper() in msg_upper for phrase in self.config.completion_phrases)

    async def run(self) -> DevCoachResult:
        """Run the Developer-Coach loop.

        Returns:
            DevCoachResult with completion status and history.
        """
        coach_message = "This is the start. Begin by planning your approach to the task."
        dev_message = ""

        for round_num in range(1, self.config.max_rounds + 1):
            # === DEVELOPER'S TURN ===
            dev_prompt = self.config.dev_prompt_template.format(
                task=self.config.task,
                coach_message=coach_message,
            )

            dev_response = await self.developer.send(dev_prompt)
            dev_message = self._extract_response_text(dev_response)

            self._history.append(
                {
                    "round": round_num,
                    "role": "developer",
                    "message": dev_message,
                }
            )

            if self.config.on_dev_turn:
                self.config.on_dev_turn(round_num, dev_message)

            # === COACH'S TURN ===
            coach_prompt = self.config.coach_prompt_template.format(
                task=self.config.task,
                dev_message=dev_message,
            )

            coach_response = await self.coach.send(coach_prompt)
            coach_message = self._extract_response_text(coach_response)

            self._history.append(
                {
                    "round": round_num,
                    "role": "coach",
                    "message": coach_message,
                }
            )

            if self.config.on_coach_turn:
                self.config.on_coach_turn(round_num, coach_message)

            # === CHECK FOR ACCEPTANCE ===
            if self._is_accepted(coach_message):
                if self.config.on_complete:
                    self.config.on_complete(round_num, "accepted")

                return DevCoachResult(
                    completed=True,
                    rounds=round_num,
                    final_dev_message=dev_message,
                    final_coach_message=coach_message,
                    history=self._history,
                )

        # Max rounds reached
        if self.config.on_complete:
            self.config.on_complete(self.config.max_rounds, "max_rounds")

        return DevCoachResult(
            completed=False,
            rounds=self.config.max_rounds,
            final_dev_message=dev_message,
            final_coach_message=coach_message,
            history=self._history,
        )
