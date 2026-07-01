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
import time
from urllib.parse import parse_qs, urlencode, urlparse

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
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


_AUTHORIZATION_CODES: dict[str, dict[str, str | float]] = {}
_AUTHORIZATION_CODE_TTL_SECONDS = 300


def _request_base_url(request) -> str:
    return str(request.base_url).rstrip("/")


def _oauth_metadata(request) -> dict[str, object]:
    base_url = _request_base_url(request)
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "code_challenge_methods_supported": [],
    }


def _resource_metadata(request) -> dict[str, object]:
    base_url = _request_base_url(request)
    return {
        "resource": f"{base_url}/mcp",
        "authorization_servers": [base_url],
        "bearer_methods_supported": ["header"],
    }


def _redirect_with_oauth_error(
    redirect_uri: str, error: str, state: str | None = None
) -> RedirectResponse:
    query = {"error": error}
    if state is not None:
        query["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{separator}{urlencode(query)}", status_code=302
    )


def _redirect_uri_is_allowed(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    configured_redirects = [
        uri.strip()
        for uri in os.getenv("MCP_OAUTH_REDIRECT_URIS", "").split(",")
        if uri.strip()
    ]
    return not configured_redirects or redirect_uri in configured_redirects


def _issue_authorization_code(client_id: str, redirect_uri: str) -> str:
    now = time.time()
    expired_codes = [
        code
        for code, details in _AUTHORIZATION_CODES.items()
        if float(details["expires_at"]) <= now
    ]
    for code in expired_codes:
        _AUTHORIZATION_CODES.pop(code, None)

    code = secrets.token_urlsafe(32)
    _AUTHORIZATION_CODES[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "expires_at": now + _AUTHORIZATION_CODE_TTL_SECONDS,
    }
    return code


def _consume_authorization_code(code: str, client_id: str, redirect_uri: str) -> bool:
    details = _AUTHORIZATION_CODES.pop(code, None)
    if not details or float(details["expires_at"]) <= time.time():
        return False

    return secrets.compare_digest(
        str(details["client_id"]), client_id
    ) and secrets.compare_digest(str(details["redirect_uri"]), redirect_uri)


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


async def oauth_authorization_server_metadata(request):
    """Returns OAuth 2.0 Authorization Server Metadata."""
    return JSONResponse(_oauth_metadata(request))


async def oauth_protected_resource_metadata(request):
    """Returns OAuth 2.0 Protected Resource Metadata for the MCP endpoint."""
    return JSONResponse(_resource_metadata(request))


async def oauth_authorize(request):
    """Issues an authorization code for the configured private OAuth client."""
    expected_client_id = _oauth_client_id()
    if not expected_client_id or not _oauth_client_secret():
        return PlainTextResponse(
            "MCP OAuth client credentials are not configured", status_code=503
        )

    response_type = request.query_params.get("response_type", "")
    client_id = request.query_params.get("client_id", "")
    redirect_uri = request.query_params.get("redirect_uri", "")
    state = request.query_params.get("state")

    if response_type != "code":
        if redirect_uri and _redirect_uri_is_allowed(redirect_uri):
            return _redirect_with_oauth_error(
                redirect_uri, "unsupported_response_type", state
            )
        return PlainTextResponse("unsupported_response_type", status_code=400)

    if not secrets.compare_digest(client_id, expected_client_id):
        if redirect_uri and _redirect_uri_is_allowed(redirect_uri):
            return _redirect_with_oauth_error(
                redirect_uri, "unauthorized_client", state
            )
        return PlainTextResponse("unauthorized_client", status_code=401)

    if not redirect_uri or not _redirect_uri_is_allowed(redirect_uri):
        return PlainTextResponse("invalid_redirect_uri", status_code=400)

    code = _issue_authorization_code(client_id, redirect_uri)
    query = {"code": code}
    if state is not None:
        query["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{separator}{urlencode(query)}", status_code=302
    )


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
    if grant_type not in {"authorization_code", "client_credentials"}:
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

    if grant_type == "authorization_code":
        code = body.get("code", [""])[0]
        redirect_uri = body.get("redirect_uri", [""])[0]
        if not _consume_authorization_code(code, client_id, redirect_uri):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

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

        public_paths = {
            "/",
            "/health",
            "/oauth/authorize",
            "/oauth/token",
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource/mcp/",
        }

        if path in public_paths or path.startswith("/oauth/"):
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
            Route(
                "/.well-known/oauth-authorization-server",
                endpoint=oauth_authorization_server_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/openid-configuration",
                endpoint=oauth_authorization_server_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                endpoint=oauth_protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/mcp/",
                endpoint=oauth_protected_resource_metadata,
                methods=["GET"],
            ),
            Route("/oauth/authorize", endpoint=oauth_authorize, methods=["GET"]),
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
