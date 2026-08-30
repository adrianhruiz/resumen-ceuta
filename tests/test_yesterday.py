"""What happens when today has barely any news."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import FakeModel
from resumen.pipeline import THIN_DAY, previous_day, run
from resumen.store import Article, connect, insert_articles, read_summary

NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
TODAY = "2026-08-30"
YESTERDAY = "2026-08-29"


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def store(
    database: sqlite3.Connection, day: str, count: int, prefix: str = "a"
) -> None:
    insert_articles(
        database,
        [
            Article(
                "faro",
                f"{prefix}{i}",
                f"g{prefix}{i}",
                f"Titular {prefix}{i}",
                "Entradilla",
                None,
                "https://elfarodeceuta.es/x/",
                f"{day}T1{i % 10}:00:00+00:00",
                day,
            )
            for i in range(count)
        ],
        "2026-08-30T12:00:00+00:00",
    )


# --- when yesterday joins in ---------------------------------------------


def test_a_thin_day_brings_yesterday_along(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 4)
    store(database, YESTERDAY, 20, prefix="b")
    output = run(database, (), fake_model, silent, NOON)
    assert "— Ayer, 29 de agosto —" in output


def test_a_full_day_stands_on_its_own(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, THIN_DAY)
    store(database, YESTERDAY, 20, prefix="b")
    assert "Ayer" not in run(database, (), fake_model, silent, NOON)


def test_the_threshold_is_exactly_five(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, YESTERDAY, 20, prefix="b")
    store(database, TODAY, 4)
    assert "Ayer" in run(database, (), fake_model, silent, NOON)
    store(database, TODAY, 5)
    assert "Ayer" not in run(database, (), fake_model, silent, NOON)


def test_a_day_with_nothing_at_all_still_brings_yesterday(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    # Nothing published yet this morning is the thinnest day there is.
    store(database, YESTERDAY, 20, prefix="b")
    output = run(database, (), fake_model, silent, NOON)
    assert output.startswith("Día 30 de agosto · sin noticias")
    assert "— Ayer, 29 de agosto —" in output


def test_without_a_yesterday_there_is_no_block(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 2)
    output = run(database, (), fake_model, silent, NOON)
    assert "Ayer" not in output


def test_todays_summary_comes_first(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 2)
    store(database, YESTERDAY, 20, prefix="b")
    output = run(database, (), fake_model, silent, NOON)
    assert output.index("Día 30 de agosto") < output.index("Ayer")


# --- what it costs -------------------------------------------------------


def test_the_thin_morning_costs_two_calls_once(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 2)
    store(database, YESTERDAY, 20, prefix="b")
    model = fake_model
    run(database, (), model, silent, NOON)
    assert model.calls == 2


def test_the_rest_of_the_morning_costs_nothing(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    # Yesterday is a row of its own, so it is paid for once and then read.
    store(database, TODAY, 2)
    store(database, YESTERDAY, 20, prefix="b")
    model = fake_model
    run(database, (), model, silent, NOON)
    run(database, (), model, silent, NOON)
    run(database, (), model, silent, NOON)
    assert model.calls == 2


def test_each_day_gets_its_own_row(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 2)
    store(database, YESTERDAY, 20, prefix="b")
    run(database, (), fake_model, silent, NOON)

    assert read_summary(database, TODAY) is not None
    assert read_summary(database, YESTERDAY) is not None
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 2


def test_yesterday_is_not_recomputed_when_today_fills_up(
    database: sqlite3.Connection, fake_model: FakeModel
) -> None:
    store(database, TODAY, 2)
    store(database, YESTERDAY, 20, prefix="b")
    model = fake_model
    run(database, (), model, silent, NOON)

    # The news picks up and yesterday drops out of the output entirely.
    store(database, TODAY, 10)
    output = run(database, (), model, silent, NOON)
    assert "Ayer" not in output
    assert model.calls == 3


def test_previous_day_crosses_the_month() -> None:
    assert previous_day("2026-09-01") == "2026-08-31"
    assert previous_day("2026-01-01") == "2025-12-31"
    assert previous_day("2026-03-01") == "2026-02-28"
