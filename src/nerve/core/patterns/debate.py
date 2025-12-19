"""Debate pattern - two agents arguing opposing positions.

Ported from wezterm's dag_debate.py.

A structured debate where:
- Two agents take opposing positions on a topic
- They alternate presenting arguments
- Continues for a set number of rounds

This pattern is useful for:
- Exploring different perspectives
- Testing argument robustness
- Generating diverse viewpoints
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nerve.core.session import Session
from nerve.core.types import ParsedResponse

DEFAULT_DEBATE_PROMPT = """You are arguing {position} in a debate.

Topic: {topic}

Your opponent said: {opponent_message}

Rules:
- Keep your response under {max_words} words
- Be persuasive and logical
- Address your opponent's points
- Stay on topic

Present your argument:"""


@dataclass
class DebateConfig:
    """Configuration for Debate loop.

    Attributes:
        topic: The debate topic.
        position_a: Position for agent A (e.g., "FOR Python").
        position_b: Position for agent B (e.g., "FOR JavaScript").
        rounds: Number of debate rounds.
        max_words: Word limit per response.
        prompt_template: Prompt template for debaters.
        on_turn: Callback after each turn.
        on_complete: Callback when debate ends.
    """

    topic: str
    position_a: str = "FOR the proposition"
    position_b: str = "AGAINST the proposition"
    rounds: int = 5
    max_words: int = 100
    prompt_template: str = DEFAULT_DEBATE_PROMPT
    on_turn: Callable[[int, str, str], None] | None = None
    on_complete: Callable[[list], None] | None = None


@dataclass
class DebateTurn:
    """A single turn in the debate."""

    round: int
    position: str
    agent: str
    message: str


@dataclass
class DebateResult:
    """Result of a debate session.

    Attributes:
        topic: The debate topic.
        rounds: Number of rounds completed.
        turns: All debate turns.
        final_a: Agent A's final argument.
        final_b: Agent B's final argument.
    """

    topic: str
    rounds: int
    turns: list[DebateTurn]
    final_a: str
    final_b: str


class DebateLoop:
    """Two-agent debate loop.

    Orchestrates a debate between two agents taking opposing positions.

    Example:
        >>> config = DebateConfig(
        ...     topic="Is Python better than JavaScript?",
        ...     position_a="FOR Python",
        ...     position_b="FOR JavaScript",
        ...     rounds=3,
        ... )
        >>>
        >>> loop = DebateLoop(
        ...     agent_a=claude1,
        ...     agent_b=claude2,
        ...     config=config,
        ... )
        >>>
        >>> result = await loop.run()
        >>> for turn in result.turns:
        ...     print(f"[{turn.position}]: {turn.message[:100]}...")
    """

    def __init__(
        self,
        agent_a: Session,
        agent_b: Session,
        config: DebateConfig,
    ):
        """Initialize the debate.

        Args:
            agent_a: Session for agent A.
            agent_b: Session for agent B.
            config: Debate configuration.
        """
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.config = config
        self._turns: list[DebateTurn] = []

    def _extract_response_text(self, response: ParsedResponse) -> str:
        """Extract text content from response."""
        for section in reversed(response.sections):
            if section.type == "text":
                return section.content
        return response.raw

    async def run(self) -> DebateResult:
        """Run the debate.

        Returns:
            DebateResult with all turns and final arguments.
        """
        message_a = ""
        message_b = f"Let's debate: {self.config.topic}"

        for round_num in range(1, self.config.rounds + 1):
            # === AGENT A's TURN ===
            prompt_a = self.config.prompt_template.format(
                position=self.config.position_a,
                topic=self.config.topic,
                opponent_message=message_b,
                max_words=self.config.max_words,
            )

            response_a = await self.agent_a.send(prompt_a)
            message_a = self._extract_response_text(response_a)

            turn_a = DebateTurn(
                round=round_num,
                position=self.config.position_a,
                agent="A",
                message=message_a,
            )
            self._turns.append(turn_a)

            if self.config.on_turn:
                self.config.on_turn(round_num, self.config.position_a, message_a)

            # === AGENT B's TURN ===
            prompt_b = self.config.prompt_template.format(
                position=self.config.position_b,
                topic=self.config.topic,
                opponent_message=message_a,
                max_words=self.config.max_words,
            )

            response_b = await self.agent_b.send(prompt_b)
            message_b = self._extract_response_text(response_b)

            turn_b = DebateTurn(
                round=round_num,
                position=self.config.position_b,
                agent="B",
                message=message_b,
            )
            self._turns.append(turn_b)

            if self.config.on_turn:
                self.config.on_turn(round_num, self.config.position_b, message_b)

        if self.config.on_complete:
            self.config.on_complete(self._turns)

        return DebateResult(
            topic=self.config.topic,
            rounds=self.config.rounds,
            turns=self._turns,
            final_a=message_a,
            final_b=message_b,
        )
