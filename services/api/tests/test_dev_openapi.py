import json
from typing import Any

from fastapi.testclient import TestClient

from app.developer import events, public

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}


def refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return found + [r for v in node.values() for r in refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in refs(v)]
    return []


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


def check_openapi(spec: dict[str, Any]) -> None:
    """The structural rules of an OpenAPI 3.1 document that tools rely on."""
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] and spec["info"]["version"]
    assert spec["paths"] and spec["servers"][0]["url"].startswith("http")
    ids = [op["operationId"] for _, _, op in operations(spec)]
    assert len(ids) == len(set(ids)) > 5, "operation ids must be unique"
    for path, method, op in operations(spec):
        assert path.startswith("/"), path
        assert op["responses"], (path, method)
        assert any(code.startswith("2") for code in op["responses"]), (path, method)
        assert op["summary"] and op["tags"], (path, method)
        # every {name} in the path is declared as a path parameter
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
        written = {part[1:-1] for part in path.split("/") if part.startswith("{")}
        assert written == declared, (path, method)
    for ref in refs(spec):
        node: Any = spec
        for part in ref.removeprefix("#/").split("/"):
            assert part in node, f"{ref} does not resolve"
            node = node[part]
    scheme = spec["components"]["securitySchemes"]["ApiKey"]
    assert scheme["type"] == "http" and scheme["scheme"] == "bearer"
    for path, method, op in operations(spec):
        assert {"ApiKey": []} in op["security"], (path, method)


def test_the_published_spec_is_valid_and_needs_no_key_to_read(api: TestClient) -> None:
    response = api.get("/v1/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    check_openapi(spec)
    assert spec["servers"][0]["url"] == str(api.base_url).rstrip("/")


def test_the_spec_describes_exactly_the_public_routes_and_leaks_no_internal_one(
    api: TestClient,
) -> None:
    spec = api.get("/v1/openapi.json").json()
    served = {
        (path, method.lower())
        for route in public.router.routes
        for path in [route.path]  # type: ignore[attr-defined]
        for method in route.methods  # type: ignore[attr-defined]
    }
    assert {(p, m) for p, m, _ in operations(spec)} == served
    assert all(path.startswith("/v1/") for path in spec["paths"])
    assert not {"/developer", "/employees", "/auth", "/billing"} & {
        "/" + p.split("/")[1] for p in spec["paths"]
    }
    text = json.dumps(spec)
    for hidden in ("password", "jwt", "secret_key", "/vobiz", "/admin"):
        assert hidden not in text


def test_the_spec_documents_the_six_webhook_events_and_the_signature(api: TestClient) -> None:
    spec = api.get("/v1/openapi.json").json()
    assert set(spec["webhooks"]) == set(events.EVENT_TYPES)
    for kind, item in spec["webhooks"].items():
        body = item["post"]["requestBody"]["content"]["application/json"]
        assert body["example"]["type"] == kind and body["example"]["data"]
    assert "X-Axon-Signature" in spec["info"]["description"]
    assert "CallEventData" in spec["components"]["schemas"]


def test_the_postman_collection_has_one_request_for_every_operation(api: TestClient) -> None:
    spec = api.get("/v1/openapi.json").json()
    collection = api.get("/v1/postman.json").json()
    assert collection["info"]["schema"].endswith("/v2.1.0/collection.json")
    assert collection["auth"]["bearer"][0]["value"] == "{{api_key}}"
    assert {v["key"] for v in collection["variable"]} == {"base_url", "api_key"}

    requests = [item["request"] for folder in collection["item"] for item in folder["item"]]
    got = sorted((r["method"], r["url"]["raw"]) for r in requests)
    want = sorted(
        (method.upper(), "{{base_url}}" + path.replace("{", ":").replace("}", ""))
        for path, method, _ in operations(spec)
    )
    assert got == want
    lead = next(r for r in requests if r["method"] == "POST")
    assert json.loads(lead["body"]["raw"])["phone"].startswith("+91")
    assert lead["url"]["variable"][0]["key"] == "employee_id"


def test_the_checker_rejects_a_broken_spec(api: TestClient) -> None:
    """A positive control for the checks above: each of these damages must be caught."""
    import copy

    import pytest

    good = api.get("/v1/openapi.json").json()
    first_op = next(op for _, _, op in operations(good))

    def broken(change: Any) -> dict[str, Any]:
        spec: dict[str, Any] = copy.deepcopy(good)
        change(spec)
        return spec

    damages = [
        lambda s: s["paths"]["/v1/account"]["get"]["responses"]["200"].update(
            {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Nope"}}}}
        ),
        lambda s: s["paths"]["/v1/leads"]["get"].update({"operationId": first_op["operationId"]}),
        lambda s: s["paths"]["/v1/account"]["get"].update({"security": []}),
        lambda s: s["paths"]["/v1/account"]["get"].update({"responses": {}}),
        lambda s: s.update({"openapi": "2.0"}),
    ]
    for damage in damages:
        with pytest.raises((AssertionError, KeyError)):
            check_openapi(broken(damage))
