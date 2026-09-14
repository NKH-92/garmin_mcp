"""Persist refreshed Garmin OAuth tokens back to Google Secret Manager."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Protocol, TextIO


class _SecretManagerClient(Protocol):
    def add_secret_version(self, *, request: dict): ...


def _default_client_factory() -> _SecretManagerClient:
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


class SecretTokenPublisher:
    """Publish a changed, valid Garmin token file as a new secret version.

    The token loaded from the mounted secret is treated as the baseline. Garmin's
    client rewrites the writable runtime copy whenever it refreshes OAuth. Calls
    after login and after successful API requests detect that rewrite and publish
    it once. Publishing is best-effort so a temporary Google API failure does not
    take down an otherwise authenticated MCP service; the unchanged digest makes
    the next successful Garmin request retry the publication.
    """

    def __init__(
        self,
        token_file: Path,
        secret_resource: str | None,
        *,
        client_factory: Callable[[], _SecretManagerClient] = _default_client_factory,
        error_stream: TextIO | None = None,
    ) -> None:
        self._token_file = token_file
        self._secret_resource = (secret_resource or "").strip()
        self._client_factory = client_factory
        # Do not capture sys.stderr at import time. Test runners and MCP hosts may
        # replace or close their stream objects during the process lifetime.
        self._error_stream = error_stream
        self._lock = threading.Lock()
        self._last_published_digest = self._read_digest() if self.enabled else None

    @classmethod
    def from_environment(cls, tokenstore: str | os.PathLike[str]) -> "SecretTokenPublisher":
        token_path = Path(tokenstore).expanduser()
        if token_path.suffix.lower() != ".json":
            token_path /= "garmin_tokens.json"
        return cls(
            token_path,
            os.getenv("GARMIN_TOKEN_SECRET_RESOURCE"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._secret_resource)

    def _read_payload(self) -> bytes:
        payload = self._token_file.read_bytes()
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError("Garmin token file must contain a JSON object")
        return payload

    def _read_digest(self) -> str | None:
        try:
            return hashlib.sha256(self._read_payload()).hexdigest()
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def publish_if_changed(self) -> bool:
        """Publish changed token bytes once; return True only on publication."""
        if not self.enabled:
            return False

        with self._lock:
            try:
                payload = self._read_payload()
                digest = hashlib.sha256(payload).hexdigest()
                if digest == self._last_published_digest:
                    return False

                response = self._client_factory().add_secret_version(
                    request={
                        "parent": self._secret_resource,
                        "payload": {"data": payload},
                    }
                )
                self._last_published_digest = digest
                version_name = getattr(response, "name", "new version")
                print(
                    f"Garmin OAuth token refresh persisted to Secret Manager: {version_name}",
                    file=self._error_stream or sys.stderr,
                )
                return True
            except Exception as exc:  # availability-first; next call retries
                print(
                    "ERROR: Failed to persist refreshed Garmin OAuth tokens to "
                    f"Secret Manager ({type(exc).__name__}). Will retry after the next "
                    "successful Garmin request.",
                    file=self._error_stream or sys.stderr,
                )
                return False
