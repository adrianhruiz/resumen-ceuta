"""Turning a validated summary into the text that reaches the terminal.

The model returns facts; the shape they are printed in is decided here. That
split is what lets the presentation change without spending an API call, and
what makes the order of the topics a property of this code rather than of
whatever the model felt like returning.
"""

import re
import shutil
import textwrap
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from .feeds import SOURCES
from .gemini import TOPICS
from .payload import Summary
from .store import Fetch

# C0 and C1 control characters, minus the tab. A headline arrives from an
# untrusted feed, and a stray escape sequence would let it clear the screen or
# move the cursor of whoever is reading.
MADRID = ZoneInfo("Europe/Madrid")

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

MIN_WIDTH = 40
MAX_WIDTH = 100
INDENT = "  "


def local_time(instant_utc: str) -> str:
    """An ISO instant as the wall clock of whoever is reading."""
    return datetime.fromisoformat(instant_utc).astimezone(MADRID).strftime("%H:%M")


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


def coverage(fetches: Sequence[Fetch]) -> str:
    """What was actually read today, per source.

    This is rendered outside the cache, from the `fetches` table, because it
    describes the run and not the summary. A cached summary shown at 21:00
    still has to admit that Faro was last read at 09:00.
    """
    by_source = {source.name: [] for source in SOURCES}
    for fetch in fetches:
        by_source.setdefault(fetch.source, []).append(fetch)

    parts = []
    # Archives first, then sliding windows: the reader gets the trustworthy
    # half of the coverage before the caveat.
    for source in sorted(SOURCES, key=lambda s: not s.archive):
        reads = [fetch for fetch in by_source.get(source.name, []) if fetch.ok]
        if not reads:
            attempted = by_source.get(source.name)
            parts.append(
                f"{source.display}: {'no se pudo leer' if attempted else 'sin leer'}"
            )
        elif source.archive:
            parts.append(
                f"{source.display}: completo hasta {local_time(reads[-1].fetched_at)}"
            )
        else:
            plural = "lectura" if len(reads) == 1 else "lecturas"
            parts.append(f"{source.display}: {len(reads)} {plural} (parcial)")
    return " · ".join(parts)


def header(day_in_spanish: str, article_count: int, fetches: Sequence[Fetch]) -> str:
    """The two lines above the summary: what day it is, and what was read."""
    noun = "noticia" if article_count == 1 else "noticias"
    count = f"{article_count} {noun}" if article_count else "sin noticias"
    return f"Día {day_in_spanish} · {count}\n{coverage(fetches)}"
