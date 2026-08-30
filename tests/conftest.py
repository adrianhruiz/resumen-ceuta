"""Fixtures that move the app's fixed paths into a temporary directory."""

import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from resumen.feeds import SOURCES, Source
from resumen.store import Article

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
RECORDED = ("faro-2026-08-30.xml", "pueblo-2026-08-30.xml")

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


@pytest.fixture
def served_feeds(httpserver: HTTPServer) -> tuple[Source, ...]:
    """Both feeds, served from a local HTTP server out of the recorded XML."""
    served = []
    for source, name in zip(SOURCES, RECORDED, strict=True):
        path = f"/{source.name}"
        httpserver.expect_request(path).respond_with_data(
            (FIXTURES / name).read_bytes(), content_type="application/rss+xml"
        )
        served.append(Source(source.name, httpserver.url_for(path), source.id_pattern))
    return tuple(served)


@pytest.fixture
def served_env(
    served_feeds: tuple[Source, ...], monkeypatch: pytest.MonkeyPatch
) -> tuple[Source, ...]:
    """The same, but through the environment, so a child process finds them.

    Without this a subprocess test would reach the real feeds, which is
    exactly what the network marker exists to keep out of the gate.
    """
    for source in served_feeds:
        monkeypatch.setenv(f"RESUMEN_{source.name.upper()}_URL", source.url)
    return served_feeds
