"""Unit and integration tests for reading the two feeds."""

from pathlib import Path

import pytest

from resumen.feeds import (
    SOURCES,
    Source,
    external_id,
    fetch,
    html_to_text,
    local_day,
    parse,
    to_utc,
)

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
FARO, PUEBLO = SOURCES


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- identifiers ---------------------------------------------------------


def test_the_faro_id_comes_from_the_query_string() -> None:
    assert external_id(FARO, "https://elfarodeceuta.es/?p=1437074") == "1437074"


def test_the_pueblo_id_comes_from_the_slug() -> None:
    guid = "https://www.elpueblodeceuta.es/sec/politica/pp-denuncia_1_1187097.html"
    assert external_id(PUEBLO, guid) == "1187097"


def test_a_corrected_headline_keeps_the_pueblo_id() -> None:
    # The slug carries the headline, so an edit rewrites the guid around a
    # number that stays put. That number is the whole point of the pattern.
    before = "https://www.elpueblodeceuta.es/sec/politica/pp-denunica_1_1187097.html"
    after = "https://www.elpueblodeceuta.es/sec/politica/pp-denuncia_1_1187097.html"
    assert external_id(PUEBLO, before) == external_id(PUEBLO, after)


@pytest.mark.parametrize(
    "guid", ["", "https://elfarodeceuta.es/sin-id/", "tag:algo,2026"]
)
def test_a_guid_without_an_id_yields_nothing(guid: str) -> None:
    assert external_id(FARO, guid) is None


# --- the day boundary ----------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "day"),
    [
        # Summer, UTC+2: the day turns at 22:00 UTC.
        ("2026-08-30T21:59:00+00:00", "2026-08-30"),
        ("2026-08-30T22:00:00+00:00", "2026-08-31"),
        # Winter, UTC+1: it turns at 23:00 UTC instead.
        ("2026-01-15T22:59:00+00:00", "2026-01-15"),
        ("2026-01-15T23:00:00+00:00", "2026-01-16"),
        # The night the clocks go forward, and the night they go back.
        ("2026-03-29T00:30:00+00:00", "2026-03-29"),
        ("2026-10-25T00:30:00+00:00", "2026-10-25"),
    ],
)
def test_the_day_is_cut_in_madrid_not_in_utc(instant: str, day: str) -> None:
    assert local_day(instant) == day


def test_rfc822_is_normalised_to_utc() -> None:
    assert to_utc("Sun, 30 Aug 2026 17:54:36 +0000") == "2026-08-30T17:54:36+00:00"


def test_a_non_utc_offset_is_converted() -> None:
    assert to_utc("Sun, 30 Aug 2026 19:54:36 +0200") == "2026-08-30T17:54:36+00:00"


# --- html to text --------------------------------------------------------


def test_paragraphs_survive_as_blank_lines() -> None:
    assert html_to_text("<p>Uno</p><p>Dos</p>") == "Uno\n\nDos"


def test_images_and_scripts_are_dropped() -> None:
    html = '<p>Texto<img src="foto.jpg"></p><script>alert(1)</script>'
    assert html_to_text(html) == "Texto"


def test_entities_are_decoded() -> None:
    assert html_to_text("<p>El PP &quot;denuncia&quot; &amp; act&uacute;a</p>") == (
        'El PP "denuncia" & actúa'
    )


def test_broken_markup_does_not_raise() -> None:
    assert html_to_text("<p>Sin cerrar<div>otro") == "Sin cerrar\n\notro"


@pytest.mark.parametrize("empty", [None, "", "<p></p>", "   "])
def test_nothing_useful_becomes_none(empty: str | None) -> None:
    assert html_to_text(empty) is None


# --- parsing the recorded feeds ------------------------------------------


def test_the_faro_fixture_yields_every_item() -> None:
    articles = parse(FARO, fixture("faro-2026-08-30.xml"))
    assert len(articles) == 10
    assert all(article.source == "faro" for article in articles)
    assert all(article.external_id.isdigit() for article in articles)
    assert all(
        article.url.startswith("https://elfarodeceuta.es/") for article in articles
    )


def test_faro_ships_the_full_body() -> None:
    articles = parse(FARO, fixture("faro-2026-08-30.xml"))
    assert all(article.body for article in articles)
    assert all("<p>" not in (article.body or "") for article in articles)


def test_the_pueblo_fixture_yields_every_item() -> None:
    articles = parse(PUEBLO, fixture("pueblo-2026-08-30.xml"))
    assert len(articles) == 137
    assert all(article.source == "pueblo" for article in articles)


def test_pueblo_ships_no_body_at_all() -> None:
    # Recorded 2026-08-30: El Pueblo's feed has no content:encoded, only the
    # excerpt. The plan claimed otherwise. The prompt only sends title and
    # description, so the design survives, but body stays empty for this source.
    articles = parse(PUEBLO, fixture("pueblo-2026-08-30.xml"))
    assert all(article.body is None for article in articles)


def test_some_pueblo_items_carry_no_excerpt() -> None:
    # The opinion pieces ship a headline and nothing else. Parsing must keep
    # them, and whatever builds the prompt has to tolerate a missing excerpt.
    articles = parse(PUEBLO, fixture("pueblo-2026-08-30.xml"))
    without = [article for article in articles if article.description is None]
    assert 0 < len(without) < len(articles)


def test_both_pueblo_content_types_are_ingested() -> None:
    # The guid encodes a content type: _1_ is an article, _3_ a photo gallery.
    # Dropping galleries here would be metadata deciding what counts as news,
    # which is the job this project handed to the model.
    guids = [
        article.guid for article in parse(PUEBLO, fixture("pueblo-2026-08-30.xml"))
    ]
    assert sum("_1_" in guid for guid in guids) == 124
    assert sum("_3_" in guid for guid in guids) == 13


def test_the_pueblo_id_ignores_the_content_type() -> None:
    gallery = "https://www.elpueblodeceuta.es/sec/sociedad/boda-oro_3_1187091.html"
    assert external_id(PUEBLO, gallery) == "1187091"


def test_ids_are_built_for_the_model() -> None:
    articles = parse(FARO, fixture("faro-2026-08-30.xml"))
    assert articles[0].id == f"faro:{articles[0].external_id}"


def test_dates_are_stored_in_utc_and_cut_in_madrid() -> None:
    articles = parse(PUEBLO, fixture("pueblo-2026-08-30.xml"))
    assert all(article.pubdate.endswith("+00:00") for article in articles)
    assert all(len(article.day) == len("2026-08-30") for article in articles)


def test_an_item_without_a_usable_id_is_dropped_not_guessed() -> None:
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Sin id</title><link>https://elfarodeceuta.es/algo/</link>
    <guid isPermaLink="false">https://elfarodeceuta.es/algo/</guid>
    <pubDate>Sun, 30 Aug 2026 17:54:36 +0000</pubDate></item>
    </channel></rss>"""
    assert parse(FARO, feed) == []


def test_an_empty_feed_yields_nothing() -> None:
    assert (
        parse(FARO, b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>') == []
    )


# --- fetching over HTTP --------------------------------------------------


def test_a_non_http_scheme_is_refused() -> None:
    # Plain http is allowed so a local server can stand in for a feed, but
    # file: and friends are what the urllib audit rule is actually about.
    source = Source("local", "file:///etc/passwd", FARO.id_pattern)
    with pytest.raises(ValueError, match="http"):
        fetch(source)
