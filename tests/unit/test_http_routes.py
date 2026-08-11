"""Unit tests for HTTP-only application routes."""

import asyncio
from unittest.mock import Mock

from mcp.server.fastmcp import FastMCP

from garmin_mcp import _HEALTH_PATH, _register_http_routes


def test_health_route_uses_cloud_run_safe_path_and_returns_ok():
    server = FastMCP("HTTP route test")

    _register_http_routes(server)

    routes = {route.path: route for route in server._custom_starlette_routes}
    assert _HEALTH_PATH == "/health"
    assert "/healthz" not in routes
    assert routes[_HEALTH_PATH].methods == {"GET", "HEAD"}

    response = asyncio.run(routes[_HEALTH_PATH].endpoint(Mock()))
    assert response.status_code == 200
    assert response.body == b"ok"
