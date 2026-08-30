"""Fixtures that move the app's fixed paths into a temporary directory."""

import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from resumen.store import Article

VALID_KEY = "clave-de-prueba"


@pytest.fixture
def valid_key() -> str:
    return VALID_KEY


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect the XDG base directories, as a real environment would.

    monkeypatch edits os.environ, so a child process started by a test
    inherits these too and resolves the same paths.
    """
    config, data = tmp_path / "config", tmp_path / "data"
    config.mkdir()
    data.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    yield tmp_path


@pytest.fixture
def env_file(home: Path) -> Path:
    """A config directory holding a well-formed, properly protected key file."""
    path = home / "config" / "resumen-ceuta" / "env"
    path.parent.mkdir(parents=True)
    path.write_text(f"GEMINI_API_KEY={VALID_KEY}\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


@pytest.fixture
def article() -> Callable[..., Article]:
    """Build an article, overriding only what the test cares about."""

    def build(**overrides: object) -> Article:
        defaults: dict[str, object] = {
            "source": "faro",
            "external_id": "1436869",
            "guid": "https://elfarodeceuta.es/?p=1436869",
            "title": "Prisión para los cuatro detenidos por la emboscada",
            "description": "La jueza decreta prisión provisional.",
            "body": "Texto plano del cuerpo.",
            "url": "https://elfarodeceuta.es/prision-cuatro-detenidos/",
            "pubdate": "2026-08-30T10:27:00+00:00",
            "day": "2026-08-30",
        }
        return Article(**(defaults | overrides))  # type: ignore[arg-type]

    return build
