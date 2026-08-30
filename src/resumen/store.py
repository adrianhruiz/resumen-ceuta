"""SQLite storage: the schema and the few queries the app needs.

Timestamps are stored in UTC. `day` is the Europe/Madrid calendar day an
article belongs to, computed when it is ingested, because that is the day the
reader means when they say "hoy".
"""

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .config import database_path

# The database is opened on every run, so the schema has to be idempotent.
SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    source      TEXT NOT NULL,      -- 'faro' | 'pueblo'
    external_id TEXT NOT NULL,      -- stable id parsed out of the guid
    guid        TEXT NOT NULL,      -- raw guid, kept for reference only
    title       TEXT NOT NULL,
    description TEXT,
    body        TEXT,               -- plain text, paragraphs kept, no images
    url         TEXT NOT NULL,
    pubdate     TEXT NOT NULL,      -- ISO 8601 UTC
    day         TEXT NOT NULL,      -- YYYY-MM-DD, Europe/Madrid
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_articles_day ON articles(day);

-- One row per feed read. Without it there is no way to tell
-- "the outlet published nothing" from "the app was never opened".
CREATE TABLE IF NOT EXISTS fetches (
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,       -- ISO 8601 UTC
    ok         INTEGER NOT NULL,
    item_count INTEGER
);

CREATE TABLE IF NOT EXISTS summaries (
    day          TEXT PRIMARY KEY,  -- YYYY-MM-DD, Europe/Madrid
    covered_ids  TEXT NOT NULL,     -- JSON array, sorted: ["faro:1436869", ...]
    input_hash   TEXT NOT NULL,     -- sha256(covered_ids + prompt + model id)
    payload      TEXT NOT NULL,     -- JSON
    generated_at TEXT NOT NULL
);
"""

# Kept in the order the queries below spell out, so Article(*row) is safe.
ARTICLE_FIELDS: Sequence[str] = (
    "source",
    "external_id",
    "guid",
    "title",
    "description",
    "body",
    "url",
    "pubdate",
    "day",
)

# Written out rather than composed: a query built by string formatting is the
# shape this project's lint rules exist to catch, and the indirection bought
# nothing.
INSERT_ARTICLE = """
INSERT OR IGNORE INTO articles
    (source, external_id, guid, title, description, body, url, pubdate, day, fetched_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_DAY = """
SELECT source, external_id, guid, title, description, body, url, pubdate, day
FROM articles
WHERE day = ?
ORDER BY pubdate, source, external_id
"""

INSERT_FETCH = """
INSERT INTO fetches (source, fetched_at, ok, item_count) VALUES (?, ?, ?, ?)
"""


@dataclass(frozen=True, slots=True)
class Article:
    """One article as it is stored. `fetched_at` belongs to the read, not here."""

    source: str
    external_id: str
    guid: str
    title: str
    description: str | None
    body: str | None
    url: str
    pubdate: str
    day: str

    @property
    def id(self) -> str:
        """The identifier the model sees and returns, e.g. 'faro:1436869'."""
        return f"{self.source}:{self.external_id}"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating its directory and schema when missing."""
    path = path if path is not None else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A second run started while this one writes should wait, not fail.
    connection = sqlite3.connect(path, timeout=5.0)
    connection.executescript(SCHEMA)
    return connection


def insert_articles(
    connection: sqlite3.Connection, articles: Iterable[Article], fetched_at: str
) -> int:
    """Store what is new and return how many rows that was.

    Deduplication is by (source, external_id), never by guid: El Pueblo builds
    its guid out of the headline, so correcting a headline changes it.
    An article already stored keeps the text it was first stored with.
    """
    rows = [
        (*(getattr(article, field) for field in ARTICLE_FIELDS), fetched_at)
        for article in articles
    ]
    before = connection.total_changes
    with connection:
        connection.executemany(INSERT_ARTICLE, rows)
    return connection.total_changes - before


def articles_for_day(connection: sqlite3.Connection, day: str) -> list[Article]:
    """Every article of that Europe/Madrid day, oldest first."""
    rows = connection.execute(SELECT_DAY, (day,))
    return [Article(*row) for row in rows]


def record_fetch(
    connection: sqlite3.Connection,
    source: str,
    fetched_at: str,
    ok: bool,
    item_count: int | None = None,
) -> None:
    """Leave a trace of the read itself, successful or not."""
    with connection:
        connection.execute(INSERT_FETCH, (source, fetched_at, int(ok), item_count))
