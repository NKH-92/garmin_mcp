"""Verify a private Garmin MCP Cloud Run service without exposing credentials.

The script asks gcloud for the service URL and an impersonated ID token, checks
the Cloud Run-safe health route, performs the MCP initialize handshake, verifies
the read-only tool allowlist, and calls key tools.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
import shutil
import subprocess
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


EXPECTED_TOOLS = {
    "get_stats",
    "get_sleep_summary",
    "get_training_readiness",
    "get_hrv_data",
    "get_training_status",
    "get_activities_by_date",
    "get_activity",
    "get_garmin_coach_workouts",
    "get_workout_by_id",
    "get_race_calendar",
}


def _gcloud(*args: str) -> str:
    executable = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not executable:
        raise RuntimeError("gcloud executable not found")

    completed = subprocess.run(
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or "gcloud command failed"
        raise RuntimeError(detail)
    return completed.stdout.strip()


def _service_url(project: str, region: str, service: str) -> str:
    return _gcloud(
        "run",
        "services",
        "describe",
        service,
        f"--project={project}",
        f"--region={region}",
        "--format=value(status.url)",
    ).rstrip("/")


def _identity_token(service_url: str, service_account: str) -> str:
    return _gcloud(
        "auth",
        "print-identity-token",
        f"--impersonate-service-account={service_account}",
        f"--audiences={service_url}",
    )


def _readiness_payload(result) -> list[dict]:
    if result.isError:
        raise RuntimeError("get_training_readiness returned an MCP error")

    payload = "\n".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    decoded = json.loads(payload)
    if not isinstance(decoded, list) or not decoded:
        raise RuntimeError("get_training_readiness returned no records")
    if not all(isinstance(item, dict) for item in decoded):
        raise RuntimeError("get_training_readiness returned an unexpected schema")
    required = {"date", "level", "score"}
    if not required.issubset(decoded[0]):
        raise RuntimeError("get_training_readiness is missing required fields")
    return decoded


def _race_payload(result) -> dict:
    if result.isError:
        raise RuntimeError("get_race_calendar returned an MCP error")

    payload = "\n".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    decoded = json.loads(payload)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("races"), list):
        raise RuntimeError("get_race_calendar returned an unexpected schema")
    if decoded.get("count") != len(decoded["races"]):
        raise RuntimeError("get_race_calendar count does not match its race list")
    return decoded


async def _verify(args: argparse.Namespace) -> None:
    service_url = _service_url(args.project, args.region, args.service)
    token = _identity_token(service_url, args.impersonate_service_account)
    headers = {"Authorization": f"Bearer {token}"}

    timeout = httpx.Timeout(args.timeout, read=args.timeout)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        health = await client.get(f"{service_url}/health")
        health.raise_for_status()
        if health.text != "ok":
            raise RuntimeError("health endpoint returned an unexpected body")
        print("health=200 ok")

        async with streamable_http_client(
            f"{service_url}/mcp", http_client=client
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                print(f"initialize={initialized.protocolVersion}")

                listed = await session.list_tools()
                tool_names = {tool.name for tool in listed.tools}
                if tool_names != EXPECTED_TOOLS:
                    missing = sorted(EXPECTED_TOOLS - tool_names)
                    unexpected = sorted(tool_names - EXPECTED_TOOLS)
                    raise RuntimeError(
                        f"tool allowlist mismatch: missing={missing}, "
                        f"unexpected={unexpected}"
                    )
                print(f"tools/list={len(tool_names)} exact allowlist match")

                result = await session.call_tool(
                    "get_training_readiness", {"date": args.date}
                )
                records = _readiness_payload(result)
                latest = records[0]
                summary = {
                    "date": latest["date"],
                    "level": latest["level"],
                    "score": latest["score"],
                }
                print(
                    "get_training_readiness="
                    + json.dumps(summary, ensure_ascii=False, sort_keys=True)
                )

                result = await session.call_tool(
                    "get_race_calendar", {"reference_date": args.date}
                )
                race_calendar = _race_payload(result)
                print(f"get_race_calendar=count:{race_calendar['count']}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--service", default="garmin-mcp")
    parser.add_argument("--impersonate-service-account", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    try:
        asyncio.run(_verify(_parse_args()))
    except Exception as exc:
        print(f"cloud MCP verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
