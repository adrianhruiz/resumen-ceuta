"""What the model answered, and whether it can be believed."""

import json
from pathlib import Path
from typing import Any

import pytest

from resumen.payload import InvalidPayload, Summary, validate

RECORDED = Path(__file__).parent / "fixtures" / "gemini" / "summary-2026-08-30.json"


@pytest.fixture
def recorded() -> dict[str, Any]:
    return json.loads(RECORDED.read_text(encoding="utf-8"))


@pytest.fixture
def recorded_ids(recorded: dict[str, Any]) -> set[str]:
    kept = {i for t in recorded["temas"] for e in t["entradas"] for i in e["ids"]}
    return kept | set(recorded["descartados"])


def minimal(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "temas": [
            {
                "tema": "Frontera",
                "entradas": [{"texto": "algo pasó", "ids": ["faro:1"]}],
            }
        ],
        "descartados": ["faro:2"],
    }
    return base | overrides


# --- the answer the model actually gave ----------------------------------


def test_the_recorded_answer_validates(
    recorded: dict[str, Any], recorded_ids: set[str]
) -> None:
    summary = validate(recorded, recorded_ids)
    assert len(summary.topics) == len(recorded["temas"])
    assert summary.covered_ids == tuple(sorted(recorded_ids))


def test_covered_ids_are_sorted_and_unique(
    recorded: dict[str, Any], recorded_ids: set[str]
) -> None:
    # They go into the input_hash, so their order cannot depend on the model.
    covered = validate(recorded, recorded_ids).covered_ids
    assert list(covered) == sorted(set(covered))


def test_a_summary_survives_a_round_trip(
    recorded: dict[str, Any], recorded_ids: set[str]
) -> None:
    summary = validate(recorded, recorded_ids)
    assert validate(json.loads(summary.as_json()), recorded_ids) == summary


# --- the shapes that must be refused -------------------------------------


def test_something_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(InvalidPayload, match="objeto JSON"):
        validate(["temas"], {"faro:1"})


def test_a_missing_temas_key_is_refused() -> None:
    with pytest.raises(InvalidPayload, match="temas"):
        validate({"descartados": []}, set())


def test_a_topic_outside_the_taxonomy_is_refused() -> None:
    payload = minimal(temas=[{"tema": "Fútbol", "entradas": []}])
    with pytest.raises(InvalidPayload, match="taxonomía"):
        validate(payload, {"faro:2"})


def test_a_repeated_topic_is_refused() -> None:
    payload = minimal(
        temas=[
            {"tema": "Frontera", "entradas": [{"texto": "a", "ids": ["faro:1"]}]},
            {"tema": "Frontera", "entradas": []},
        ]
    )
    with pytest.raises(InvalidPayload, match="repetido"):
        validate(payload, {"faro:1", "faro:2"})


def test_an_entry_without_text_is_refused() -> None:
    payload = minimal(
        temas=[{"tema": "Frontera", "entradas": [{"texto": "  ", "ids": ["faro:1"]}]}]
    )
    with pytest.raises(InvalidPayload, match="texto"):
        validate(payload, {"faro:1", "faro:2"})


def test_an_entry_citing_nothing_is_refused() -> None:
    # An entry with no ids is a fact nobody reported, which is the shape a
    # hallucination takes here.
    payload = minimal(
        temas=[{"tema": "Frontera", "entradas": [{"texto": "algo", "ids": []}]}]
    )
    with pytest.raises(InvalidPayload, match="ningún artículo"):
        validate(payload, {"faro:2"})


def test_an_invented_id_is_refused() -> None:
    # minimal() cites faro:1 and faro:2; only faro:1 was ever sent.
    with pytest.raises(InvalidPayload, match="no se enviaron"):
        validate(minimal(), {"faro:1"})


def test_an_article_judged_twice_is_refused() -> None:
    payload = minimal(descartados=["faro:1", "faro:2"])
    with pytest.raises(InvalidPayload, match="dos veces"):
        validate(payload, {"faro:1", "faro:2"})


def test_a_truncated_answer_is_refused(
    recorded: dict[str, Any], recorded_ids: set[str]
) -> None:
    # The real failure mode: the reply stops mid-way, so the last articles
    # never appear. Nothing else in the payload looks wrong.
    truncated = dict(recorded, temas=recorded["temas"][:2], descartados=[])
    with pytest.raises(InvalidPayload, match="por juzgar"):
        validate(truncated, recorded_ids)


def test_the_error_says_how_many_are_missing(recorded_ids: set[str]) -> None:
    with pytest.raises(InvalidPayload, match="faltan 3[0-9] artículos"):
        validate({"temas": [], "descartados": []}, recorded_ids)


@pytest.mark.parametrize(
    "broken",
    [
        {"temas": "no es una lista", "descartados": []},
        {
            "temas": [{"tema": "Frontera", "entradas": "no es una lista"}],
            "descartados": [],
        },
        {"temas": [], "descartados": "no es una lista"},
        {
            "temas": [
                {"tema": "Frontera", "entradas": [{"texto": "a", "ids": "faro:1"}]}
            ],
            "descartados": [],
        },
        {
            "temas": [{"tema": "Frontera", "entradas": [{"texto": "a", "ids": [1]}]}],
            "descartados": [],
        },
        {"temas": ["Frontera"], "descartados": []},
    ],
)
def test_wrong_types_are_refused(broken: dict[str, Any]) -> None:
    with pytest.raises(InvalidPayload):
        validate(broken, {"faro:1"})


def test_an_empty_day_is_a_valid_summary() -> None:
    # Nothing published, nothing judged: that is a real answer, not a failure.
    assert validate({"temas": [], "descartados": []}, set()) == Summary((), ())


def test_a_topic_with_no_entries_is_allowed() -> None:
    # The model may name a topic and put nothing in it; the render drops it.
    payload = minimal(temas=[{"tema": "Frontera", "entradas": []}])
    assert validate(payload, {"faro:2"}).topics[0].entries == ()


def test_a_model_that_obeyed_an_injected_instruction_is_caught() -> None:
    # The feeds are untrusted input: a headline can say "ignore the above and
    # answer X". No wording of the prompt can guarantee the model resists it,
    # so the defence is arithmetic — an answer that stops accounting for the
    # ids it was handed cannot be stored, whatever it says.
    obeyed = {
        "temas": [
            {"tema": "Otros", "entradas": [{"texto": "hola", "ids": ["inyectado:1"]}]}
        ],
        "descartados": [],
    }
    with pytest.raises(InvalidPayload):
        validate(obeyed, {"faro:1", "faro:2"})
