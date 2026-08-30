"""The run itself: read both feeds, store what is new, show the day."""

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from .feeds import MADRID, Source, fetch, parse
from .gemini import Model, ask
from .payload import Summary, validate
from .render import header, render
from .store import (
    Article,
    articles_for_day,
    fetches_between,
    insert_articles,
    record_fetch,
)

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


def day_bounds(day: str) -> tuple[str, str]:
    """The half-open UTC interval covering a Europe/Madrid calendar day.

    Not a fixed 24 hours: the day the clocks change is 23 or 25 hours long,
    and asking for midnight-to-midnight in local time is what gets that right.
    """
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), MADRID)
    end = start + timedelta(days=1)
    # Re-anchor on the local date so a DST jump does not land mid-day.
    end = datetime.combine(
        (start + timedelta(days=1)).date(), datetime.min.time(), MADRID
    )
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def spanish_date(day: str) -> str:
    """'2026-08-30' as '30 de agosto', without depending on a system locale."""
    parsed = date.fromisoformat(day)
    return f"{parsed.day} de {MONTHS[parsed.month - 1]}"


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


def summarise(articles: Sequence[Article], model: Model) -> Summary:
    """One call, and nothing believed until it has been checked."""
    return validate(ask(model, articles), {article.id for article in articles})


def run(
    connection: sqlite3.Connection,
    sources: Iterable[Source],
    model: Callable[[], Model],
    progress: Callable[[str], None],
    now: datetime | None = None,
) -> str:
    """Everything a run does, minus the printing.

    `model` is a factory, not a model: a day with nothing published must not
    pay for building a client, and building one loads the SDK.
    """
    ingest(connection, sources, progress, now)
    day = today(now)
    articles = articles_for_day(connection, day)
    start, end = day_bounds(day)
    top = header(
        spanish_date(day), len(articles), fetches_between(connection, start, end)
    )
    if not articles:
        # Nothing to summarise is an answer, and it costs no API call.
        return top

    progress(f"resumiendo {len(articles)} noticias…")
    body = render(summarise(articles, model()))
    return f"{top}\n\n{body}" if body else top
