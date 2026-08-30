"""The run itself: read both feeds, store what is new, show the day."""

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime

from .feeds import MADRID, Source, fetch, parse
from .store import Article, articles_for_day, insert_articles, record_fetch

MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def today(now: datetime | None = None) -> str:
    """The Europe/Madrid day the reader means by 'hoy'."""
    return (now or datetime.now(UTC)).astimezone(MADRID).date().isoformat()


def spanish_date(day: str) -> str:
    """'2026-08-30' as '30 de agosto', without depending on a system locale."""
    parsed = date.fromisoformat(day)
    return f"{parsed.day} de {MONTHS[parsed.month - 1]}"


def local_time(pubdate_utc: str) -> str:
    return datetime.fromisoformat(pubdate_utc).astimezone(MADRID).strftime("%H:%M")


def ingest(
    connection: sqlite3.Connection,
    sources: Iterable[Source],
    progress: Callable[[str], None],
    now: datetime | None = None,
) -> None:
    """Read every source, store what is new, and leave a trace of each read.

    One source failing must not cost the other one: the full taxonomy of
    failures is T15's job, but the skeleton already degrades rather than dies.
    """
    fetched_at = (now or datetime.now(UTC)).isoformat()
    for source in sources:
        try:
            articles = parse(source, fetch(source))
        except Exception as error:
            record_fetch(connection, source.name, fetched_at, ok=False)
            progress(f"{source.name}: no se pudo leer ({error})")
            continue
        stored = insert_articles(connection, articles, fetched_at)
        record_fetch(
            connection, source.name, fetched_at, ok=True, item_count=len(articles)
        )
        progress(f"{source.name}: {len(articles)} items, {stored} nuevos")


def headlines(articles: Sequence[Article], day: str) -> str:
    """The day as a plain list. The grouped summary arrives with T11."""
    if not articles:
        return f"Día {spanish_date(day)} · sin noticias"
    lines = [f"Día {spanish_date(day)} · {len(articles)} noticias", ""]
    lines += [
        f"  {local_time(article.pubdate)} · {article.source} · {article.title}"
        for article in articles
    ]
    return "\n".join(lines)


def run(
    connection: sqlite3.Connection,
    sources: Iterable[Source],
    progress: Callable[[str], None],
    now: datetime | None = None,
) -> str:
    """Everything a run does, minus the printing."""
    ingest(connection, sources, progress, now)
    day = today(now)
    return headlines(articles_for_day(connection, day), day)
