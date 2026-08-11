#!/usr/bin/env bash
set -euo pipefail

TUNNEL_CLIENT_VERSION="v0.0.11"
TUNNEL_CLIENT_SHA256="29adfe5c1399dfb9fda9383f230c324355912f50dc36e2e416b1f1322317b3c4"
TUNNEL_ID="tunnel_6a7b0e9cf41c81918e14bc9d46db9922"
CLOUD_RUN_BASE_URL="https://garmin-mcp-smrc6iymhq-du.a.run.app"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl python3 unzip
rm -rf /var/lib/apt/lists/*

id -u garmin-tunnel >/dev/null 2>&1 || \
  useradd --system --home-dir /var/lib/garmin-tunnel --create-home --shell /usr/sbin/nologin garmin-tunnel
install -d -o root -g garmin-tunnel -m 0750 /etc/garmin-mcp-tunnel
install -d -o garmin-tunnel -g garmin-tunnel -m 0750 /var/lib/garmin-tunnel /var/log/tunnel-client
install -d -o root -g root -m 0755 /opt/tunnel-client

archive="$(mktemp)"
curl --fail --location --silent --show-error \
  "https://github.com/openai/tunnel-client/releases/download/${TUNNEL_CLIENT_VERSION}/tunnel-client-${TUNNEL_CLIENT_VERSION}-linux-amd64.zip" \
  --output "$archive"
echo "${TUNNEL_CLIENT_SHA256}  ${archive}" | sha256sum --check --status
tmpdir="$(mktemp -d)"
unzip -q "$archive" -d "$tmpdir"
install -o root -g root -m 0755 "$(find "$tmpdir" -type f -name tunnel-client -print -quit)" /opt/tunnel-client/tunnel-client
rm -rf "$archive" "$tmpdir"

install -o root -g root -m 0755 /tmp/cloud_run_auth_proxy.py /opt/tunnel-client/cloud_run_auth_proxy.py

cat >/etc/garmin-mcp-tunnel/tunnel-client.yaml <<EOF
config_version: 1
control_plane:
  tunnel_id: ${TUNNEL_ID}
  api_key: file:/etc/garmin-mcp-tunnel/control-plane-api-key
log:
  level: info
  format: json
health:
  listen_addr: 127.0.0.1:8080
admin_ui:
  open_browser: false
mcp:
  server_urls:
    - channel: main
      url: http://127.0.0.1:8765/mcp
EOF
chown root:garmin-tunnel /etc/garmin-mcp-tunnel/tunnel-client.yaml
chmod 0640 /etc/garmin-mcp-tunnel/tunnel-client.yaml

cat >/etc/systemd/system/garmin-cloud-run-proxy.service <<EOF
[Unit]
Description=Authenticated loopback proxy for Garmin MCP Cloud Run
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=garmin-tunnel
Group=garmin-tunnel
Environment=CLOUD_RUN_BASE_URL=${CLOUD_RUN_BASE_URL}
ExecStart=/usr/bin/python3 /opt/tunnel-client/cloud_run_auth_proxy.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/garmin-tunnel-client.service <<'EOF'
[Unit]
Description=OpenAI Secure MCP Tunnel for Garmin
After=network-online.target garmin-cloud-run-proxy.service
Wants=network-online.target garmin-cloud-run-proxy.service
ConditionPathExists=/etc/garmin-mcp-tunnel/control-plane-api-key

[Service]
Type=simple
User=garmin-tunnel
Group=garmin-tunnel
WorkingDirectory=/var/lib/garmin-tunnel
ExecStart=/opt/tunnel-client/tunnel-client run --config /etc/garmin-mcp-tunnel/tunnel-client.yaml
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/garmin-tunnel /var/log/tunnel-client

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now garmin-cloud-run-proxy.service
systemctl enable garmin-tunnel-client.service

curl --fail --silent http://127.0.0.1:8765/health >/dev/null
/opt/tunnel-client/tunnel-client --version
