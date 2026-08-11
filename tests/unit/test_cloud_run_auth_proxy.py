import base64
import json
from unittest.mock import Mock

from ops.tunnel_vm.cloud_run_auth_proxy import GcloudIdentityTokenProvider, _jwt_exp


def test_jwt_exp_reads_urlsafe_payload_without_padding():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1234567890}).encode()).decode()
    token = f"header.{payload.rstrip('=')}.signature"

    assert _jwt_exp(token) == 1234567890


def test_gcloud_provider_impersonates_service_account(monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800}).encode()).decode()
    token = f"header.{payload.rstrip('=')}.signature"
    run = Mock(return_value=Mock(stdout=f"{token}\n"))
    monkeypatch.setattr("ops.tunnel_vm.cloud_run_auth_proxy.subprocess.run", run)
    provider = GcloudIdentityTokenProvider(
        "https://example.run.app", "tunnel@example.iam.gserviceaccount.com", "gcloud.cmd"
    )

    assert provider.get() == token
    assert provider.get() == token
    run.assert_called_once()
    assert "--impersonate-service-account=tunnel@example.iam.gserviceaccount.com" in run.call_args.args[0]
    assert "--audiences=https://example.run.app" in run.call_args.args[0]
