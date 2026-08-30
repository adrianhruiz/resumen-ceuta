"""Integration tests for a whole run, against a local server and a frozen clock."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resumen.feeds import SOURCES, Source
from resumen.pipeline import headlines, ingest, run, spanish_date, today
from resumen.store import Article, articles_for_day, connect

NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def test_the_real_feeds_are_https() -> None:
    # fetch() accepts plain http so a local server can stand in for a feed.
    # That the two real ones are https is a separate promise, kept here.
    assert all(source.url.startswith("https://") for source in SOURCES)


def test_both_feeds_land_in_the_database(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    ingest(database, served_feeds, silent, NOON)
    stored = database.execute(
        "SELECT source, COUNT(*) FROM articles GROUP BY source"
    ).fetchall()
    assert dict(stored) == {"faro": 10, "pueblo": 137}


def test_every_read_is_recorded(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    ingest(database, served_feeds, silent, NOON)
    rows = database.execute(
        "SELECT source, ok, item_count FROM fetches ORDER BY source"
    ).fetchall()
    assert rows == [("faro", 1, 10), ("pueblo", 1, 137)]


def test_a_second_run_adds_nothing(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    ingest(database, served_feeds, silent, NOON)
    ingest(database, served_feeds, silent, NOON)
    assert database.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 147
    # But both reads are on the record: two runs, four rows.
    assert database.execute("SELECT COUNT(*) FROM fetches").fetchone()[0] == 4


def test_a_failing_source_does_not_cost_the_other(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    faro, pueblo = served_feeds
    broken = Source("faro", faro.url + "/no-existe", faro.id_pattern)
    ingest(database, (broken, pueblo), silent, NOON)

    assert database.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 137
    rows = database.execute(
        "SELECT source, ok, item_count FROM fetches ORDER BY source"
    ).fetchall()
    assert rows == [("faro", 0, None), ("pueblo", 1, 137)]


def test_the_failure_is_reported_to_the_reader(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    faro, pueblo = served_feeds
    said: list[str] = []
    ingest(
        database,
        (Source("faro", faro.url + "/no", faro.id_pattern),),
        said.append,
        NOON,
    )
    assert any("faro" in line and "no se pudo leer" in line for line in said)


def test_a_run_prints_the_headlines_of_the_day(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    output = run(database, served_feeds, silent, NOON)
    assert output.startswith("Día 30 de agosto · ")
    assert "El PP denuncia" in output
    # Only that day: the fixtures reach back to February.
    assert len(output.splitlines()) == 2 + len(articles_for_day(database, "2026-08-30"))


def test_a_day_without_news_says_so(database: sqlite3.Connection) -> None:
    assert run(database, (), silent, NOON) == "Día 30 de agosto · sin noticias"


def test_the_day_is_the_madrid_one() -> None:
    # 22:00 UTC in August is already tomorrow for the reader.
    assert today(datetime(2026, 8, 30, 21, 59, tzinfo=UTC)) == "2026-08-30"
    assert today(datetime(2026, 8, 30, 22, 0, tzinfo=UTC)) == "2026-08-31"


@pytest.mark.parametrize(
    ("day", "spanish"),
    [
        ("2026-01-01", "1 de enero"),
        ("2026-08-30", "30 de agosto"),
        ("2026-12-25", "25 de diciembre"),
    ],
)
def test_dates_are_written_in_spanish_without_a_locale(day: str, spanish: str) -> None:
    assert spanish_date(day) == spanish


def test_headlines_are_listed_oldest_first() -> None:
    articles = [
        Article(
            "faro",
            "2",
            "g2",
            "Segunda",
            None,
            None,
            "u",
            "2026-08-30T16:00:00+00:00",
            "2026-08-30",
        ),
        Article(
            "faro",
            "1",
            "g1",
            "Primera",
            None,
            None,
            "u",
            "2026-08-30T06:00:00+00:00",
            "2026-08-30",
        ),
    ]
    listed = headlines(sorted(articles, key=lambda a: a.pubdate), "2026-08-30")
    assert listed.index("Primera") < listed.index("Segunda")
    # Times are shown in Madrid, not UTC.
    assert "08:00 · faro · Primera" in listed
