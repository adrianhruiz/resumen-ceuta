"""Reading the two feeds and turning their items into articles.

The two outlets agree on almost nothing: one hides a numeric id in a query
string, the other in a URL slug; one ships the full body, the other only an
excerpt. Everything that differs lives in `Source`, and the parsing below is
written once.
"""

import os
import re
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import feedparser

from .store import Article

# The day a reader means by "hoy" is the local one, not the UTC one.
MADRID = ZoneInfo("Europe/Madrid")

USER_AGENT = "resumen-ceuta (+https://github.com/adrianhruiz/resumen-ceuta)"
TIMEOUT_SECONDS = 15.0

# Tags whose text is markup, not prose.
SKIPPED_TAGS = frozenset({"script", "style"})
# Tags that end a paragraph of prose.
BREAKING_TAGS = frozenset(
    {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "blockquote"}
)


@dataclass(frozen=True, slots=True)
class Source:
    """One outlet, and the two things it does its own way."""

    name: str
    url: str
    # Pulls the stable numeric id out of the guid. El Pueblo's guid carries the
    # headline as a slug, so the id is the only part of it that survives an edit.
    id_pattern: re.Pattern[str]
    display: str = ""
    # True when a single read backfills months, false when the feed is a
    # sliding window and one read only ever catches what is visible right now.
    # It is the difference between "complete up to 20:14" and "3 reads so far".
    archive: bool = False

    def __post_init__(self) -> None:
        if not self.display:
            object.__setattr__(self, "display", self.name.capitalize())


SOURCES: tuple[Source, ...] = (
    Source(
        "faro",
        "https://elfarodeceuta.es/feed/",
        re.compile(r"[?&]p=(\d+)"),
        display="Faro",
        archive=False,
    ),
    # The digit before the id is a content type: 1 is an article, 3 a photo
    # gallery. Both are ingested. Filtering by it here would be exactly the
    # metadata-based sorting this project decided the model has to do instead,
    # and the numeric id is unique across types, so nothing collides.
    Source(
        "pueblo",
        "https://www.elpueblodeceuta.es/rss/",
        re.compile(r"_\d+_(\d+)\.html"),
        display="El Pueblo",
        archive=True,
    ),
)


def sources() -> tuple[Source, ...]:
    """The two feeds, with their URLs overridable through the environment.

    RESUMEN_FARO_URL and RESUMEN_PUEBLO_URL point the app somewhere else: a
    local server in the tests, a mirror if an outlet ever moves its feed.
    """
    return tuple(
        replace(
            source, url=os.environ.get(f"RESUMEN_{source.name.upper()}_URL", source.url)
        )
        for source in SOURCES
    )


class _Text(HTMLParser):
    """Turn a fragment of article HTML into plain text, paragraphs intact."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in SKIPPED_TAGS:
            self.skipping += 1
        elif tag in BREAKING_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and self.skipping:
            self.skipping -= 1
        elif tag in BREAKING_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_to_text(html: str | None) -> str | None:
    """Plain text with blank lines between paragraphs, or None when empty."""
    if not html:
        return None
    parser = _Text()
    parser.feed(html)
    parser.close()
    paragraphs = [
        "\n".join(line.strip() for line in block.split("\n") if line.strip())
        for block in "".join(parser.parts).split("\n\n")
    ]
    text = "\n\n".join(block for block in paragraphs if block)
    return text or None


def to_utc(published: str) -> str:
    """RFC 822 as the feeds send it, normalised to ISO 8601 in UTC."""
    return parsedate_to_datetime(published).astimezone(UTC).isoformat()


def local_day(pubdate_utc: str) -> str:
    """The Europe/Madrid calendar day an instant belongs to."""
    return datetime.fromisoformat(pubdate_utc).astimezone(MADRID).date().isoformat()


def external_id(source: Source, guid: str) -> str | None:
    match = source.id_pattern.search(guid or "")
    return match.group(1) if match else None


def fetch(source: Source) -> bytes:
    """Read the feed as bytes, so the parser sees exactly what was served."""
    # S310 warns that urllib will happily open file: or custom schemes. The
    # guard below is the answer to that, so the rule is silenced here and only
    # here, on a URL that has just been checked. Plain http is allowed because
    # a local test server speaks it; that the real feeds are https is a
    # separate invariant, asserted against SOURCES in the tests.
    if not source.url.startswith(("https://", "http://")):
        raise ValueError(f"feed URL must be http(s): {source.url}")
    request = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.read()


def parse(source: Source, raw: bytes) -> list[Article]:
    """Every item that carries a usable id. The rest are dropped, not guessed."""
    feed = feedparser.parse(raw)
    articles = []
    for entry in feed.entries:
        identifier = external_id(source, entry.get("id") or entry.get("link") or "")
        published = entry.get("published")
        if identifier is None or not published:
            continue
        pubdate = to_utc(published)
        contents = entry.get("content") or []
        articles.append(
            Article(
                source=source.name,
                external_id=identifier,
                guid=entry.get("id") or entry.get("link") or "",
                title=entry.get("title", "").strip(),
                description=html_to_text(entry.get("summary")),
                body=html_to_text(contents[0].get("value") if contents else None),
                url=entry.get("link", ""),
                pubdate=pubdate,
                day=local_day(pubdate),
            )
        )
    return articles
