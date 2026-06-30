import importlib.util
import os
import sys
from pathlib import Path


def test_passenger_wsgi_sets_adc_environment_before_app_import(tmp_path, monkeypatch):
    source = Path("passenger_wsgi.py").read_text(encoding="utf-8")
    passenger_module = tmp_path / "passenger_wsgi.py"
    passenger_module.write_text(source, encoding="utf-8")

    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()
    credentials_file = secrets_dir / "google-application-credentials.json"
    credentials_file.write_text('{"project_id": "test-project"}', encoding="utf-8")

    imported_env = {}
    fake_http_server = type(sys)("analytics_mcp.http_server")

    def create_app():
        imported_env["GOOGLE_APPLICATION_CREDENTIALS"] = os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        imported_env["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT")
        imported_env["GOOGLE_PROJECT_ID"] = os.environ.get("GOOGLE_PROJECT_ID")
        return "app"

    fake_http_server.create_app = create_app
    monkeypatch.setitem(sys.modules, "analytics_mcp.http_server", fake_http_server)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_PROJECT_ID", raising=False)

    spec = importlib.util.spec_from_file_location(
        "passenger_wsgi_test_entry", passenger_module
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.application == "app"
    assert imported_env == {
        "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_file),
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_PROJECT_ID": "test-project",
    }
