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


configure_google_application_credentials()

from analytics_mcp.http_server import create_app

application = create_app()
