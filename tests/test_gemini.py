"""The prompt, and the retry policy around the single call."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from resumen.gemini import MODEL, TOPICS, TransportError, as_payload, ask, build_prompt
from resumen.store import Article

RECORDED = Path(__file__).parent / "fixtures" / "gemini" / "summary-2026-08-30.json"


class Fake:
    """A model that answers from a script and counts what it was asked."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def recorded() -> str:
    return RECORDED.read_text(encoding="utf-8")


@pytest.fixture
def naps() -> list[float]:
    return []


def article(**overrides: Any) -> Article:
    fields: dict[str, Any] = {
        "source": "faro",
        "external_id": "1",
        "guid": "g",
        "title": "Un titular",
        "description": "Una entradilla.",
        "body": "El cuerpo entero del artículo, largo y caro en tokens.",
        "url": "https://elfarodeceuta.es/x/",
        "pubdate": "2026-08-30T10:00:00+00:00",
        "day": "2026-08-30",
    }
    return Article(**(fields | overrides))


# --- what the model is sent ---------------------------------------------


def test_the_body_is_never_sent() -> None:
    # Storing the body is cheap; sending it is ten times the tokens and more
    # noise. The prompt gets the headline and the excerpt, nothing else.
    sent = as_payload([article()])
    assert set(sent[0]) == {"id", "titulo", "entradilla"}
    assert "cuerpo entero" not in build_prompt([article()])


def test_a_missing_excerpt_is_sent_as_null() -> None:
    # El Pueblo's opinion pieces arrive with a headline and nothing else.
    assert as_payload([article(description=None)])[0]["entradilla"] is None


def test_the_prompt_carries_the_closed_taxonomy() -> None:
    prompt = build_prompt([article()])
    assert all(topic in prompt for topic in TOPICS)


def test_the_prompt_carries_every_id() -> None:
    prompt = build_prompt([article(external_id="1"), article(external_id="2")])
    assert "faro:1" in prompt
    assert "faro:2" in prompt


def test_without_a_previous_summary_the_prompt_says_so() -> None:
    assert "primer resumen del día" in build_prompt([article()])


def test_with_a_previous_summary_it_is_handed_back(recorded: str) -> None:
    prompt = build_prompt([article()], json.loads(recorded))
    assert "RESUMEN QUE YA EXISTE" in prompt
    assert "prisión provisional" in prompt


def test_the_model_is_pinned_not_an_alias() -> None:
    # gemini-flash-latest would change the answers without changing the hash
    # that is supposed to track them.
    assert "latest" not in MODEL
    assert MODEL == "gemini-3.6-flash"


# --- the retry policy ----------------------------------------------------


def test_a_good_answer_comes_back_parsed(recorded: str, naps: list[float]) -> None:
    payload = ask(Fake(recorded), [article()], sleep=naps.append)
    assert payload["temas"][0]["tema"] in TOPICS
    assert naps == []


def test_one_failure_is_absorbed(recorded: str, naps: list[float]) -> None:
    model = Fake(RuntimeError("503"), recorded)
    assert ask(model, [article()], sleep=naps.append)["descartados"] is not None
    assert len(model.prompts) == 2
    assert naps == [1.0]


def test_three_failures_give_up_with_a_clear_error(naps: list[float]) -> None:
    model = Fake(*(RuntimeError("503 UNAVAILABLE") for _ in range(3)))
    with pytest.raises(TransportError, match="3 intentos"):
        ask(model, [article()], sleep=naps.append)
    assert len(model.prompts) == 3
    # Backs off between attempts, and does not sleep after the last one.
    assert naps == [1.0, 2.0]


def test_a_non_json_answer_is_a_failure_like_any_other(naps: list[float]) -> None:
    # A model that starts explaining itself instead of answering is broken in
    # the same way a 503 is broken: nothing usable came back.
    model = Fake("Claro, aquí tienes el resumen:", "{ truncado", "todavía no")
    with pytest.raises(TransportError):
        ask(model, [article()], sleep=naps.append)


def test_the_error_names_what_went_wrong(naps: list[float]) -> None:
    with pytest.raises(TransportError, match="DEADLINE"):
        ask(
            Fake(*(RuntimeError("504 DEADLINE_EXCEEDED") for _ in range(3))),
            [article()],
            sleep=naps.append,
        )


def test_the_prompt_is_identical_on_every_attempt(
    recorded: str, naps: list[float]
) -> None:
    model = Fake(RuntimeError("503"), RuntimeError("503"), recorded)
    ask(model, [article()], sleep=naps.append)
    assert len(set(model.prompts)) == 1


def test_the_recorded_answer_accounts_for_every_id(recorded: str) -> None:
    # The shape the validation of T8 will enforce, checked here on the real
    # answer the model gave on 2026-08-30.
    payload = json.loads(recorded)
    returned = {i for t in payload["temas"] for e in t["entradas"] for i in e["ids"]}
    assert returned & set(payload["descartados"]) == set()
    assert len(returned) + len(payload["descartados"]) == 34


def test_the_sdk_is_not_imported_until_it_is_needed() -> None:
    # google-genai is heavy and a cache-warm run never calls the model, so the
    # import lives inside Gemini.__init__ instead of at module level.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import resumen.gemini, sys; print('google' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
