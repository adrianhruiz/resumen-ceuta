"""How a validated summary reaches the terminal."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from resumen.payload import Entry, Summary, Topic, validate
from resumen.render import render, sanitize, terminal_width

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "render" / "summary-2026-08-30.txt"


@pytest.fixture
def recorded() -> Summary:
    raw = json.loads(
        (FIXTURES / "gemini" / "summary-2026-08-30.json").read_text(encoding="utf-8")
    )
    ids = {i for t in raw["temas"] for e in t["entradas"] for i in e["ids"]} | set(
        raw["descartados"]
    )
    return validate(raw, ids)


def summary(*topics: Topic) -> Summary:
    return Summary(topics, ())


def entry(text: str) -> Entry:
    return Entry(text, ("faro:1",))


# --- the recorded day ----------------------------------------------------


def test_the_recorded_day_renders_exactly_as_recorded(recorded: Summary) -> None:
    assert render(recorded, width=72) + "\n" == GOLDEN.read_text(encoding="utf-8")


# --- order and omissions -------------------------------------------------


def test_topics_come_out_in_the_fixed_order() -> None:
    # The model returned them the other way round; the reader sees the same
    # shape every day regardless.
    text = render(
        summary(
            Topic("Cultura", (entry("un concierto"),)),
            Topic("Frontera", (entry("una valla"),)),
        ),
        width=72,
    )
    assert text.index("Frontera") < text.index("Cultura")


def test_an_empty_topic_is_not_printed() -> None:
    text = render(
        summary(Topic("Frontera", ()), Topic("Cultura", (entry("un concierto"),))),
        width=72,
    )
    assert "Frontera" not in text
    assert "Cultura" in text


def test_a_summary_with_nothing_renders_as_nothing() -> None:
    assert render(Summary((), ()), width=72) == ""


def test_every_entry_of_a_topic_is_its_own_bullet() -> None:
    text = render(summary(Topic("Frontera", (entry("uno"), entry("dos")))), width=72)
    assert text == "Frontera:\n  - uno\n  - dos"


def test_topics_are_separated_by_a_blank_line() -> None:
    text = render(
        summary(
            Topic("Frontera", (entry("una valla"),)),
            Topic("Cultura", (entry("un concierto"),)),
        ),
        width=72,
    )
    assert text == "Frontera:\n  - una valla\n\nCultura:\n  - un concierto"


# --- wrapping ------------------------------------------------------------


def test_long_bullets_wrap_under_their_own_text() -> None:
    text = render(summary(Topic("Frontera", (entry("palabra " * 30),))), width=40)
    lines = text.splitlines()
    assert all(len(line) <= 40 for line in lines)
    assert lines[1].startswith("  - ")
    # The continuation lines up with the first word, not with the dash.
    assert all(line.startswith("    palabra") for line in lines[2:])


def test_a_narrow_terminal_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "40")
    assert terminal_width() == 40


def test_an_absurd_terminal_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wrapping at 400 columns would be unreadable; wrapping at 5 impossible.
    monkeypatch.setenv("COLUMNS", "400")
    assert terminal_width() == 100
    monkeypatch.setenv("COLUMNS", "5")
    assert terminal_width() == 40


def test_a_long_url_is_not_broken_apart() -> None:
    text = render(
        summary(
            Topic(
                "Otros", (entry("mira https://elfarodeceuta.es/una-url-larguisima/"),)
            )
        ),
        width=40,
    )
    assert "https://elfarodeceuta.es/una-url-larguisima/" in text


# --- untrusted text ------------------------------------------------------


def test_escape_sequences_are_stripped() -> None:
    # A headline comes from a feed nobody here controls. Left alone, this one
    # would clear the reader's screen.
    assert sanitize("\x1b[2Jborrar la pantalla") == "[2Jborrar la pantalla"


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f", "\x9b"])
def test_every_control_character_is_removed(control: str) -> None:
    assert control not in sanitize(f"titular{control}peligroso")


def test_newlines_inside_an_entry_do_not_break_the_layout() -> None:
    assert sanitize("una\nlínea\ty otra") == "una línea y otra"


def test_accents_and_quotes_survive() -> None:
    assert sanitize("el “30J”, según Almería") == "el “30J”, según Almería"


def test_a_hostile_headline_cannot_paint_the_terminal() -> None:
    text = render(
        summary(Topic("Sucesos", (entry("\x1b[31mrojo\x1b[0m y \x07campana"),))),
        width=72,
    )
    assert "\x1b" not in text
    assert "\x07" not in text


# --- the terminal it is printed to ---------------------------------------


def test_the_output_carries_no_colour(recorded: Summary) -> None:
    # Nothing here emits colour, so TERM=dumb changes nothing. The test exists
    # so adding colour later has to be a deliberate decision, not a slip.
    assert "\x1b[" not in render(recorded, width=72)


def test_a_dumb_terminal_renders_the_same(tmp_path: Path) -> None:
    # TERM=dumb is the environment where anything clever about the terminal
    # falls apart. The output has to be byte-identical.
    script = tmp_path / "render_it.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "from resumen.payload import validate\n"
        "from resumen.render import render\n"
        "raw = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "kept = {i for t in raw['temas'] for e in t['entradas'] for i in e['ids']}\n"
        "print(render(validate(raw, kept | set(raw['descartados'])), width=72))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(FIXTURES / "gemini" / "summary-2026-08-30.json"),
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb", "COLUMNS": "1000"},
    )
    assert result.stdout == GOLDEN.read_text(encoding="utf-8")
