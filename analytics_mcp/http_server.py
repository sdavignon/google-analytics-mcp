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
import os

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


async def health(_request):
    return JSONResponse({"status": "ok", "service": "analytics-mcp"})


async def root(_request):
    return RedirectResponse(url="/mcp")


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

    return Starlette(
        debug=False,
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            Route("/health", endpoint=health, methods=["GET"]),
            Mount("/mcp", app=McpStreamableHttpApp(transport)),
        ],
        lifespan=lifespan,
    )


def run_http_server():
    """Runs the MCP server over Streamable HTTP."""
    host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("MCP_HTTP_PORT", "8000")))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    run_http_server()
