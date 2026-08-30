"""Performance budgets.

Every threshold here is set several times above what was measured on
2026-08-30, and the comment on each says what that measurement was. A failure
is meant to mean a regression of an order of magnitude, not a busy CI runner.
"""

import json
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import FakeModel
from resumen.feeds import SOURCES, Source, parse
from resumen.gemini import build_prompt
from resumen.pipeline import run
from resumen.store import articles_for_day, connect, insert_articles

pytestmark = pytest.mark.perf

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOON = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
FARO, PUEBLO = SOURCES

# 4250 real tokens for a full day, at 3.42 characters per token (counted
# against the API on 2026-08-30). The budget is 6000 tokens; measuring
# characters keeps this test offline and deterministic.
CHARACTERS_PER_TOKEN = 3.42
TOKEN_BUDGET = 6000
CHARACTER_BUDGET = int(TOKEN_BUDGET * CHARACTERS_PER_TOKEN)


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db.sqlite3")


def silent(message: str) -> None:
    pass


def recorded_day() -> list:
    articles = parse(FARO, (FIXTURES / "faro-2026-08-30.xml").read_bytes())
    articles += parse(PUEBLO, (FIXTURES / "pueblo-2026-08-30.xml").read_bytes())
    return articles


# --- the budget that protects the API key --------------------------------


def test_a_run_asks_the_model_at_most_once(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    fake_model: FakeModel,
) -> None:
    run(database, served_feeds, fake_model, silent, NOON)
    assert fake_model.calls <= 1


def test_a_cache_warm_run_asks_nothing(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    fake_model: FakeModel,
) -> None:
    run(database, served_feeds, fake_model, silent, NOON)
    run(database, served_feeds, fake_model, silent, NOON)
    assert fake_model.calls == 1


# --- time ----------------------------------------------------------------


def test_a_cache_warm_run_is_immediate(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    fake_model: FakeModel,
) -> None:
    # Measured against the real feeds and a warm cache: 0.63 s, most of it
    # network. Budget 1.5 s, as the plan says.
    run(database, served_feeds, fake_model, silent, NOON)
    started = time.perf_counter()
    run(database, served_feeds, fake_model, silent, NOON)
    assert time.perf_counter() - started < 1.5


def test_starting_up_is_not_noticeable() -> None:
    # Measured: 92 ms. Budget 400 ms. This is what the lazy import of the
    # google-genai SDK buys, so a regression here usually means someone moved
    # that import back to the top of a module.
    started = time.perf_counter()
    subprocess.run(
        [sys.executable, "-m", "resumen.cli", "--version"],
        capture_output=True,
        check=True,
    )
    assert time.perf_counter() - started < 0.4


def test_reading_both_feeds_is_quick() -> None:
    # Measured: 0.078 s for 147 items. Budget 2 s.
    started = time.perf_counter()
    recorded_day()
    assert time.perf_counter() - started < 2.0


def test_storing_a_days_articles_is_quick(database: sqlite3.Connection) -> None:
    # Measured: 0.001 s for 147 articles. Budget 1 s.
    articles = recorded_day()
    started = time.perf_counter()
    insert_articles(database, articles, NOON.isoformat())
    assert time.perf_counter() - started < 1.0


# --- size ----------------------------------------------------------------


def test_a_day_of_articles_fits_in_the_budget(tmp_path: Path) -> None:
    # Measured: 164 KB for 147 articles with their bodies. Budget 200 KB/day,
    # which is the number the "55 MB a year, not worth purging" decision rests
    # on. If this fails, that decision needs revisiting.
    path = tmp_path / "db.sqlite3"
    insert_articles(connect(path), recorded_day(), NOON.isoformat())
    assert path.stat().st_size <= 200 * 1024


def test_a_full_days_prompt_fits_in_the_budget(database: sqlite3.Connection) -> None:
    # Measured: 14515 characters, 4250 real tokens. Budget 6000 tokens.
    insert_articles(database, recorded_day(), NOON.isoformat())
    prompt = build_prompt(articles_for_day(database, "2026-08-30"))
    assert len(prompt) <= CHARACTER_BUDGET


def test_the_body_is_what_would_blow_the_budget(database: sqlite3.Connection) -> None:
    # The reason the prompt only carries headline and excerpt: the bodies are
    # several times the size, and they are stored precisely so they never have
    # to be sent.
    insert_articles(database, recorded_day(), NOON.isoformat())
    articles = articles_for_day(database, "2026-08-30")
    bodies = sum(len(article.body or "") for article in articles)
    sent = len(build_prompt(articles))
    assert bodies > sent


def test_the_stored_summary_stays_small(
    database: sqlite3.Connection,
    served_feeds: tuple[Source, ...],
    fake_model: FakeModel,
) -> None:
    # It is handed back to the model as context on every incremental call, so
    # its size is a running cost, not a storage one.
    run(database, served_feeds, fake_model, silent, NOON)
    payload = database.execute("SELECT payload FROM summaries").fetchone()[0]
    assert len(payload) < 8000
    assert json.loads(payload)
