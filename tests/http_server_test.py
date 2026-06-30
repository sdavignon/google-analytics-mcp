from starlette.testclient import TestClient

from analytics_mcp.http_server import create_app


def test_mcp_path_redirects_to_relative_trailing_slash():
    with TestClient(create_app()) as client:
        response = client.get("/mcp", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp/"


def test_root_redirects_to_mcp_path():
    with TestClient(create_app()) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp"
