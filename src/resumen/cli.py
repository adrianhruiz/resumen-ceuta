"""Command line entry point.

stdout carries the summary and nothing else, so it stays usable through a pipe.
Everything the user reads while waiting goes to stderr.
"""

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, database_path, load_api_key
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
    parse_args(argv)
    try:
        load_api_key(warn=progress)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    # Opening the database creates it and applies the schema, on every run.
    connect().close()
    progress(
        f"resumen: base de datos en {database_path()}, sin fuentes que leer todavía"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
