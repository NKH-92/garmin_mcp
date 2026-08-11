import os

import pytest

from garmin_mcp import _prepare_tokenstore_from_secret


def test_secret_bootstrap_is_noop_when_secret_env_unset(monkeypatch):
    monkeypatch.delenv("GARMIN_TOKEN_SECRET_FILE", raising=False)
    monkeypatch.setenv("GARMINTOKENS", "original-token-path")

    _prepare_tokenstore_from_secret()

    assert os.environ["GARMINTOKENS"] == "original-token-path"


def test_secret_bootstrap_copies_token_to_runtime_dir(tmp_path, monkeypatch):
    secret_file = tmp_path / "mounted-secret"
    secret_content = '{"test": "fake-garmin-token"}'
    secret_file.write_text(secret_content, encoding="utf-8")

    runtime_dir = tmp_path / "garmin-runtime"

    monkeypatch.setenv("GARMIN_TOKEN_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("GARMIN_TOKEN_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.delenv("GARMINTOKENS", raising=False)

    _prepare_tokenstore_from_secret()

    runtime_token = runtime_dir / "garmin_tokens.json"

    assert runtime_token.is_file()
    assert runtime_token.read_text(encoding="utf-8") == secret_content
    assert os.environ["GARMINTOKENS"] == str(runtime_dir)


def test_secret_bootstrap_fails_when_secret_file_missing(tmp_path, monkeypatch):
    missing_file = tmp_path / "missing-secret"

    monkeypatch.setenv("GARMIN_TOKEN_SECRET_FILE", str(missing_file))
    monkeypatch.setenv(
        "GARMIN_TOKEN_RUNTIME_DIR",
        str(tmp_path / "garmin-runtime"),
    )

    with pytest.raises(FileNotFoundError, match="Garmin token secret file not found"):
        _prepare_tokenstore_from_secret()
