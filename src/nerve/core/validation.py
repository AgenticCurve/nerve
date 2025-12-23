"""Name validation for servers and nodes.

Provides consistent validation rules for naming entities in nerve.
"""

from __future__ import annotations

import re

# Pattern: lowercase alphanumeric, can contain dashes but not start/end with them
# Single char names allowed (just alphanumeric)
NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

MAX_NAME_LENGTH = 32


def validate_name(name: str, entity: str = "name") -> None:
    """Validate a name (server/node).

    Rules:
    - 1-32 characters
    - Lowercase alphanumeric and dashes only
    - Cannot start or end with dash

    Args:
        name: The name to validate.
        entity: What the name is for (used in error messages).

    Raises:
        ValueError: If the name is invalid.

    Example:
        >>> validate_name("my-project", "server")  # OK
        >>> validate_name("claude-1", "node")      # OK
        >>> validate_name("My Project", "server")  # ValueError
        >>> validate_name("-bad", "node")          # ValueError
    """
    entity_cap = entity.capitalize()

    if not name:
        raise ValueError(f"{entity_cap} name is required")

    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"{entity_cap} name must be {MAX_NAME_LENGTH} characters or less")

    if not NAME_PATTERN.match(name):
        raise ValueError(
            f"{entity_cap} name must be lowercase alphanumeric with dashes, "
            f"cannot start or end with dash"
        )


def is_valid_name(name: str) -> bool:
    """Check if a name is valid without raising.

    Args:
        name: The name to check.

    Returns:
        True if valid, False otherwise.
    """
    if not name or len(name) > MAX_NAME_LENGTH:
        return False
    return bool(NAME_PATTERN.match(name))
