"""Turning what the model answered into something safe to store.

The model is asked for a shape and usually returns it. This module decides
whether what came back can be believed, because a summary that is written to
the cache is a summary the app will keep showing without asking again.
"""

import json
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from .gemini import TOPICS


class InvalidPayload(ValueError):
    """The answer cannot be trusted, so nothing gets written."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One fact, and the articles that told it."""

    text: str
    ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Topic:
    name: str
    entries: tuple[Entry, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Summary:
    """A validated summary of one day."""

    topics: tuple[Topic, ...]
    discarded: tuple[str, ...]

    @property
    def covered_ids(self) -> tuple[str, ...]:
        """Every article this summary has already judged, kept or dropped."""
        seen = [
            identifier
            for topic in self.topics
            for entry in topic.entries
            for identifier in entry.ids
        ]
        return tuple(sorted({*seen, *self.discarded}))

    def as_json(self) -> str:
        """The form stored in `summaries.payload`."""
        return json.dumps(
            {
                "temas": [
                    {
                        "tema": topic.name,
                        "entradas": [
                            {"texto": e.text, "ids": list(e.ids)} for e in topic.entries
                        ],
                    }
                    for topic in self.topics
                ],
                "descartados": list(self.discarded),
            },
            ensure_ascii=False,
        )


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidPayload(f"{where} tiene que ser una lista de cadenas")
    return tuple(value)


def _entry(raw: Any, topic: str) -> Entry:
    if not isinstance(raw, dict):
        raise InvalidPayload(f"una entrada de {topic} no es un objeto")
    text = raw.get("texto")
    if not isinstance(text, str) or not text.strip():
        raise InvalidPayload(f"una entrada de {topic} no tiene texto")
    ids = _strings(raw.get("ids"), f"los ids de una entrada de {topic}")
    if not ids:
        raise InvalidPayload(f"una entrada de {topic} no cita ningún artículo")
    return Entry(text.strip(), ids)


def _topic(raw: Any) -> Topic:
    if not isinstance(raw, dict):
        raise InvalidPayload("un tema no es un objeto")
    name = raw.get("tema")
    if name not in TOPICS:
        raise InvalidPayload(f"tema fuera de la taxonomía: {name!r}")
    entries = raw.get("entradas")
    if not isinstance(entries, list):
        raise InvalidPayload(f"las entradas de {name} no son una lista")
    return Topic(name, tuple(_entry(entry, name) for entry in entries))


def validate(payload: Any, expected_ids: Collection[str]) -> Summary:
    """Check the answer against the articles it was asked about.

    `expected_ids` is everything the model was accountable for: the articles
    sent this time, plus the ones an earlier run already covered and handed
    back as context.
    """
    if not isinstance(payload, dict):
        raise InvalidPayload("la respuesta no es un objeto JSON")

    raw_topics = payload.get("temas")
    if not isinstance(raw_topics, list):
        raise InvalidPayload("faltan los temas")
    topics = tuple(_topic(topic) for topic in raw_topics)

    names = [topic.name for topic in topics]
    if len(names) != len(set(names)):
        raise InvalidPayload("hay un tema repetido")

    discarded = _strings(payload.get("descartados"), "los descartados")
    summary = Summary(topics, discarded)

    kept = [i for topic in topics for entry in topic.entries for i in entry.ids]
    everything = [*kept, *discarded]
    if len(everything) != len(set(everything)):
        raise InvalidPayload("hay un artículo contado dos veces")

    expected = set(expected_ids)
    seen = set(everything)
    # This is the check that catches a truncated answer: the model can only
    # return every id if it got to the end of its own reply.
    if missing := expected - seen:
        raise InvalidPayload(
            f"faltan {len(missing)} artículos por juzgar: {sorted(missing)[:3]}"
        )
    if invented := seen - expected:
        raise InvalidPayload(f"ids que no se enviaron: {sorted(invented)[:3]}")
    return summary
