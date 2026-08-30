"""Command line entry point.

stdout carries the summary and nothing else, so it stays usable through a pipe.
Everything the user reads while waiting goes to stderr.
"""

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, load_api_key
from .feeds import sources
from .gemini import Gemini, TransportError
from .payload import InvalidPayload
from .pipeline import NothingToShow, run
from .store import connect


def progress(message: str) -> None:
    """Report what the run is doing, on stderr so stdout stays pipeable."""
    print(message, file=sys.stderr)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="resumen",
        description="Resumen de la prensa local de Ceuta, agrupado por temas.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenera el resumen ignorando la caché",
    )
    parser.add_argument("--version", action="version", version=f"resumen {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pipeline. Returns the process exit code."""
    args = parse_args(argv)
    try:
        key = load_api_key(warn=progress)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    # Opening the database creates it and applies the schema, on every run.
    connection = connect()
    try:
        print(
            run(connection, sources(), lambda: Gemini(key), progress, force=args.force)
        )
    except (TransportError, InvalidPayload, NothingToShow) as error:
        # Nothing was written, so the next run retries from a clean slate.
        print(error, file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
