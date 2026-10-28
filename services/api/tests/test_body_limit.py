from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.bodylimit import MAX_BODY_BYTES

LOGIN = "/auth/login"


def chunks(total: int) -> Iterator[bytes]:
    for _ in range(total // 1_000_000):
        yield b"x" * 1_000_000


def test_a_body_that_announces_a_size_over_the_limit_is_refused_before_it_is_read(
    db_client: TestClient,
) -> None:
    refused = db_client.post(LOGIN, content=b"x" * (MAX_BODY_BYTES + 1))
    assert refused.status_code == 413


def test_a_chunked_body_over_the_limit_is_refused_too(db_client: TestClient) -> None:
    refused = db_client.post(LOGIN, content=chunks(MAX_BODY_BYTES + 1_000_000))
    assert refused.status_code == 413
    assert "MB" in refused.json()["detail"]


def test_a_body_inside_the_limit_reaches_the_route(db_client: TestClient) -> None:
    body = {"email": "a@b.in", "password": "p" * 100}
    assert db_client.post(LOGIN, json=body).status_code == 401  # answered by the route, not refused
    big_but_fine = db_client.post(LOGIN, content=b"x" * (MAX_BODY_BYTES - 1))
    assert big_but_fine.status_code == 422
