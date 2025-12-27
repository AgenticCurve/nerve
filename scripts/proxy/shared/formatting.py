"""Text formatting utilities."""

from .colors import C


def truncate(text: str, max_len: int, indicator: str = "...") -> str:
    """Truncate text to max_len with indicator.

    Args:
        text: Text to truncate.
        max_len: Maximum length including indicator.
        indicator: String to append when truncated (default "...").

    Returns:
        Truncated text with indicator, or original if under max_len.
    """
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= len(indicator):
        return indicator[:max_len]
    return text[: max_len - len(indicator)] + indicator


def truncate_oneline(text: str, max_len: int, indicator: str = "...") -> str:
    """Truncate text, collapsing newlines to spaces first.

    Args:
        text: Text to truncate.
        max_len: Maximum length including indicator.
        indicator: String to append when truncated.

    Returns:
        Single-line truncated text.
    """
    text = text.replace("\n", " ").strip()
    return truncate(text, max_len, indicator)


def truncate_with_count(
    text: str,
    max_len: int,
    show_hint: bool = True,
) -> str:
    """Truncate text and show remaining character count.

    Args:
        text: Text to truncate.
        max_len: Maximum length before truncation message.
        show_hint: Whether to show "use --full" hint.

    Returns:
        Truncated text with count of remaining chars.
    """
    if len(text) <= max_len:
        return text
    remaining = len(text) - max_len
    hint = ", use --full to see all" if show_hint else ""
    return f"{text[:max_len]}\n{C.RED}[TRUNCATED: {remaining} more chars{hint}]{C.RESET}"


def print_indented(text: str, indent: int = 2, style: str = "") -> None:
    """Print text with indentation, handling multiline.

    Args:
        text: Text to print.
        indent: Number of spaces to indent.
        style: Optional ANSI style code to apply.
    """
    pad = " " * indent
    reset = C.RESET if style else ""
    for line in text.split("\n"):
        print(f"{pad}{style}{line}{reset}")
