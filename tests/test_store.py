"""Integration tests for the store, against a real SQLite file."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

from resumen.store import (
    Article,
    articles_for_day,
    connect,
    insert_articles,
    record_fetch,
)

FETCHED_AT = "2026-08-30T12:00:00+00:00"


def tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def test_the_schema_is_created_on_an_empty_database(tmp_path: Path) -> None:
    connection = connect(tmp_path / "nueva.sqlite3")
    assert tables(connection) >= {"articles", "fetches", "summaries"}


def test_the_directory_is_created_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "no" / "existe" / "db.sqlite3"
    connect(path)
    assert path.is_file()


def test_reopening_an_existing_database_keeps_its_rows(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    path = tmp_path / "db.sqlite3"
    insert_articles(connect(path), [article()], FETCHED_AT)
    # Reopening runs the schema again: it must not wipe or fail.
    assert len(articles_for_day(connect(path), "2026-08-30")) == 1


def test_the_same_article_twice_leaves_one_row(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    assert insert_articles(connection, [article()], FETCHED_AT) == 1
    assert insert_articles(connection, [article()], FETCHED_AT) == 0
    assert len(articles_for_day(connection, "2026-08-30")) == 1


def test_a_corrected_headline_does_not_duplicate(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    # El Pueblo builds its guid out of the headline, so an editor fixing a typo
    # changes the guid while the article stays the same one.
    connection = connect(tmp_path / "db.sqlite3")
    original = article(
        source="pueblo", guid=".../pp-denuncia_1_1187097.html", title="PP denunica"
    )
    corrected = article(
        source="pueblo", guid=".../pp-denuncia-b_1_1187097.html", title="PP denuncia"
    )
    insert_articles(connection, [original], FETCHED_AT)
    insert_articles(connection, [corrected], FETCHED_AT)

    stored = articles_for_day(connection, "2026-08-30")
    assert len(stored) == 1
    # First one wins: the app never rewrites what it already summarised.
    assert stored[0].title == "PP denunica"


def test_the_same_external_id_in_both_sources_are_two_articles(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    insert_articles(
        connection,
        [
            article(source="faro", external_id="1"),
            article(source="pueblo", external_id="1"),
        ],
        FETCHED_AT,
    )
    assert len(articles_for_day(connection, "2026-08-30")) == 2


def test_only_that_day_comes_back(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    insert_articles(
        connection,
        [
            article(external_id="1", day="2026-08-29"),
            article(external_id="2", day="2026-08-30"),
            article(external_id="3", day="2026-08-31"),
        ],
        FETCHED_AT,
    )
    assert [a.external_id for a in articles_for_day(connection, "2026-08-30")] == ["2"]


def test_a_day_with_nothing_comes_back_empty(tmp_path: Path) -> None:
    assert articles_for_day(connect(tmp_path / "db.sqlite3"), "2026-08-30") == []


def test_articles_come_back_oldest_first(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    insert_articles(
        connection,
        [
            article(external_id="tarde", pubdate="2026-08-30T18:00:00+00:00"),
            article(external_id="manana", pubdate="2026-08-30T06:00:00+00:00"),
        ],
        FETCHED_AT,
    )
    assert [a.external_id for a in articles_for_day(connection, "2026-08-30")] == [
        "manana",
        "tarde",
    ]


def test_every_field_survives_the_round_trip(
    tmp_path: Path, article: Callable[..., Article]
) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    original = article(description=None, body=None)
    insert_articles(connection, [original], FETCHED_AT)
    assert articles_for_day(connection, "2026-08-30")[0] == original


def test_the_article_id_is_source_and_external_id(
    article: Callable[..., Article],
) -> None:
    assert article(source="faro", external_id="1436869").id == "faro:1436869"


def test_a_successful_read_is_recorded(tmp_path: Path) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    record_fetch(connection, "faro", FETCHED_AT, ok=True, item_count=10)
    assert list(connection.execute("SELECT source, ok, item_count FROM fetches")) == [
        ("faro", 1, 10)
    ]


def test_a_failed_read_is_recorded_too(tmp_path: Path) -> None:
    # Without this row there is no telling "the outlet published nothing"
    # from "the app never managed to read it".
    connection = connect(tmp_path / "db.sqlite3")
    record_fetch(connection, "pueblo", FETCHED_AT, ok=False)
    assert list(connection.execute("SELECT source, ok, item_count FROM fetches")) == [
        ("pueblo", 0, None)
    ]
