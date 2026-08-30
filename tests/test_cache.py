"""The incremental cache: what a second run costs, and what invalidates it."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resumen import gemini
from resumen.gemini import input_hash
from resumen.pipeline import summary_for_day
from resumen.store import Article, connect, read_summary

NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
DAY = "2026-08-30"


class Counting:
    """A model that answers about whatever it is given, and counts the asking."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self) -> Counting:
        return self

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        sent = [line.split('"')[3] for line in prompt.splitlines() if '"id"' in line]
        previous = []
        if "RESUMEN QUE YA EXISTE" in prompt:
            body = prompt.split("RESUMEN QUE YA EXISTE")[1].rsplit(
                "ARTÍCULOS NUEVOS:", 1
            )[0]
            previous = json.loads(body[body.index("{") : body.rindex("}") + 1])[
                "descartados"
            ]
        return json.dumps({"temas": [], "descartados": sorted({*previous, *sent})})


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def articles(count: int, offset: int = 0) -> list[Article]:
    return [
        Article(
            "faro",
            str(i),
            f"g{i}",
            f"Titular {i}",
            "Entradilla",
            None,
            "https://elfarodeceuta.es/x/",
            f"2026-08-30T{i % 24:02d}:00:00+00:00",
            DAY,
        )
        for i in range(offset, offset + count)
    ]


def summarise(
    database: sqlite3.Connection, model: Counting, items: list[Article]
) -> None:
    summary_for_day(database, DAY, items, model, silent, NOON)


# --- what a repeated run costs -------------------------------------------


def test_the_first_run_asks_once(database: sqlite3.Connection) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    assert model.calls == 1


def test_a_second_run_with_nothing_new_asks_nothing(
    database: sqlite3.Connection,
) -> None:
    # The whole point of the design: opening the app again is free.
    model = Counting()
    summarise(database, model, articles(10))
    summarise(database, model, articles(10))
    assert model.calls == 1


def test_ten_more_articles_cost_one_call_about_ten(
    database: sqlite3.Connection,
) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    summarise(database, model, articles(20))

    assert model.calls == 2
    second = model.prompts[1]
    # Only the new ones are paid for...
    assert '"faro:10"' in second
    assert '"faro:0"' not in second.rsplit("ARTÍCULOS NUEVOS:", 1)[1]
    # ...and the previous summary rides along as context.
    assert "RESUMEN QUE YA EXISTE" in second


def test_the_cost_follows_the_news_not_the_openings(
    database: sqlite3.Connection,
) -> None:
    model = Counting()
    for _ in range(5):
        summarise(database, model, articles(10))
    summarise(database, model, articles(11))
    for _ in range(5):
        summarise(database, model, articles(11))
    # Eleven articles, two calls, twelve runs.
    assert model.calls == 2


# --- what is stored ------------------------------------------------------


def test_the_covered_ids_are_stored_sorted(database: sqlite3.Connection) -> None:
    summarise(database, Counting(), articles(12))
    stored = read_summary(database, DAY)
    assert stored is not None
    assert list(stored.covered_ids) == sorted(stored.covered_ids)
    assert len(stored.covered_ids) == 12


def test_the_summary_is_written_once_per_day(database: sqlite3.Connection) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    summarise(database, model, articles(20))
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 1


def test_a_cached_day_comes_back_identical(database: sqlite3.Connection) -> None:
    model = Counting()
    first = summary_for_day(database, DAY, articles(10), model, silent, NOON)
    second = summary_for_day(database, DAY, articles(10), model, silent, NOON)
    assert first == second


# --- what makes it stale -------------------------------------------------


def test_editing_the_prompt_redoes_the_day(
    database: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    monkeypatch.setattr(gemini, "PROMPT", gemini.PROMPT + "\nY sé más breve.")

    summarise(database, model, articles(10))
    assert model.calls == 2
    # Redone from scratch, not extended: no previous summary was handed back.
    assert "RESUMEN QUE YA EXISTE" not in model.prompts[1]


def test_changing_the_model_redoes_the_day(
    database: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    monkeypatch.setattr(gemini, "MODEL", "gemini-9-flash")

    summarise(database, model, articles(10))
    assert model.calls == 2


def test_the_reader_is_told_the_day_is_being_redone(
    database: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    monkeypatch.setattr(gemini, "MODEL", "gemini-9-flash")

    said: list[str] = []
    summary_for_day(database, DAY, articles(10), model, said.append, NOON)
    assert any("han cambiado" in line for line in said)


def test_the_hash_ignores_the_order_of_the_ids() -> None:
    # covered_ids are stored sorted precisely so the model's whim about order
    # cannot invalidate a perfectly good summary.
    assert input_hash(["faro:2", "faro:1"]) == input_hash(["faro:1", "faro:2"])


def test_the_hash_changes_with_the_articles() -> None:
    assert input_hash(["faro:1"]) != input_hash(["faro:1", "faro:2"])


def test_a_failed_call_leaves_the_previous_summary_alone(
    database: sqlite3.Connection,
) -> None:
    class Dead(Counting):
        def generate(self, prompt: str) -> str:
            self.calls += 1
            raise RuntimeError("503")

    model = Counting()
    summarise(database, model, articles(10))
    before = read_summary(database, DAY)

    with pytest.raises(Exception, match="intentos"):
        summary_for_day(database, DAY, articles(20), Dead(), silent, NOON)
    assert read_summary(database, DAY) == before


# --- the shortcuts, and the way past them --------------------------------


def test_force_asks_again_even_with_nothing_new(database: sqlite3.Connection) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    summary_for_day(database, DAY, articles(10), model, silent, NOON, force=True)
    assert model.calls == 2


def test_force_redoes_the_day_from_scratch(database: sqlite3.Connection) -> None:
    # Not an extension of what is stored: --force exists for when the stored
    # summary is the thing you distrust.
    model = Counting()
    summarise(database, model, articles(10))
    summary_for_day(database, DAY, articles(20), model, silent, NOON, force=True)
    assert "RESUMEN QUE YA EXISTE" not in model.prompts[1]
    assert '"faro:0"' in model.prompts[1]


def test_force_replaces_what_was_stored(database: sqlite3.Connection) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    summary_for_day(database, DAY, articles(20), model, silent, NOON, force=True)

    stored = read_summary(database, DAY)
    assert stored is not None
    assert len(stored.covered_ids) == 20
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 1


def test_force_says_what_it_is_doing(database: sqlite3.Connection) -> None:
    said: list[str] = []
    summary_for_day(
        database, DAY, articles(3), Counting(), said.append, NOON, force=True
    )
    assert any("--force" in line for line in said)


def test_a_covered_day_is_rendered_without_asking(database: sqlite3.Connection) -> None:
    model = Counting()
    summarise(database, model, articles(10))
    said: list[str] = []
    summary_for_day(database, DAY, articles(10), model, said.append, NOON)
    assert model.calls == 1
    assert any("sin llamar al modelo" in line for line in said)
