"""Turning a validated summary into the text that reaches the terminal.

The model returns facts; the shape they are printed in is decided here. That
split is what lets the presentation change without spending an API call, and
what makes the order of the topics a property of this code rather than of
whatever the model felt like returning.
"""

import re
import shutil
import textwrap

from .gemini import TOPICS
from .payload import Summary

# C0 and C1 control characters, minus the tab. A headline arrives from an
# untrusted feed, and a stray escape sequence would let it clear the screen or
# move the cursor of whoever is reading.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

MIN_WIDTH = 40
MAX_WIDTH = 100
INDENT = "  "


def sanitize(text: str) -> str:
    """Printable text, with control sequences and stray whitespace removed."""
    return " ".join(CONTROL.sub("", text).split())


def terminal_width() -> int:
    """How wide to wrap. COLUMNS wins, which is what makes this testable."""
    return max(
        MIN_WIDTH, min(MAX_WIDTH, shutil.get_terminal_size(fallback=(80, 24)).columns)
    )


def render(summary: Summary, width: int | None = None) -> str:
    """The body of the summary: one paragraph per topic, in a fixed order."""
    wrap_at = width if width is not None else terminal_width()
    by_name = {topic.name: topic for topic in summary.topics}

    paragraphs = []
    # TOPICS order, not the model's: the reader gets the same shape every day.
    for name in TOPICS:
        topic = by_name.get(name)
        if topic is None or not topic.entries:
            continue
        facts = "; ".join(sanitize(entry.text) for entry in topic.entries)
        paragraphs.append(
            textwrap.fill(
                f"{name}: {facts}",
                width=wrap_at,
                subsequent_indent=INDENT,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(paragraphs)
