"""The run itself: read both feeds, store what is new, show the day."""

import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from .feeds import MADRID, Source, fetch, parse
from .gemini import Model, ask, input_hash
from .payload import Summary, validate
from .render import header, render
from .store import (
    Article,
    articles_for_day,
    fetches_between,
    insert_articles,
    read_summary,
    record_fetch,
    write_summary,
)

# Below this, a day is too thin to be worth reading on its own and yesterday
# is printed underneath it. Five is a judgement call, not a measurement.
THIN_DAY = 5

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


def previous_day(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


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


def summary_for_day(
    connection: sqlite3.Connection,
    day: str,
    articles: Sequence[Article],
    model: Callable[[], Model],
    progress: Callable[[str], None],
    now: datetime | None = None,
    force: bool = False,
) -> Summary:
    """The day's summary, asking the model only for what it has not judged.

    Running the app twice in a row must not cost twice. The stored summary
    knows which articles it already accounted for, so a later run pays only
    for what appeared since, handing the previous summary back as context.
    """
    stored = None if force else read_summary(connection, day)
    if force:
        progress("--force: se rehace el día ignorando la caché")
    if stored is not None and stored.input_hash != input_hash(stored.covered_ids):
        # The instructions or the model moved. What they produced is stale, so
        # it is dropped here and the day is summarised from scratch below.
        progress("el prompt o el modelo han cambiado: se rehace el día entero")
        stored = None

    if stored is not None:
        covered = set(stored.covered_ids)
        pending = [article for article in articles if article.id not in covered]
        if not pending:
            progress("nada nuevo desde la última vez: sin llamar al modelo")
            return validate(json.loads(stored.payload), covered)
        progress(f"resumiendo {len(pending)} noticias nuevas…")
        summary = validate(
            ask(model(), pending, json.loads(stored.payload)),
            covered | {article.id for article in pending},
        )
    else:
        progress(f"resumiendo {len(articles)} noticias…")
        summary = summarise(articles, model())

    written_at = (now or datetime.now(UTC)).isoformat()
    write_summary(
        connection,
        day,
        summary.covered_ids,
        input_hash(summary.covered_ids),
        summary.as_json(),
        written_at,
    )
    return summary


def run(
    connection: sqlite3.Connection,
    sources: Iterable[Source],
    model: Callable[[], Model],
    progress: Callable[[str], None],
    now: datetime | None = None,
    force: bool = False,
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
    blocks = []
    if articles:
        # Nothing to summarise is an answer too, and it costs no API call.
        blocks.append(
            render(
                summary_for_day(connection, day, articles, model, progress, now, force)
            )
        )

    # A thin morning is not worth reading on its own, so yesterday comes along.
    # It is its own row in `summaries`, so it costs one call the first time of
    # the day and nothing for the rest of it.
    if len(articles) < THIN_DAY:
        yesterday = previous_day(day)
        earlier = articles_for_day(connection, yesterday)
        if earlier:
            progress(f"hoy va flojo: se añade el {spanish_date(yesterday)}")
            body = render(
                summary_for_day(
                    connection, yesterday, earlier, model, progress, now, force
                )
            )
            if body:
                blocks.append(f"— Ayer, {spanish_date(yesterday)} —\n\n{body}")

    return "\n\n".join([top, *[block for block in blocks if block]])
