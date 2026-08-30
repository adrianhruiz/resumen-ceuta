"""Unit tests for path resolution and key loading."""

import stat
from pathlib import Path

import pytest

from resumen.config import (
    ConfigError,
    config_dir,
    data_dir,
    database_path,
    env_file,
    load_api_key,
)


def test_paths_follow_the_xdg_variables(home: Path) -> None:
    assert config_dir() == home / "config" / "resumen-ceuta"
    assert data_dir() == home / "data" / "resumen-ceuta"
    assert env_file() == home / "config" / "resumen-ceuta" / "env"
    assert database_path() == home / "data" / "resumen-ceuta" / "db.sqlite3"


def test_paths_fall_back_to_the_home_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/casa")))
    assert config_dir() == Path("/casa/.config/resumen-ceuta")
    assert data_dir() == Path("/casa/.local/share/resumen-ceuta")


def test_a_valid_key_is_returned(env_file: Path, valid_key: str) -> None:
    assert load_api_key() == valid_key


def test_surrounding_whitespace_is_stripped(env_file: Path, valid_key: str) -> None:
    env_file.write_text(f"GEMINI_API_KEY=  {valid_key}  \n", encoding="utf-8")
    assert load_api_key() == valid_key


def test_a_missing_file_names_the_file_and_the_line_to_write(home: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        load_api_key()
    message = str(raised.value)
    assert str(home / "config" / "resumen-ceuta" / "env") in message
    assert "GEMINI_API_KEY=tu-clave" in message
    assert "chmod 600" in message
    assert "https://aistudio.google.com/apikey" in message


def test_a_file_without_the_key_is_rejected(env_file: Path) -> None:
    env_file.write_text("OTRA_COSA=1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_api_key()


def test_an_empty_key_is_rejected(env_file: Path) -> None:
    env_file.write_text("GEMINI_API_KEY=   \n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_api_key()


def test_no_error_message_ever_leaks_the_file_contents(env_file: Path) -> None:
    # A typo in the variable name is the realistic way a secret ends up in a
    # file the app then complains about. The complaint must not quote it.
    env_file.write_text("GEMINI_APIKEY=secreto-que-no-debe-salir\n", encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_api_key()
    assert "secreto-que-no-debe-salir" not in str(raised.value)


def test_loose_permissions_are_reported_without_blocking(
    env_file: Path, valid_key: str
) -> None:
    env_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    warnings: list[str] = []
    assert load_api_key(warn=warnings.append) == valid_key
    assert len(warnings) == 1
    assert "chmod 600" in warnings[0]


def test_tight_permissions_are_silent(env_file: Path) -> None:
    warnings: list[str] = []
    load_api_key(warn=warnings.append)
    assert warnings == []
