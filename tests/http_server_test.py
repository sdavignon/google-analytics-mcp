from starlette.testclient import TestClient

from analytics_mcp.http_server import create_app


def test_mcp_path_redirects_to_relative_trailing_slash(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    with TestClient(create_app()) as client:
        response = client.get(
            "/mcp",
            headers={"Authorization": "Bearer secret-token"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp/"


def test_root_redirects_to_mcp_path(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    with TestClient(create_app()) as client:
        response = client.get(
            "/",
            headers={"Authorization": "Bearer secret-token"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp"


def test_health_remains_public_without_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "analytics-mcp"}


def test_mcp_fails_closed_without_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/mcp", follow_redirects=False)

    assert response.status_code == 503
    assert response.json() == {"error": "MCP_AUTH_TOKEN is not configured"}


def test_mcp_requires_configured_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    with TestClient(create_app()) as client:
        response = client.get("/mcp", follow_redirects=False)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "Unauthorized"}


def test_mcp_accepts_configured_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    with TestClient(create_app()) as client:
        response = client.get(
            "/mcp",
            headers={"Authorization": "Bearer secret-token"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp/"
