"""Where the key and the database live, and how the key is read.

Paths follow the XDG base directory spec. That is also what makes them
redirectable: nothing here reads a location the environment cannot move, so
the tests exercise the real resolution instead of a test-only back door.
"""

import os
from collections.abc import Callable
from pathlib import Path

from dotenv import dotenv_values

APP_NAME = "resumen-ceuta"
KEY_NAME = "GEMINI_API_KEY"

# Anything readable by group or other. The key is a credential, not a config.
LOOSE_PERMISSIONS = 0o077


class ConfigError(Exception):
    """The run cannot start until the user fixes something."""


def _base_dir(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else Path.home() / fallback


def config_dir() -> Path:
    return _base_dir("XDG_CONFIG_HOME", ".config") / APP_NAME


def data_dir() -> Path:
    return _base_dir("XDG_DATA_HOME", ".local/share") / APP_NAME


def env_file() -> Path:
    return config_dir() / "env"


def database_path() -> Path:
    return data_dir() / "db.sqlite3"


def _instructions(path: Path, problem: str) -> str:
    """Say what is wrong and exactly what to write. Never echo file contents."""
    return "\n".join(
        [
            problem,
            "",
            f"Crea {path} con esta única línea:",
            "",
            f"    {KEY_NAME}=tu-clave",
            "",
            f"y protégelo:  chmod 600 {path}",
            "",
            "La clave se genera en https://aistudio.google.com/apikey",
        ]
    )


def load_api_key(warn: Callable[[str], None] = lambda message: None) -> str:
    """Return the Gemini API key, or explain precisely how to provide it."""
    path = env_file()
    if not path.is_file():
        problem = f"No encuentro la API key de Gemini en {path}."
        raise ConfigError(_instructions(path, problem))

    if path.stat().st_mode & LOOSE_PERMISSIONS:
        warn(
            f"aviso: {path} es legible por otros usuarios. "
            f"Corrígelo con: chmod 600 {path}"
        )

    key = (dotenv_values(path).get(KEY_NAME) or "").strip()
    if not key:
        problem = f"{path} existe pero no define {KEY_NAME}."
        raise ConfigError(_instructions(path, problem))
    return key
