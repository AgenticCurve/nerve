"""Cross-platform clipboard utilities for Commander TUI.

Provides clipboard copy functionality with platform-specific tool detection.
Supports macOS (pbcopy), Linux (xclip, xsel), and WSL.
"""

from __future__ import annotations

import os
import subprocess

# Clipboard commands to try in order of preference
_CLIPBOARD_COMMANDS: list[tuple[list[str], dict[str, str]]] = [
    # macOS
    (["pbcopy"], {"LANG": "en_US.UTF-8"}),
    # Linux (X11)
    (["xclip", "-selection", "clipboard"], {}),
    # Linux (alternative)
    (["xsel", "--clipboard", "--input"], {}),
]

TIMEOUT_SECONDS = 5


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    """Copy text to system clipboard.

    Tries multiple clipboard tools in order until one succeeds.
    Supports macOS (pbcopy), Linux (xclip, xsel).

    Args:
        text: Text to copy to clipboard.

    Returns:
        Tuple of (success, message) where message is user-facing feedback.
    """
    encoded = text.encode("utf-8")

    for cmd, env in _CLIPBOARD_COMMANDS:
        try:
            # Merge provided env with current environment (don't replace it)
            process_env = {**os.environ, **env} if env else None
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                env=process_env,
            )
            process.communicate(encoded, timeout=TIMEOUT_SECONDS)

            if process.returncode == 0:
                return True, "Copied to clipboard!"
            # Non-zero return code, try next command
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            # Timeout is unusual - report it rather than silently trying next
            return False, "Copy timed out"
        except FileNotFoundError:
            # Command not found, try next
            continue
        except Exception:
            # Other error, try next
            continue

    return False, "Copy failed (no clipboard tool available)"
