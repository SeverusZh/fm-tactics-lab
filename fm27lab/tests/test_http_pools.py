import base64
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.adapters.fmf import FmfCodec
from fm27lab.interfaces.http.routes.pools import FMF_SIZE_ERROR, MAX_FMF_BYTES
from fm27lab.tests.test_http_drafts import scenario
from fm27lab.tests.test_http_health import make_app
from fm27lab.tests.test_pool_schema import tactic


def fmf_payload(*, tactic_name: str = "客队战术") -> bytes:
    document = scenario(23)
    document["teams"][0].update(tactic(tactic_name=tactic_name))
    return FmfCodec().encode(document)


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def payload(name="Corner", weight=2, **extra):
    value = {
        "name": name,
        "weight": weight,
        "tactic": {"tactic_name": "角球", "mentality": 3},
        "roster": {"club_uid": 7},
    }
    value.update(extra)
    return value


def test_pool_http_requires_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/pools").status_code == 401
    assert client.post("/api/pools", json=payload()).status_code == 401
    assert client.get("/api/pools/none").status_code == 401
    assert client.patch("/api/pools/none", json={"name": "x"}).status_code == 401
    assert (
        client.post(
            "/api/pools/import-fmf",
            json={"content_base64": base64.b64encode(fmf_payload()).decode("ascii")},
        ).status_code
        == 401
    )
    assert client.delete("/api/pools/none").status_code == 401


def test_pool_http_round_trip(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post("/api/pools", json=payload(), headers=headers)
    assert created.status_code == 201
    entry = created.json()
    assert entry["id"]
    assert entry["tactic"]["tactic_name"] == "角球"
    assert entry["roster"]["club_uid"] == 7
    listed = client.get("/api/pools", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == [entry]
    assert listed.json()["total"] == 1
    assert listed.json()["next_offset"] is None
    fetched = client.get(f"/api/pools/{entry['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == entry
    removed = client.delete(f"/api/pools/{entry['id']}", headers=headers)
    assert removed.status_code == 204
    assert client.get(f"/api/pools/{entry['id']}", headers=headers).status_code == 404


def test_pool_http_validation_and_missing_are_error_envelopes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    bad = client.post("/api/pools", json={"name": "", "weight": 1, "tactic": {}}, headers=headers)
    assert bad.status_code == 400
    error = bad.json()["error"]
    assert error["code"] == "validation_failed"
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    missing = client.get("/api/pools/missing", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert client.delete("/api/pools/missing", headers=headers).status_code == 404


def test_pool_http_rejects_path_unsafe_ids_and_loose_weight(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for unsafe in ("a/b", "..", "a%2Fb", " "):
        response = client.post("/api/pools", json=payload(id=unsafe), headers=headers)
        assert response.status_code == 400, unsafe
    for weight in (True, "2", 1.0):
        response = client.post("/api/pools", json=payload(weight=weight), headers=headers)
        assert response.status_code == 400, weight


def test_pool_http_pagination_and_error_headers(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for index in range(3):
        assert client.post("/api/pools", json=payload(f"P{index}"), headers=headers).status_code == 201
    page = client.get("/api/pools?limit=2&offset=0", headers=headers).json()
    assert len(page["items"]) == 2
    assert page["total"] == 3
    assert page["next_offset"] == 2
    denied = client.get("/api/pools")
    assert denied.headers["www-authenticate"] == "Bearer"


def test_pool_http_duplicate_id_conflicts(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    first = client.post("/api/pools", json=payload(id="fixed"), headers=headers)
    assert first.status_code == 201
    duplicate = client.post("/api/pools", json=payload("Other", id="fixed"), headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"


def test_pool_http_openapi_exposes_routes(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)
    document = client.get("/api/openapi.json").json()
    paths = document["paths"]
    assert "/api/pools" in paths
    assert "/api/pools/{entry_id}" in paths
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert paths["/api/pools"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("PoolListOutput")
    assert paths["/api/pools"]["post"]["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("PoolEntryOutput")
    assert "/api/pools/import-fmf" in paths
    assert paths["/api/pools/import-fmf"]["post"]["responses"]["201"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("PoolImportOutput")
    assert paths["/api/pools/{entry_id}"]["patch"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("PoolEntryOutput")


def test_openapi_removes_422_and_documents_error_envelope(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    for path, operations in document["paths"].items():
        if not path.startswith("/api/pools"):
            continue
        for operation in operations.values():
            assert "422" not in operation["responses"], (path, operation)
            assert "400" in operation["responses"], path
            schema = operation["responses"]["400"]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorEnvelope")


def test_405_allow_lists_all_methods_and_bearer_is_case_insensitive(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    wrong = client.put("/api/pools", headers=headers)
    assert wrong.status_code == 405
    assert "GET" in wrong.headers["allow"] and "POST" in wrong.headers["allow"]
    wrong_member = client.put("/api/pools/x", headers=headers)
    assert wrong_member.status_code == 405
    allow = wrong_member.headers["allow"]
    assert "GET" in allow and "PATCH" in allow and "DELETE" in allow
    lower = client.get("/api/pools", headers={"Authorization": f"bearer {settings.token}"})
    assert lower.status_code == 200


def test_pagination_boundaries_strict_query_and_204_body(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for index in range(3):
        assert client.post("/api/pools", json=payload(f"P{index}"), headers=headers).status_code == 201
    last = client.get("/api/pools?limit=2&offset=2", headers=headers).json()
    assert len(last["items"]) == 1
    assert last["next_offset"] is None
    beyond = client.get("/api/pools?limit=2&offset=99", headers=headers).json()
    assert beyond["items"] == []
    assert beyond["next_offset"] is None
    for query in ("limit=1.0", "limit=0", "limit=129", "limit=abc", "offset=-1", "offset=abc"):
        assert client.get(f"/api/pools?{query}", headers=headers).status_code == 400, query
    created = client.post("/api/pools", json=payload("Delete"), headers=headers).json()
    removed = client.delete(f"/api/pools/{created['id']}", headers=headers)
    assert removed.status_code == 204
    assert removed.content == b""
    assert "content-type" not in removed.headers


def test_duplicate_conflict_keeps_original_and_pool_service_injection(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    original = client.post("/api/pools", json=payload(id="fixed"), headers=headers).json()
    conflict = client.post("/api/pools", json=payload("Other", id="fixed"), headers=headers)
    assert conflict.status_code == 409
    assert client.get("/api/pools/fixed", headers=headers).json() == original

    class FakeService:
        def list(self, limit=128, offset=0):
            return {"items": [], "total": 0, "next_offset": None}

        def create(self, value):
            return {"id": "fake", **value, "created_at": "now"}

        def get(self, entry_id):
            return None

        def delete(self, entry_id):
            return False

    from fm27lab.interfaces.http.app import create_app

    second = create_app(settings, database, pool_service=FakeService())
    assert TestClient(second).get("/api/pools", headers=headers).json()["items"] == []


def test_pool_http_updates_name_and_weight(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post("/api/pools", json=payload(), headers=headers).json()
    renamed = client.patch(
        f"/api/pools/{created['id']}",
        json={"name": "  改名  ", "weight": 9},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    updated = renamed.json()
    assert updated["name"] == "改名"
    assert updated["weight"] == 9
    assert updated["tactic"] == created["tactic"]
    assert updated["roster"] == created["roster"]
    assert client.get(f"/api/pools/{created['id']}", headers=headers).json() == updated
    only_weight = client.patch(f"/api/pools/{created['id']}", json={"weight": 3}, headers=headers)
    assert only_weight.status_code == 200
    assert only_weight.json()["name"] == "改名"
    assert only_weight.json()["weight"] == 3


def test_pool_http_update_rejects_invalid_payloads(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post("/api/pools", json=payload(), headers=headers).json()
    for body in (
        {},
        {"weight": 0},
        {"weight": 1001},
        {"weight": True},
        {"weight": "2"},
        {"weight": 1.5},
        {"name": ""},
        {"name": "   "},
        {"tactic": {}},
        {"name": "x", "unknown": 1},
    ):
        response = client.patch(f"/api/pools/{created['id']}", json=body, headers=headers)
        assert response.status_code == 400, body
        assert response.json()["error"]["code"] == "validation_failed", body
    missing = client.patch("/api/pools/missing", json={"name": "x"}, headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert client.patch("/api/pools/a b", json={"name": "x"}, headers=headers).status_code == 400


def test_pool_http_import_fmf_creates_entries(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    content = base64.b64encode(fmf_payload()).decode("ascii")
    response = client.post(
        "/api/pools/import-fmf",
        json={"content_base64": content, "name": "导入战术"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["total"] == 1
    item = imported["items"][0]
    assert item["id"]
    assert item["name"] == "导入战术"
    assert item["weight"] == 1
    assert item["roster"] is None
    assert item["tactic"]["tactic_name"] == "客队战术"
    assert item["tactic"]["mentality"] == 3
    assert item["tactic"]["native_extra_team_bits"] == "0"
    assert len(item["tactic"]["phases"]) == 2
    listed = client.get("/api/pools", headers=headers).json()
    assert listed["items"] == [item]
    assert listed["total"] == 1

    duplicate = client.post(
        "/api/pools/import-fmf",
        json={"content_base64": content, "name": "导入战术"},
        headers=headers,
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["items"][0]["name"] == "导入战术 2"

    anonymous = client.post(
        "/api/pools/import-fmf", json={"content_base64": content}, headers=headers
    )
    assert anonymous.status_code == 201, anonymous.text
    assert anonymous.json()["items"][0]["name"] == "导入战术 3"


def test_pool_http_import_fmf_uses_name_as_entry_name(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    content = base64.b64encode(fmf_payload(tactic_name="高压")).decode("ascii")
    response = client.post(
        "/api/pools/import-fmf",
        json={"content_base64": content, "name": "主战术"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["tactic"]["tactic_name"] == "高压"
    listed = client.get("/api/pools", headers=headers).json()
    assert [row["name"] for row in listed["items"]] == ["主战术"]


def test_pool_http_import_fmf_rejects_bad_files(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    no_tactic = FmfCodec().encode(scenario(23))
    bad_cases = (
        {"content_base64": "not base64!"},
        {"content_base64": base64.b64encode(b"not a fmf file").decode("ascii")},
        {"content_base64": base64.b64encode(b"FMFV2" + (2).to_bytes(4, "big") + b"{}").decode("ascii")},
        {"content_base64": base64.b64encode(no_tactic).decode("ascii")},
        {"content_base64": ""},
        {"name": "x"},
        {"content_base64": 123},
        {"content_base64": "Rk1GVjI=", "unknown": True},
    )
    for body in bad_cases:
        response = client.post("/api/pools/import-fmf", json=body, headers=headers)
        assert response.status_code == 400, body
        assert response.json()["error"]["code"] == "validation_failed", body
    assert client.get("/api/pools", headers=headers).json()["total"] == 0


def test_pool_http_import_fmf_rejects_oversized_content(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    oversized = base64.b64encode(b"\0" * (MAX_FMF_BYTES + 1)).decode("ascii")
    response = client.post(
        "/api/pools/import-fmf",
        json={"content_base64": oversized},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == FMF_SIZE_ERROR


def test_openapi_pagination_and_all_error_schemas(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    parameters = {
        item["name"]: item["schema"] for item in document["paths"]["/api/pools"]["get"]["parameters"]
    }
    assert parameters["limit"]["type"] == "integer"
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 128
    assert parameters["offset"]["minimum"] == 0
    assert parameters["limit"]["default"] == 128
    assert parameters["offset"]["default"] == 0
    get_responses = document["paths"]["/api/pools/{entry_id}"]["get"]["responses"]
    for status in ("400", "401", "404"):
        assert get_responses[status]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ErrorEnvelope"
        )
    post_responses = document["paths"]["/api/pools"]["post"]["responses"]
    assert post_responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")
