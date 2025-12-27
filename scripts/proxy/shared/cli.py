"""Shared CLI configuration for rich-click."""

import rich_click as click


def configure_rich_click(option_groups: dict | None = None) -> None:
    """Apply standard rich-click configuration.

    Args:
        option_groups: Optional dict mapping command names to option group definitions.
                      Example: {"main": [{"name": "Display", "options": ["--verbose"]}]}
    """
    click.rich_click.USE_RICH_MARKUP = True
    click.rich_click.USE_MARKDOWN = True
    click.rich_click.SHOW_ARGUMENTS = True
    click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
    click.rich_click.STYLE_OPTION = "bold cyan"
    click.rich_click.STYLE_ARGUMENT = "bold green"
    click.rich_click.STYLE_COMMAND = "bold yellow"
    click.rich_click.MAX_WIDTH = 100

    if option_groups:
        click.rich_click.OPTION_GROUPS = option_groups
