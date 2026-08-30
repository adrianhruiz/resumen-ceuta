"""Functional tests for the CLI, driven the way a user drives it."""

import subprocess
import sys

from resumen import __version__


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI in a child process, as the installed command would run."""
    return subprocess.run(
        [sys.executable, "-m", "resumen.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_exits_zero() -> None:
    assert run().returncode == 0


def test_stdout_carries_nothing_but_the_summary() -> None:
    # No sources are read yet, so a clean run must leave stdout empty:
    # anything else here would end up in the user's pipe.
    assert run().stdout == ""


def test_progress_goes_to_stderr() -> None:
    assert run().stderr.strip() != ""


def test_version_goes_to_stdout() -> None:
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"resumen {__version__}"


def test_force_is_accepted() -> None:
    assert run("--force").returncode == 0


def test_unknown_flag_is_rejected() -> None:
    result = run("--nope")
    assert result.returncode != 0
    assert result.stdout == ""
