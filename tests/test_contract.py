"""Contract tests: what the two feeds actually serve, right now.

These exist so drift is noisy. Everything the design rests on was measured
once, on 2026-08-30, and nobody at either outlet promised to keep it that way.
They hit real servers, so they are marked `network` and stay out of the gate
that protects `develop`.
"""

import os
import urllib.error
import urllib.request

import feedparser
import pytest

from resumen.config import ConfigError, load_api_key
from resumen.feeds import SOURCES, fetch, parse
from resumen.gemini import MODEL, TOPICS, Gemini, ask
from resumen.store import Article

FARO, PUEBLO = SOURCES

pytestmark = pytest.mark.network


def test_the_faro_feed_is_a_sliding_window_of_ten() -> None:
    # The whole risk profile of this project comes from this number. If it
    # grows, the "one run captures a third of the day" problem is over and the
    # design should be revisited; that is worth a failing test either way.
    assert len(parse(FARO, fetch(FARO))) == 10


def test_faro_still_ships_the_full_body() -> None:
    articles = parse(FARO, fetch(FARO))
    assert all(article.body for article in articles)


def test_faro_ids_still_live_in_the_query_string() -> None:
    assert all(article.external_id.isdigit() for article in parse(FARO, fetch(FARO)))


def test_the_pueblo_feed_is_its_own_archive() -> None:
    # Two orders of magnitude more history than Faro. A single read backfills.
    assert len(parse(PUEBLO, fetch(PUEBLO))) > 100


def test_pueblo_still_ships_no_body() -> None:
    articles = parse(PUEBLO, fetch(PUEBLO))
    assert all(article.body is None for article in articles)


def test_pueblo_ids_still_live_in_the_slug() -> None:
    assert all(
        article.external_id.isdigit() for article in parse(PUEBLO, fetch(PUEBLO))
    )


def test_both_feeds_still_date_everything_in_utc() -> None:
    for source in SOURCES:
        assert all(
            article.pubdate.endswith("+00:00")
            for article in parse(source, fetch(source))
        )


def test_the_pueblo_wordpress_path_is_still_a_404() -> None:
    # /feed/ is the obvious guess and the wrong one. If it ever starts working,
    # somebody changed their CMS and everything above deserves a second look.
    with pytest.raises(urllib.error.HTTPError) as raised:
        urllib.request.urlopen(  # noqa: S310
            "https://www.elpueblodeceuta.es/feed/", timeout=15
        )
    assert raised.value.code == 404


def test_the_feeds_parse_without_errors() -> None:
    for source in SOURCES:
        assert not feedparser.parse(fetch(source)).bozo


def api_key() -> str:
    """The key from the environment in CI, or from the user's file locally."""
    from_environment = os.environ.get("GEMINI_API_KEY")
    if from_environment:
        return from_environment
    try:
        return load_api_key()
    except ConfigError:
        pytest.skip("sin API key: exporta GEMINI_API_KEY o crea el fichero de config")


def test_the_pinned_model_still_answers_a_usable_summary() -> None:
    # Two articles about the same fact, one per outlet. If the pinned model
    # disappears, stops returning JSON, or stops honouring the taxonomy, this
    # is where it shows up, not in production.
    articles = [
        Article(
            "faro",
            "1",
            "g1",
            "El PP denuncia que el Gobierno sigue fallando a Ceuta",
            "El partido critica la inacción del Ejecutivo central.",
            None,
            "https://elfarodeceuta.es/x/",
            "2026-08-30T10:58:34+00:00",
            "2026-08-30",
        ),
        Article(
            "pueblo",
            "2",
            "g2",
            "El PP carga contra el Gobierno un mes después del 30J",
            "Los populares reprochan al Ejecutivo su gestión.",
            None,
            "https://www.elpueblodeceuta.es/y/",
            "2026-08-30T11:02:00+00:00",
            "2026-08-30",
        ),
    ]
    payload = ask(Gemini(api_key(), MODEL), articles)

    assert all(theme["tema"] in TOPICS for theme in payload["temas"])
    returned = {i for t in payload["temas"] for e in t["entradas"] for i in e["ids"]}
    assert returned | set(payload["descartados"]) == {"faro:1", "pueblo:2"}
