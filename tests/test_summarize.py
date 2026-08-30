"""A whole run, from feed to summary, with a scripted model."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resumen.feeds import Source
from resumen.gemini import TransportError
from resumen.payload import InvalidPayload
from resumen.pipeline import run, summarise
from resumen.store import Article, articles_for_day, connect

NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


class Scripted:
    """A model that answers with whatever the test decided, and counts calls."""

    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self) -> Scripted:
        return self

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def answering(database: sqlite3.Connection, day: str = "2026-08-30") -> Scripted:
    """A model that returns a summary accounting for exactly today's articles."""

    def build() -> str:
        ids = [article.id for article in articles_for_day(database, day)]
        return json.dumps(
            {
                "temas": [
                    {
                        "tema": "Frontera",
                        "entradas": [{"texto": "algo pasó", "ids": ids[:1]}],
                    }
                ],
                "descartados": ids[1:],
            }
        )

    return Scripted(build())


def test_a_whole_run_prints_header_and_summary(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    from resumen.pipeline import ingest

    ingest(database, served_feeds, silent, NOON)
    model = answering(database)

    output = run(database, served_feeds, model, silent, NOON)
    lines = output.splitlines()
    assert lines[0].startswith("Día 30 de agosto · 34 noticias")
    assert lines[1].startswith("El Pueblo: completo hasta")
    assert "Frontera:\n  - algo pasó" in output


def test_exactly_one_call_per_run(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    # The budget that protects the API key. Everything else is a nicety.
    from resumen.pipeline import ingest

    ingest(database, served_feeds, silent, NOON)
    model = answering(database)
    run(database, served_feeds, model, silent, NOON)
    assert model.calls == 1


def test_a_day_with_nothing_costs_no_call(database: sqlite3.Connection) -> None:
    model = Scripted(AssertionError("no debería llamarse"))
    output = run(database, (), model, silent, NOON)
    assert model.calls == 0
    assert output.startswith("Día 30 de agosto · sin noticias")


def test_the_model_is_not_even_built_when_there_is_nothing(
    database: sqlite3.Connection,
) -> None:
    # Building a client loads the SDK; an empty day must not pay for it.
    def explode() -> object:
        raise AssertionError("no debería construirse")

    run(database, (), explode, silent, NOON)


def test_a_dead_model_leaves_the_articles_stored(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    model = Scripted(RuntimeError("503"))
    with pytest.raises(TransportError):
        run(database, served_feeds, model, silent, NOON)
    # The reading happened and is kept; only the summary is missing.
    assert database.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 147
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0


def test_an_unbelievable_answer_stops_the_run(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    model = Scripted(json.dumps({"temas": [], "descartados": []}))
    with pytest.raises(InvalidPayload):
        run(database, served_feeds, model, silent, NOON)
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0


def test_the_summary_is_checked_against_what_was_sent() -> None:
    articles = [
        Article(
            "faro",
            "1",
            "g",
            "T",
            "E",
            None,
            "u",
            "2026-08-30T10:00:00+00:00",
            "2026-08-30",
        )
    ]
    invented = json.dumps(
        {
            "temas": [
                {"tema": "Otros", "entradas": [{"texto": "x", "ids": ["faro:9"]}]}
            ],
            "descartados": [],
        }
    )
    with pytest.raises(InvalidPayload):
        summarise(articles, Scripted(invented))


def test_an_empty_day_costs_nothing_even_with_force(
    database: sqlite3.Connection,
) -> None:
    # --force is about distrusting a stored summary, not about conjuring one:
    # with no articles there is nothing to ask about.
    model = Scripted(AssertionError("no debería llamarse"))
    output = run(database, (), model, silent, NOON, force=True)
    assert model.calls == 0
    assert "sin noticias" in output


def test_the_cli_passes_force_through(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from resumen import cli

    seen: list[bool] = []

    def spy(connection, sources, model, progress, force=False):  # noqa: ANN001, ANN202
        seen.append(force)
        return "listo"

    monkeypatch.setattr(cli, "run", spy)
    monkeypatch.setattr(cli, "connect", lambda: database)
    monkeypatch.setattr(cli, "load_api_key", lambda warn: "clave")
    assert cli.main([]) == 0
    assert cli.main(["--force"]) == 0
    assert seen == [False, True]
