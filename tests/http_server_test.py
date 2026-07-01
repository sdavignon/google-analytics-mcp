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
            data={"grant_type": "password"},
            auth=("private-client", "private-secret"),
        )

    assert response.status_code == 400
    assert response.json() == {"error": "unsupported_grant_type"}


def test_oauth_authorization_server_metadata_is_public(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app(), base_url="https://mcp.example.com") as client:
        response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json() == {
        "issuer": "https://mcp.example.com",
        "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
        "token_endpoint": "https://mcp.example.com/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "code_challenge_methods_supported": [],
    }


def test_oauth_protected_resource_metadata_is_public(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app(), base_url="https://mcp.example.com") as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "https://mcp.example.com/mcp",
        "authorization_servers": ["https://mcp.example.com"],
        "bearer_methods_supported": ["header"],
    }


def test_root_redirect_remains_public_without_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp"


def test_oauth_protected_resource_metadata_slash_variant_is_public(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with TestClient(create_app(), base_url="https://mcp.example.com") as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp/")

    assert response.status_code == 200
    assert response.json()["resource"] == "https://mcp.example.com/mcp"


def test_oauth_authorize_issues_code_and_preserves_state(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    with TestClient(create_app()) as client:
        response = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "private-client",
                "redirect_uri": "https://chat.openai.com/aip/plugin/callback",
                "state": "state-value",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    redirect = response.headers["location"]
    assert redirect.startswith("https://chat.openai.com/aip/plugin/callback?")
    assert "code=" in redirect
    assert "state=state-value" in redirect


def test_oauth_authorization_code_can_be_exchanged_once(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setenv("MCP_AUTH_TOKEN", "issued-token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")

    redirect_uri = "https://chat.openai.com/aip/plugin/callback"
    with TestClient(create_app()) as client:
        authorize_response = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "private-client",
                "redirect_uri": redirect_uri,
            },
            follow_redirects=False,
        )
        code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][
            0
        ]

        token_response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=("private-client", "private-secret"),
        )
        reused_code_response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=("private-client", "private-secret"),
        )

    assert token_response.status_code == 200
    assert token_response.json() == {
        "access_token": "issued-token",
        "token_type": "Bearer",
    }
    assert reused_code_response.status_code == 400
    assert reused_code_response.json() == {"error": "invalid_grant"}


def test_oauth_authorize_rejects_unconfigured_redirect_uri(monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "private-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "private-secret")
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", "https://allowed.example/callback")

    with TestClient(create_app()) as client:
        response = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "private-client",
                "redirect_uri": "https://evil.example/callback",
            },
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert response.text == "invalid_redirect_uri"
