"""Passenger entry point for the Google Analytics MCP HTTP server.

DreamHost Passenger can load this module directly instead of invoking shell
startup scripts. Configure Google Application Default Credentials here before
importing the ASGI app so client libraries see the expected environment.
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GOOGLE_CREDENTIALS_FILE = BASE_DIR / ".secrets" / "google-application-credentials.json"
MCP_AUTH_TOKEN_FILE = BASE_DIR / ".secrets" / "mcp-auth-token"
MCP_OAUTH_CLIENT_ID_FILE = BASE_DIR / ".secrets" / "mcp-oauth-client-id"
MCP_OAUTH_CLIENT_SECRET_FILE = BASE_DIR / ".secrets" / "mcp-oauth-client-secret"
MCP_OAUTH_REDIRECT_URIS_FILE = BASE_DIR / ".secrets" / "mcp-oauth-redirect-uris"


def configure_google_application_credentials() -> None:
    """Sets ADC-related environment variables for Passenger deployments."""
    if not GOOGLE_CREDENTIALS_FILE.exists():
        return

    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", str(GOOGLE_CREDENTIALS_FILE)
    )

    try:
        with GOOGLE_CREDENTIALS_FILE.open("r", encoding="utf-8") as credentials:
            project_id = json.load(credentials).get("project_id")
    except Exception:
        return

    if project_id:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        os.environ.setdefault("GOOGLE_PROJECT_ID", project_id)


def configure_mcp_secret_file(environment_variable: str, path: Path) -> None:
    """Sets an MCP environment variable from a deployment secret file."""
    if path.exists():
        os.environ[environment_variable] = path.read_text(encoding="utf-8").strip()


def configure_mcp_secrets() -> None:
    """Sets MCP auth and OAuth settings from deployment secret files."""
    configure_mcp_secret_file("MCP_AUTH_TOKEN", MCP_AUTH_TOKEN_FILE)
    configure_mcp_secret_file("MCP_OAUTH_CLIENT_ID", MCP_OAUTH_CLIENT_ID_FILE)
    configure_mcp_secret_file("MCP_OAUTH_CLIENT_SECRET", MCP_OAUTH_CLIENT_SECRET_FILE)
    configure_mcp_secret_file("MCP_OAUTH_REDIRECT_URIS", MCP_OAUTH_REDIRECT_URIS_FILE)


configure_google_application_credentials()
configure_mcp_secrets()

from analytics_mcp.http_server import create_app

application = create_app()
