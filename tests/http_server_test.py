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


def test_oauth_token_issues_bearer_token_for_basic_client_credentials(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    with TestClient(create_app()) as client:
        response = client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=("private-client", "private-secret"),
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "access_token": "issued-token",
        "token_type": "Bearer",
    }


def test_oauth_token_accepts_form_client_credentials(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    with TestClient(create_app()) as client:
        response = client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "private-client",
                "client_secret": "private-secret",
            },
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "issued-token"


def test_oauth_token_rejects_invalid_client_credentials(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    with TestClient(create_app()) as client:
        response = client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=("private-client", "wrong-secret"),
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"
    assert response.json() == {"error": "invalid_client"}


def test_oauth_token_rejects_unsupported_grant_type(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    with TestClient(create_app()) as client:
        response = client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code"},
            auth=("private-client", "private-secret"),
        )

    assert response.status_code == 400
    assert response.json() == {"error": "unsupported_grant_type"}
