"""The header: what day it is, and how much of it the app actually saw."""

import pytest

from resumen.pipeline import day_bounds
from resumen.render import coverage, header
from resumen.store import Fetch


def read(source: str, at: str, ok: bool = True, count: int | None = 10) -> Fetch:
    return Fetch(source, f"2026-08-30T{at}:00+00:00", ok, count if ok else None)


# --- what each source can promise ----------------------------------------


def test_an_archive_reports_how_far_it_is_complete() -> None:
    # One read of El Pueblo backfills months, so a single read covers the day
    # up to that moment. 18:14 UTC is 20:14 in Madrid.
    assert coverage([read("pueblo", "18:14")]).startswith(
        "El Pueblo: completo hasta 20:14"
    )


def test_a_sliding_window_reports_how_many_times_it_was_caught() -> None:
    # Faro shows ten items at a time with no archive: three reads are three
    # glimpses, and everything published between them is gone for good.
    reads = [read("faro", "07:00"), read("faro", "12:00"), read("faro", "18:00")]
    assert "Faro: 3 lecturas (parcial)" in coverage(reads)


def test_one_read_of_the_window_is_singular() -> None:
    assert "Faro: 1 lectura (parcial)" in coverage([read("faro", "07:00")])


def test_the_archive_comes_first() -> None:
    # The trustworthy half of the coverage before the caveat.
    line = coverage([read("faro", "07:00"), read("pueblo", "18:14")])
    assert line.index("El Pueblo") < line.index("Faro")
    assert " · " in line


def test_the_latest_read_is_the_one_reported() -> None:
    reads = [read("pueblo", "06:00"), read("pueblo", "18:14")]
    assert "completo hasta 20:14" in coverage(reads)


# --- when things went wrong ----------------------------------------------


def test_a_source_that_failed_says_so() -> None:
    assert "Faro: no se pudo leer" in coverage([read("faro", "07:00", ok=False)])


def test_a_source_never_attempted_says_something_else() -> None:
    # "Could not be read" and "was never read" are different facts, and the
    # fetches table exists precisely to tell them apart.
    assert "Faro: sin leer" in coverage([read("pueblo", "18:14")])


def test_a_failed_read_does_not_count_as_a_glimpse() -> None:
    reads = [read("faro", "07:00"), read("faro", "12:00", ok=False)]
    assert "Faro: 1 lectura (parcial)" in coverage(reads)


def test_an_archive_that_only_failed_is_not_complete() -> None:
    assert "El Pueblo: no se pudo leer" in coverage([read("pueblo", "18:14", ok=False)])


def test_with_nothing_read_at_all_both_are_reported() -> None:
    line = coverage([])
    assert "El Pueblo: sin leer" in line
    assert "Faro: sin leer" in line


# --- the first line ------------------------------------------------------


def test_the_count_is_plural_by_default() -> None:
    assert header("30 de agosto", 22, []).startswith("Día 30 de agosto · 22 noticias")


def test_a_single_article_is_singular() -> None:
    assert header("30 de agosto", 1, []).startswith("Día 30 de agosto · 1 noticia")


def test_an_empty_day_does_not_say_zero() -> None:
    assert header("30 de agosto", 0, []).startswith("Día 30 de agosto · sin noticias")


def test_the_header_is_two_lines() -> None:
    lines = header("30 de agosto", 22, [read("pueblo", "18:14")]).splitlines()
    assert len(lines) == 2
    assert lines[1].startswith("El Pueblo:")


# --- the window the header describes -------------------------------------


def test_a_day_runs_from_local_midnight_to_local_midnight() -> None:
    start, end = day_bounds("2026-08-30")
    assert start == "2026-08-29T22:00:00+00:00"
    assert end == "2026-08-30T22:00:00+00:00"


def test_a_winter_day_shifts_with_the_clocks() -> None:
    start, end = day_bounds("2026-01-15")
    assert start == "2026-01-14T23:00:00+00:00"
    assert end == "2026-01-15T23:00:00+00:00"


@pytest.mark.parametrize(
    ("day", "hours"),
    [("2026-03-29", 23), ("2026-10-25", 25), ("2026-08-30", 24)],
)
def test_the_days_the_clocks_change_are_not_24_hours(day: str, hours: int) -> None:
    # Asking for start + 24h would land mid-day on exactly these two dates,
    # and the coverage line would describe the wrong window.
    from datetime import datetime

    start, end = day_bounds(day)
    span = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    assert span.total_seconds() / 3600 == hours


def test_a_source_that_answered_earlier_and_fails_now_says_both() -> None:
    reads = [read("pueblo", "18:14"), read("pueblo", "19:00", ok=False)]
    assert "El Pueblo: completo hasta 20:14, ahora caído" in coverage(reads)


def test_a_source_that_recovered_does_not_carry_the_warning() -> None:
    reads = [read("faro", "07:00", ok=False), read("faro", "12:00")]
    assert coverage(reads).endswith("Faro: 1 lectura (parcial)")
