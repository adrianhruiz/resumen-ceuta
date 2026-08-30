"""Functional tests for the CLI, driven the way a user drives it."""

import subprocess
import sys
from pathlib import Path

from resumen import __version__


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI in a child process, as the installed command would run.

    The child inherits the environment the `home` fixture patched, so it
    resolves its paths inside the temporary directory.
    """
    return subprocess.run(
        [sys.executable, "-m", "resumen.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_exits_zero(env_file: Path, empty_env: None) -> None:
    assert run().returncode == 0


def test_stdout_carries_the_day_and_nothing_else(
    env_file: Path, empty_env: None
) -> None:
    # Everything on stdout must be the day itself; the reading of the feeds is
    # reported on stderr, or it would end up in the user's pipe.
    stdout = run().stdout
    assert stdout.startswith("Día ")
    assert "items" not in stdout


def test_a_run_that_reads_nothing_still_says_what_day_it_is(
    env_file: Path, empty_env: None
) -> None:
    result = run()
    assert result.returncode == 0
    assert "sin noticias" in result.stdout
    assert "sin leer" not in result.stdout


def test_version_goes_to_stdout() -> None:
    # Deliberately without a key file: asking for the version must never
    # depend on the configuration being complete.
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"resumen {__version__}"


def test_force_is_accepted(env_file: Path, empty_env: None) -> None:
    assert run("--force").returncode == 0


def test_unknown_flag_is_rejected() -> None:
    result = run("--nope")
    assert result.returncode != 0
    assert result.stdout == ""


def test_a_missing_key_stops_the_run_with_instructions(home: Path) -> None:
    result = run()
    assert result.returncode == 1
    assert result.stdout == ""
    assert str(home / "config" / "resumen-ceuta" / "env") in result.stderr
    assert "GEMINI_API_KEY=tu-clave" in result.stderr


def test_the_key_never_reaches_the_output(
    env_file: Path, valid_key: str, empty_env: None
) -> None:
    result = run()
    assert valid_key not in result.stdout
    assert valid_key not in result.stderr


def test_the_database_is_created_on_the_first_run(
    env_file: Path, home: Path, empty_env: None
) -> None:
    database = home / "data" / "resumen-ceuta" / "db.sqlite3"
    assert not database.exists()
    assert run().returncode == 0
    assert database.is_file()


def test_a_second_run_keeps_the_database(
    env_file: Path, home: Path, empty_env: None
) -> None:
    run()
    database = home / "data" / "resumen-ceuta" / "db.sqlite3"
    stamp = database.stat().st_ino
    assert run().returncode == 0
    assert database.stat().st_ino == stamp
