import base64
import json

from ops.tunnel_vm.cloud_run_auth_proxy import _jwt_exp


def test_jwt_exp_reads_urlsafe_payload_without_padding():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1234567890}).encode()).decode()
    token = f"header.{payload.rstrip('=')}.signature"

    assert _jwt_exp(token) == 1234567890
