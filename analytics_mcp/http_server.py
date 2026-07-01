#!/usr/bin/env python

# Copyright 2025 Google LLC All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP entry point for the Google Analytics MCP server."""

from contextlib import asynccontextmanager
import base64
import os
import secrets
from urllib.parse import parse_qs

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import analytics_mcp.coordinator as coordinator
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.streamable_http import StreamableHTTPServerTransport


def _initialization_options() -> InitializationOptions:
    return InitializationOptions(
        server_name=coordinator.app.name,
        server_version="1.0.0",
        capabilities=coordinator.app.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


class McpStreamableHttpApp:
    """ASGI adapter for the MCP Streamable HTTP transport."""

    def __init__(self, transport: StreamableHTTPServerTransport):
        self._transport = transport

    async def __call__(self, scope, receive, send):
        await self._transport.handle_request(scope, receive, send)


def _oauth_configured_token() -> str:
    return os.getenv("MCP_AUTH_TOKEN", "").strip()


def _oauth_client_id() -> str:
    return os.getenv("MCP_OAUTH_CLIENT_ID", "").strip()


def _oauth_client_secret() -> str:
    return os.getenv("MCP_OAUTH_CLIENT_SECRET", "").strip()


def _extract_basic_client_credentials(request) -> tuple[str, str]:
    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return "", ""

    try:
        decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return "", ""

    client_id, separator, client_secret = decoded.partition(":")
    if not separator:
        return "", ""
    return client_id, client_secret


async def oauth_token(request):
    """Issues the configured MCP bearer token for valid private OAuth clients."""
    access_token = _oauth_configured_token()
    expected_client_id = _oauth_client_id()
    expected_client_secret = _oauth_client_secret()

    if not access_token:
        return JSONResponse(
            {
                "error": "server_error",
                "error_description": "MCP_AUTH_TOKEN is not configured",
            },
            status_code=503,
        )

    if not expected_client_id or not expected_client_secret:
        return JSONResponse(
            {
                "error": "server_error",
                "error_description": "MCP OAuth client credentials are not configured",
            },
            status_code=503,
        )

    body = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    grant_type = body.get("grant_type", [""])[0]
    if grant_type != "client_credentials":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    client_id, client_secret = _extract_basic_client_credentials(request)
    if not client_id and not client_secret:
        client_id = body.get("client_id", [""])[0]
        client_secret = body.get("client_secret", [""])[0]

    client_id_matches = secrets.compare_digest(client_id, expected_client_id)
    client_secret_matches = secrets.compare_digest(
        client_secret, expected_client_secret
    )
    if not client_id_matches or not client_secret_matches:
        return JSONResponse(
            {"error": "invalid_client"},
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def health(_request):
    return JSONResponse({"status": "ok", "service": "analytics-mcp"})


async def root(_request):
    return RedirectResponse(url="/mcp")


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/")


class BearerAuthMiddleware:
    """Simple bearer-token protection for public MCP HTTP endpoint."""

    def __init__(self, app):
        self.app = app
        self.required_token = os.getenv("MCP_AUTH_TOKEN", "").strip()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Leave health check public.
        if path in {"/health", "/oauth/token"}:
            await self.app(scope, receive, send)
            return

        # If no token is configured, fail closed instead of exposing GA data.
        if not self.required_token:
            response = JSONResponse(
                {"error": "MCP_AUTH_TOKEN is not configured"},
                status_code=503,
            )
            await response(scope, receive, send)
            return

        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }

        expected = f"Bearer {self.required_token}"
        if headers.get("authorization") != expected:
            response = JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def create_app() -> Starlette:
    """Creates the ASGI app that exposes the MCP server at /mcp."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )

    @asynccontextmanager
    async def lifespan(_app):
        async with transport.connect() as (read_stream, write_stream):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    coordinator.app.run,
                    read_stream,
                    write_stream,
                    _initialization_options(),
                )
                yield
                task_group.cancel_scope.cancel()

    app = Starlette(
        debug=False,
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/oauth/token", endpoint=oauth_token, methods=["POST"]),
            Route("/mcp", endpoint=mcp_redirect, methods=["GET"]),
            Mount("/mcp", app=McpStreamableHttpApp(transport)),
        ],
        lifespan=lifespan,
    )
    return BearerAuthMiddleware(app)


def run_http_server():
    """Runs the MCP server over Streamable HTTP."""
    host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("MCP_HTTP_PORT", "8000")))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    run_http_server()
