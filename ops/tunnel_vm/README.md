# Always-on Secure MCP Tunnel VM

This directory contains the Google Compute Engine runtime for the private
Garmin MCP Cloud Run service.

- `cloud_run_auth_proxy.py` listens only on loopback and obtains short-lived
  Cloud Run identity tokens from the VM metadata server.
- `bootstrap.sh` installs the pinned OpenAI `tunnel-client`, configures both
  processes as systemd services, and leaves the tunnel stopped until its
  runtime key is installed.
- `scripts/install_tunnel_runtime_key.ps1` prompts for the runtime key locally
  and sends it over IAP SSH stdin. The key is not placed in Git, Secret Manager,
  command arguments, or PowerShell history.

The intended VM is an `e2-micro` in `us-west1-b` with a 10 GB standard persistent
disk. The machine and disk fit the Google Cloud Free Tier allowance, but an
always-on external IPv4 address is billed separately. Do not create the VM until
the operator accepts that recurring network-address charge.

The VM service account needs only `roles/run.invoker` on the `garmin-mcp` Cloud
Run service. The VPC must allow outbound HTTPS and should have no public inbound
firewall rule; administration uses IAP TCP forwarding.
