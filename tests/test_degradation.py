"""What the app does when a source, or the model, lets it down."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from conftest import FakeModel
from resumen.feeds import SOURCES, FeedError, Source, parse
from resumen.gemini import TransportError
from resumen.pipeline import NothingToShow, ingest, run
from resumen.store import connect, read_summary

NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
FARO, PUEBLO = SOURCES


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def broken(httpserver: HTTPServer, name: str, status: int, body: bytes = b"") -> Source:
    path = f"/{name}-roto"
    httpserver.expect_request(path).respond_with_data(body, status=status)
    return Source(
        name, httpserver.url_for(path), FARO.id_pattern, display=name.capitalize()
    )


# --- the shapes a broken feed takes --------------------------------------


def test_an_error_page_served_with_200_is_not_a_quiet_day() -> None:
    # The dangerous one: an outlet serving HTML with status 200 parses without
    # complaint and would be filed as "published nothing today".
    with pytest.raises(FeedError, match="no es un feed"):
        parse(FARO, b"<html><body>Error 404</body></html>")


def test_something_that_is_not_xml_is_refused() -> None:
    with pytest.raises(FeedError, match="no es un feed"):
        parse(FARO, b"no soy xml en absoluto")


def test_an_empty_but_valid_feed_is_a_quiet_day() -> None:
    # No items and no error: the outlet published nothing, which is a fact and
    # not a failure.
    empty = (
        b'<?xml version="1.0"?><rss version="2.0">'
        b"<channel><title>x</title></channel></rss>"
    )
    assert parse(FARO, empty) == []


def test_a_truncated_feed_keeps_what_parsed() -> None:
    # Half a document still carries real articles; throwing them away would
    # lose news that nothing else will bring back.
    truncated = (FIXTURES / "faro-2026-08-30.xml").read_bytes()[:20000]
    assert len(parse(FARO, truncated)) > 0


@pytest.mark.parametrize("status", [404, 500, 503])
def test_an_http_error_is_reported_with_its_code(
    httpserver: HTTPServer, status: int
) -> None:
    from resumen.feeds import fetch

    with pytest.raises(FeedError, match=str(status)):
        fetch(broken(httpserver, "faro", status))


def test_an_unreachable_host_is_reported() -> None:
    from resumen.feeds import fetch

    unreachable = Source("faro", "http://127.0.0.1:1/feed", FARO.id_pattern)
    with pytest.raises(FeedError, match="no responde"):
        fetch(unreachable)


# --- one source down -----------------------------------------------------


def test_the_other_source_still_gets_read(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    httpserver: HTTPServer,
) -> None:
    _, pueblo = served_feeds
    failed = ingest(database, (broken(httpserver, "faro", 500), pueblo), silent, NOON)

    assert failed == ["faro"]
    assert database.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 137


def test_the_failure_is_on_the_record(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    httpserver: HTTPServer,
) -> None:
    _, pueblo = served_feeds
    ingest(database, (broken(httpserver, "faro", 500), pueblo), silent, NOON)
    rows = database.execute(
        "SELECT source, ok, item_count FROM fetches ORDER BY source"
    ).fetchall()
    assert rows == [("faro", 0, None), ("pueblo", 1, 137)]


def test_the_header_admits_it(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    httpserver: HTTPServer,
    fake_model: FakeModel,
) -> None:
    _, pueblo = served_feeds
    output = run(
        database, (broken(httpserver, "faro", 500), pueblo), fake_model, silent, NOON
    )
    assert "Faro: no se pudo leer" in output
    assert "El Pueblo: completo hasta" in output


def test_the_reader_is_told_which_source_and_why(
    database: sqlite3.Connection, httpserver: HTTPServer
) -> None:
    said: list[str] = []
    ingest(database, (broken(httpserver, "faro", 503),), said.append, NOON)
    assert any("Faro" in line and "503" in line for line in said)


# --- everything down -----------------------------------------------------


def test_nothing_readable_and_nothing_stored_says_so(
    database: sqlite3.Connection, httpserver: HTTPServer, fake_model: FakeModel
) -> None:
    sources = (broken(httpserver, "faro", 500), broken(httpserver, "pueblo", 500))
    with pytest.raises(NothingToShow, match="Comprueba la conexión"):
        run(database, sources, fake_model, silent, NOON)
    # And the model was never troubled about it.
    assert fake_model.calls == 0


def test_nothing_readable_but_something_stored_still_reads(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    httpserver: HTTPServer,
    fake_model: FakeModel,
) -> None:
    # The network went down after this morning's run. A stale summary with an
    # honest header beats refusing to print anything.
    ingest(database, served_feeds, silent, NOON)
    broken_sources = (
        broken(httpserver, "faro", 500),
        broken(httpserver, "pueblo", 500),
    )

    output = run(database, broken_sources, fake_model, silent, NOON)
    # This morning's reads still count as coverage; the header adds that both
    # sources have stopped answering since.
    assert "El Pueblo: completo hasta 14:00, ahora caído" in output
    assert "Faro: 1 lectura (parcial), ahora caído" in output
    assert "Día 30 de agosto · 34 noticias" in output


# --- the model down ------------------------------------------------------


def test_an_exhausted_model_leaves_the_cache_untouched(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    fake_model: FakeModel,
) -> None:
    run(database, served_feeds, fake_model, silent, NOON)
    before = read_summary(database, "2026-08-30")

    class Dead(FakeModel):
        def generate(self, prompt: str) -> str:
            raise RuntimeError("503 UNAVAILABLE")

    # Force it to ask again, and have the asking fail.
    with pytest.raises(TransportError):
        run(database, served_feeds, Dead(), silent, NOON, force=True)
    assert read_summary(database, "2026-08-30") == before


def test_the_next_run_recovers(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    class Dead(FakeModel):
        def generate(self, prompt: str) -> str:
            self.calls += 1
            raise RuntimeError("503 UNAVAILABLE")

    with pytest.raises(TransportError):
        run(database, served_feeds, Dead(), silent, NOON)

    recovered = FakeModel()
    assert "Día 30 de agosto" in run(database, served_feeds, recovered, silent, NOON)
    assert recovered.calls == 1


def test_the_articles_survive_a_dead_model(
    database: sqlite3.Connection, served_feeds: tuple[Source, ...]
) -> None:
    class Dead(FakeModel):
        def generate(self, prompt: str) -> str:
            raise RuntimeError("503")

    with pytest.raises(TransportError):
        run(database, served_feeds, Dead(), silent, NOON)
    assert database.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 147
    assert database.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0
