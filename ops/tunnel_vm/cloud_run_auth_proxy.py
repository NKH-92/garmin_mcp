#!/usr/bin/env python3
"""Loopback proxy that adds a short-lived Cloud Run identity token."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _jwt_exp(token: str) -> int:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])


class IdentityTokenProvider:
    def __init__(self, audience: str, refresh_skew_seconds: int = 300) -> None:
        self.audience = audience
        self.refresh_skew_seconds = refresh_skew_seconds
        self._token = ""
        self._expires_at = 0
        self._lock = threading.Lock()

    def get(self) -> str:
        now = int(time.time())
        if self._token and now < self._expires_at - self.refresh_skew_seconds:
            return self._token
        with self._lock:
            now = int(time.time())
            if self._token and now < self._expires_at - self.refresh_skew_seconds:
                return self._token
            query = urllib.parse.urlencode(
                {"audience": self.audience, "format": "full"}
            )
            request = urllib.request.Request(
                f"{METADATA_IDENTITY_URL}?{query}",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                token = response.read().decode("utf-8").strip()
            self._token = token
            self._expires_at = _jwt_exp(token)
            return token


class GcloudIdentityTokenProvider:
    def __init__(
        self,
        audience: str,
        service_account: str,
        gcloud_path: str = "gcloud",
        refresh_skew_seconds: int = 300,
    ) -> None:
        self.audience = audience
        self.service_account = service_account
        self.gcloud_path = gcloud_path
        self.refresh_skew_seconds = refresh_skew_seconds
        self._token = ""
        self._expires_at = 0
        self._lock = threading.Lock()

    def get(self) -> str:
        now = int(time.time())
        if self._token and now < self._expires_at - self.refresh_skew_seconds:
            return self._token
        with self._lock:
            now = int(time.time())
            if self._token and now < self._expires_at - self.refresh_skew_seconds:
                return self._token
            result = subprocess.run(
                [
                    self.gcloud_path,
                    "auth",
                    "print-identity-token",
                    f"--impersonate-service-account={self.service_account}",
                    f"--audiences={self.audience}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            token = result.stdout.strip()
            self._token = token
            self._expires_at = _jwt_exp(token)
            return token


def make_token_provider(audience: str):
    auth_mode = os.environ.get("CLOUD_RUN_AUTH_MODE", "metadata").lower()
    if auth_mode == "metadata":
        return IdentityTokenProvider(audience)
    if auth_mode == "gcloud":
        service_account = os.environ["CLOUD_RUN_IMPERSONATE_SERVICE_ACCOUNT"]
        gcloud_path = os.environ.get("GCLOUD_PATH", "gcloud")
        return GcloudIdentityTokenProvider(audience, service_account, gcloud_path)
    raise ValueError(f"Unsupported CLOUD_RUN_AUTH_MODE: {auth_mode}")


class CloudRunProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "GarminCloudRunProxy/1.0"

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._forward()

    def _forward(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > self.server.max_request_bytes:
            self.send_error(413, "request body too large")
            return
        body = self.rfile.read(content_length) if content_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
            and key.lower() not in {"host", "authorization", "content-length"}
        }
        try:
            headers["Authorization"] = f"Bearer {self.server.token_provider.get()}"
            target = f"{self.server.cloud_run_base_url}{self.path}"
            request = urllib.request.Request(
                target,
                data=body,
                headers=headers,
                method=self.command,
            )
            try:
                response = urllib.request.urlopen(
                    request, timeout=self.server.upstream_timeout_seconds
                )
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                response_body = response.read(self.server.max_response_bytes + 1)
                if len(response_body) > self.server.max_response_bytes:
                    self.send_error(502, "upstream response too large")
                    return
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in {
                        "content-length",
                    }:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
        except Exception as exc:  # Deliberately avoid leaking tokens or response bodies.
            self.log_error("upstream request failed: %s", type(exc).__name__)
            self.send_error(502, "Cloud Run upstream unavailable")

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


class CloudRunProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], cloud_run_base_url: str) -> None:
        super().__init__(listen, CloudRunProxyHandler)
        self.cloud_run_base_url = cloud_run_base_url.rstrip("/")
        self.token_provider = make_token_provider(self.cloud_run_base_url)
        self.max_request_bytes = 10 * 1024 * 1024
        self.max_response_bytes = 10 * 1024 * 1024
        self.upstream_timeout_seconds = 600


def main() -> None:
    cloud_run_base_url = os.environ["CLOUD_RUN_BASE_URL"]
    host = os.environ.get("PROXY_LISTEN_HOST", "127.0.0.1")
    port = int(os.environ.get("PROXY_LISTEN_PORT", "8765"))
    server = CloudRunProxyServer((host, port), cloud_run_base_url)
    print(f"Cloud Run auth proxy listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
