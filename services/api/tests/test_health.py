from fastapi.testclient import TestClient


def test_boots_without_any_key_and_reports_alive(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_names_every_dependency_that_is_down(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failed": ["postgres", "redis"]}
