import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from garmin_mcp.cloud_token_persistence import SecretTokenPublisher


SECRET = "projects/test-project/secrets/garmin-oauth-token"


def _write(path: Path, value: str) -> None:
    path.write_text(json.dumps({"token": value}), encoding="utf-8")


def test_disabled_publisher_is_noop(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client_factory = Mock()
    publisher = SecretTokenPublisher(token_file, None, client_factory=client_factory)

    _write(token_file, "changed")

    assert publisher.publish_if_changed() is False
    client_factory.assert_not_called()


def test_unchanged_baseline_is_not_published(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client_factory = Mock()
    publisher = SecretTokenPublisher(token_file, SECRET, client_factory=client_factory)

    assert publisher.publish_if_changed() is False
    client_factory.assert_not_called()


def test_changed_valid_json_is_published_once(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client = Mock()
    client.add_secret_version.return_value = SimpleNamespace(name=f"{SECRET}/versions/2")
    publisher = SecretTokenPublisher(token_file, SECRET, client_factory=lambda: client)

    _write(token_file, "changed")

    assert publisher.publish_if_changed() is True
    assert publisher.publish_if_changed() is False
    request = client.add_secret_version.call_args.kwargs["request"]
    assert request["parent"] == SECRET
    assert json.loads(request["payload"]["data"]) == {"token": "changed"}
    client.add_secret_version.assert_called_once()


def test_invalid_json_is_never_published(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client_factory = Mock()
    errors = io.StringIO()
    publisher = SecretTokenPublisher(
        token_file, SECRET, client_factory=client_factory, error_stream=errors
    )
    token_file.write_text("not-json", encoding="utf-8")

    assert publisher.publish_if_changed() is False
    client_factory.assert_not_called()
    assert "Failed to persist" in errors.getvalue()
    assert "not-json" not in errors.getvalue()


def test_failed_write_is_retried(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client = Mock()
    client.add_secret_version.side_effect = [RuntimeError("temporary"), SimpleNamespace(name="v2")]
    publisher = SecretTokenPublisher(token_file, SECRET, client_factory=lambda: client)
    _write(token_file, "changed")

    assert publisher.publish_if_changed() is False
    assert publisher.publish_if_changed() is True
    assert client.add_secret_version.call_count == 2


def test_concurrent_publish_adds_one_version(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    _write(token_file, "initial")
    client = Mock()
    entered = threading.Event()

    def add_secret_version(*, request):
        entered.set()
        return SimpleNamespace(name="v2")

    client.add_secret_version.side_effect = add_secret_version
    publisher = SecretTokenPublisher(token_file, SECRET, client_factory=lambda: client)
    _write(token_file, "changed")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: publisher.publish_if_changed(), range(8)))

    assert entered.is_set()
    assert results.count(True) == 1
    client.add_secret_version.assert_called_once()
