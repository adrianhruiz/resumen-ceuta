"""Contract tests: what the two feeds actually serve, right now.

These exist so drift is noisy. Everything the design rests on was measured
once, on 2026-08-30, and nobody at either outlet promised to keep it that way.
They hit real servers, so they are marked `network` and stay out of the gate
that protects `develop`.
"""

import urllib.error
import urllib.request

import feedparser
import pytest

from resumen.feeds import SOURCES, fetch, parse

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
