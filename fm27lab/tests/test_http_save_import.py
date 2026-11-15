from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fm27lab.adapters.save_fmsave import FmsaveReader
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.save_import import SaveImportService
from fm27lab.application.saves import SavesService
from fm27lab.domain.roster import MATCH_ROSTER_SIZE, STARTERS
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_health import make_app

ATTRIBUTE_COUNT = 69
SUMMARY_KEYS = ("id", "name", "source", "created_at", "updated_at")
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
SAVE_BYTES = b"FM27 save bytes"
SAVED_STARTERS = [500, 501, 502, 105, 504, 505, 506, 108, 508, 509, 510]
SAVED_SUBSTITUTES = list(range(511, 523))
SAVED_UIDS = SAVED_STARTERS + SAVED_SUBSTITUTES
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "options", "head"}


def save_player(uid: int, *, goalkeeper: bool = False) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if goalkeeper else 7] = 18
    return {"source_uid": uid, "name": f"S{uid}", "attributes": attributes, "ability": 12}


def draft_player(uid: int, *, goalkeeper: bool = False) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if goalkeeper else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def squad(uids: list[int]) -> list[dict[str, Any]]:
    return [save_player(uid, goalkeeper=index == 0) for index, uid in enumerate(uids)]


def save_data() -> dict[str, Any]:
    return {
        "info": {
            "game": "FM27",
            "build": "27.1.0",
            "db_version": "27.0",
            "game_date": "2026-07-01",
            "save_name": "season",
        },
        "managed_clubs": [
            {
                "club_uid": 7,
                "club_name": "阿森纳",
                "club_short_name": "ARS",
                "manager_name": "教练",
                "manager_staff_uid": 71,
            }
        ],
        "clubs": [
            {"uid": 7, "unique_id": 700, "name": "Arsenal", "short_name": "Ars", "nation_id": 1},
        ],
        "squads": {7: squad(SAVED_UIDS)},
        "selections": {
            7: {
                "club_uid": 7,
                "team_id": 100,
                "team_slot": 0,
                "lineup": list(SAVED_STARTERS),
                "substitutes": list(SAVED_SUBSTITUTES),
            }
        },
    }


class FakeReader:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def read_info(self) -> dict[str, Any]:
        return copy.deepcopy(self.data["info"])

    def read_managed_clubs(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["managed_clubs"])

    def read_clubs(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["clubs"])

    def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["squads"][club_uid])

    def read_selection(self, club_uid: int) -> dict[str, Any] | None:
        return copy.deepcopy(self.data["selections"].get(club_uid))


class FakeFactory:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def __call__(self, _path: Path) -> FakeReader:
        return FakeReader(self.data)


def make_import_app(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    service = SaveImportService(
        SavesService(SavesRepository(database)),
        DraftService(DraftRepository(database)),
        FakeFactory(copy.deepcopy(save_data())),
    )
    app = create_app(settings, database, save_import_service=service)
    return app, settings, service


def auth(settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def source_file(tmp_path: Path, name: str = "season.fm", content: bytes = SAVE_BYTES) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def import_save(client: TestClient, headers: dict[str, str], path: Path, **extra: Any) -> dict[str, Any]:
    response = client.post(
        "/api/saves/import",
        json={"source_path": str(path), **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def draft_team(name: str, base: int) -> dict[str, Any]:
    return {
        "name": name,
        "players": [draft_player(base + index, goalkeeper=index == 0) for index in range(MATCH_ROSTER_SIZE)],
        "roster_size": MATCH_ROSTER_SIZE,
        "lineup": list(range(STARTERS)),
        "substitutes": list(range(STARTERS, MATCH_ROSTER_SIZE)),
        "captains": [5],
        "takers": {"penalties": [5]},
        "setpieces": {"role_priorities": {"8": [8]}},
        "phases": [{"phase": 0}, {"phase": 1}],
    }


def scenario() -> dict[str, Any]:
    return {"schema": 4, "teams": [draft_team("Home", 100), draft_team("Away", 200)]}


def generated_player(index: int) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[7] = 15
    return {
        "source_uid": f"generated:{index}",
        "name": f"占位球员 {index}",
        "attributes": attributes,
        "ability": 10,
        "generated": True,
    }


def placeholder_team(name: str, base: int, *, placeholder_starters: bool) -> dict[str, Any]:
    if placeholder_starters:
        players = [generated_player(index) for index in range(1, STARTERS + 1)]
        players += [
            draft_player(base + index, goalkeeper=index == 0) for index in range(MATCH_ROSTER_SIZE - STARTERS)
        ]
    else:
        players = [draft_player(base + index, goalkeeper=index == 0) for index in range(STARTERS)]
        players += [generated_player(index) for index in range(1, MATCH_ROSTER_SIZE - STARTERS + 1)]
    return {
        "name": name,
        "players": players,
        "roster_size": MATCH_ROSTER_SIZE,
        "lineup": list(range(STARTERS)),
        "substitutes": list(range(STARTERS, MATCH_ROSTER_SIZE)),
        "captains": [5],
        "takers": {"penalties": [5], "corners": [2]},
        "setpieces": {"role_priorities": {"8": [8]}},
        "phases": [{"phase": 0}, {"phase": 1}],
    }


def placeholder_scenario() -> dict[str, Any]:
    return {
        "schema": 4,
        "teams": [
            placeholder_team("Home", 100, placeholder_starters=False),
            placeholder_team("Away", 200, placeholder_starters=True),
        ],
    }


def create_placeholder_draft(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/drafts",
        json={"name": "Placeholders", "scenario": placeholder_scenario(), "source": {"kind": "inline"}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_draft(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/drafts",
        json={"name": "Draft", "scenario": scenario(), "source": {"kind": "inline"}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_http_save_import_requires_bearer_token(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)
    apply_body = {"save_id": "save-1", "club_uid": 7, "side": "home", "scope": "both"}
    responses = (
        client.post("/api/saves/import", json={"source_path": "/tmp/save.fm"}),
        client.get("/api/saves/save-1/squad?club_uid=7"),
        client.post("/api/drafts/draft-1/apply-roster", json=apply_body),
        client.post("/api/drafts/draft-1/undo-roster"),
    )
    for response in responses:
        assert response.status_code == 401
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.post(
        "/api/saves/import",
        json={"source_path": "/tmp/save.fm"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401


def test_http_save_import_creates_ready_save_and_reads_squad(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    path = source_file(tmp_path)

    imported = import_save(client, headers, path)

    assert set(imported) == {"save_id", "status", "managed_clubs", "clubs"}
    assert imported["status"] == "ready"
    assert imported["clubs"] == 1
    assert imported["managed_clubs"] == [{"club_uid": 7, "club_name": "阿森纳", "players": 23}]
    record = app.state.saves.get(imported["save_id"])
    assert record["status"] == "ready"
    assert record["source_path"] == str(path)
    assert record["metadata"] == {
        "game": "FM27",
        "build": "27.1.0",
        "game_date": "2026-07-01",
        "managed_club_uids": [7],
    }

    response = client.get(
        f"/api/saves/{imported['save_id']}/squad",
        params={"club_uid": 7},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"save_id", "club_uid", "club_name", "players", "selection"}
    assert body["save_id"] == imported["save_id"]
    assert body["club_uid"] == 7
    assert body["club_name"] == "阿森纳"
    assert [player["source_uid"] for player in body["players"]] == SAVED_UIDS
    assert body["selection"]["lineup"] == SAVED_STARTERS
    assert body["selection"]["substitutes"] == SAVED_SUBSTITUTES

    missing_save = client.get("/api/saves/missing/squad", params={"club_uid": 7}, headers=headers)
    assert missing_save.status_code == 404
    assert missing_save.json()["error"]["code"] == "not_found"
    missing_club = client.get(
        f"/api/saves/{imported['save_id']}/squad",
        params={"club_uid": 9},
        headers=headers,
    )
    assert missing_club.status_code == 404
    for query in ("club_uid=0", "club_uid=abc", "club_uid=1.5", ""):
        response = client.get(f"/api/saves/{imported['save_id']}/squad?{query}", headers=headers)
        assert response.status_code == 400, query
        assert response.json()["error"]["code"] == "validation_failed", query


def test_http_save_import_duplicate_conflicts_and_replace_reuses_id(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    first = import_save(client, headers, source_file(tmp_path))

    duplicate = client.post(
        "/api/saves/import",
        json={"source_path": str(source_file(tmp_path, "copy.fm"))},
        headers=headers,
    )
    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "conflict"
    assert "存档内容重复" in error["message"]
    assert app.state.saves.list(limit=256)["total"] == 1

    replaced = import_save(client, headers, source_file(tmp_path, "third.fm"), replace=True)
    assert replaced["save_id"] == first["save_id"]
    assert app.state.saves.list(limit=256)["total"] == 1
    assert app.state.saves.get(first["save_id"])["metadata"]["game"] == "FM27"


def test_http_save_import_validation_failures(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    valid = {"source_path": str(source_file(tmp_path))}

    for body, message in (
        ({"source_path": str(tmp_path / "missing.fm")}, "存档文件不存在"),
        ({"source_path": str(tmp_path)}, "存档文件不存在"),
        ({"source_path": ""}, "存档文件不存在"),
        ({"source_path": 5}, "request body"),
        ({}, "request body"),
        ({**valid, "replace": "yes"}, "request body"),
        ({**valid, "extra": True}, "request body"),
    ):
        response = client.post("/api/saves/import", json=body, headers=headers)
        assert response.status_code == 400, body
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS, body
        assert error["code"] == "validation_failed", body
        assert message in error["message"], (body, error["message"])
    assert app.state.saves.list(limit=256)["items"] == []


def test_http_apply_roster_and_undo_round_trip(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    imported = import_save(client, headers, source_file(tmp_path))
    draft = create_draft(client, headers)

    response = client.post(
        f"/api/drafts/{draft['id']}/apply-roster",
        json={
            "save_id": imported["save_id"],
            "club_uid": 7,
            "side": "home",
            "scope": "both",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"draft", "applied"}
    assert body["applied"] == {"starters": 11, "substitutes": 12}
    refetched = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert body["draft"] == {key: refetched[key] for key in SUMMARY_KEYS}
    home = refetched["scenario"]["teams"][0]
    assert [player["source_uid"] for player in home["players"]] == SAVED_UIDS
    assert home["captains"] == [3]
    assert home["phases"] == draft["scenario"]["teams"][0]["phases"]
    snapshot = refetched["source"]["roster_snapshot"]
    assert snapshot["side"] == "home"
    assert snapshot["save_id"] == imported["save_id"]
    assert snapshot["club_uid"] == 7
    assert snapshot["scenario_before"] == draft["scenario"]

    undone = client.post(f"/api/drafts/{draft['id']}/undo-roster", headers=headers)
    assert undone.status_code == 200, undone.text
    assert set(undone.json()) == {"draft"}
    restored = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert restored["scenario"] == draft["scenario"]
    assert restored["source"] == draft["source"]

    again = client.post(f"/api/drafts/{draft['id']}/undo-roster", headers=headers)
    assert again.status_code == 400
    error = again.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert "没有可撤销的阵容同步" in error["message"]


def test_http_apply_roster_scopes_replace_only_requested_section(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    imported = import_save(client, headers, source_file(tmp_path))

    starters_draft = create_draft(client, headers)
    starters = client.post(
        f"/api/drafts/{starters_draft['id']}/apply-roster",
        json={"save_id": imported["save_id"], "club_uid": 7, "side": "home", "scope": "starters"},
        headers=headers,
    )
    assert starters.status_code == 200
    assert starters.json()["applied"] == {"starters": 11, "substitutes": 0}
    home = client.get(f"/api/drafts/{starters_draft['id']}", headers=headers).json()["scenario"]["teams"][0]
    assert [player["source_uid"] for player in home["players"]] == SAVED_STARTERS + list(range(111, 123))
    assert home["substitutes"] == list(range(11, 23))

    bench_draft = create_draft(client, headers)
    bench = client.post(
        f"/api/drafts/{bench_draft['id']}/apply-roster",
        json={"save_id": imported["save_id"], "club_uid": 7, "side": "home", "scope": "bench"},
        headers=headers,
    )
    assert bench.status_code == 200
    assert bench.json()["applied"] == {"starters": 0, "substitutes": 12}
    home = client.get(f"/api/drafts/{bench_draft['id']}", headers=headers).json()["scenario"]["teams"][0]
    assert [player["source_uid"] for player in home["players"]] == list(range(100, 111)) + SAVED_SUBSTITUTES
    assert home["captains"] == [5]


def test_http_apply_roster_validation_and_missing_resources(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    imported = import_save(client, headers, source_file(tmp_path))
    draft = create_draft(client, headers)
    valid = {"save_id": imported["save_id"], "club_uid": 7, "side": "home", "scope": "both"}

    for draft_id in ("missing",):
        response = client.post(f"/api/drafts/{draft_id}/apply-roster", json=valid, headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    for body in (
        {**valid, "save_id": "missing"},
        {**valid, "club_uid": 9},
    ):
        response = client.post(f"/api/drafts/{draft['id']}/apply-roster", json=body, headers=headers)
        assert response.status_code == 404, body
        assert response.json()["error"]["code"] == "not_found", body
    for body, message in (
        ({**valid, "side": "both"}, "side"),
        ({**valid, "scope": "all"}, "scope"),
        ({**valid, "club_uid": 0}, "俱乐部标识无效"),
        ({**valid, "extra": 1}, "request body"),
        ({"save_id": imported["save_id"], "club_uid": 7, "side": "home"}, "request body"),
        ({**valid, "club_uid": "7"}, "request body"),
    ):
        response = client.post(f"/api/drafts/{draft['id']}/apply-roster", json=body, headers=headers)
        assert response.status_code == 400, body
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS, body
        assert error["code"] == "validation_failed", body
        assert message in error["message"], (body, error["message"])
    assert client.get(f"/api/drafts/{draft['id']}", headers=headers).json() == draft

    missing_undo = client.post("/api/drafts/missing/undo-roster", headers=headers)
    assert missing_undo.status_code == 404
    assert missing_undo.json()["error"]["code"] == "not_found"
    no_snapshot = client.post(f"/api/drafts/{draft['id']}/undo-roster", headers=headers)
    assert no_snapshot.status_code == 400
    assert "没有可撤销的阵容同步" in no_snapshot.json()["error"]["message"]


def test_http_save_import_openapi_contract(tmp_path: Path):
    app, _, _ = make_import_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in (
        "/api/saves/import",
        "/api/saves/{save_id}/squad",
        "/api/drafts/{draft_id}/apply-roster",
        "/api/drafts/{draft_id}/undo-roster",
    ):
        assert path in paths
    for path, operations in paths.items():
        if not path.startswith(("/api/saves", "/api/drafts")):
            continue
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            assert "422" not in operation["responses"], (path, method)
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            for status in ("400", "401"):
                reference = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
                assert reference.endswith("ErrorEnvelope"), (path, method, status)

    import_operation = paths["/api/saves/import"]["post"]
    assert import_operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SaveFileImportOutput"
    )
    assert import_operation["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )
    squad_operation = paths["/api/saves/{save_id}/squad"]["get"]
    assert squad_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SquadOutput"
    )
    assert squad_operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )
    parameters = {item["name"]: item["schema"] for item in squad_operation["parameters"]}
    assert parameters["club_uid"]["type"] == "integer"
    assert parameters["club_uid"]["minimum"] == 1
    apply_operation = paths["/api/drafts/{draft_id}/apply-roster"]["post"]
    assert apply_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "RosterApplyOutput"
    )
    for status in ("400", "401", "404"):
        reference = apply_operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert reference.endswith("ErrorEnvelope"), status
    assert apply_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "RosterApplyInput"
    )
    undo_operation = paths["/api/drafts/{draft_id}/undo-roster"]["post"]
    assert undo_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "RosterUndoOutput"
    )
    assert "requestBody" not in undo_operation

    components = document["components"]["schemas"]
    import_input = components["SaveFileImportInput"]
    assert set(import_input["properties"]) == {"source_path", "replace"}
    assert set(import_input["required"]) == {"source_path"}
    assert import_input["additionalProperties"] is False
    import_output = components["SaveFileImportOutput"]
    assert set(import_output["properties"]) == {"save_id", "status", "managed_clubs", "clubs"}
    assert set(import_output["required"]) == {"save_id", "status", "managed_clubs", "clubs"}
    applied_output = components["RosterAppliedOutput"]
    assert set(applied_output["properties"]) == {"starters", "substitutes"}
    apply_input = components["RosterApplyInput"]
    assert set(apply_input["properties"]) == {"save_id", "club_uid", "side", "scope"}
    assert set(apply_input["required"]) == {"save_id", "club_uid", "side", "scope"}
    assert apply_input["additionalProperties"] is False
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_http_save_import_service_is_injectable(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    default = app.state.save_import
    assert isinstance(default, SaveImportService)
    assert default.reader_factory is FmsaveReader

    class FakeService:
        def __init__(self):
            self.calls: list[tuple[Any, ...]] = []

        def import_save(self, source_path, replace=False):
            self.calls.append(("import_save", source_path, replace))
            return {
                "save_id": "fake-save",
                "status": "ready",
                "managed_clubs": [],
                "clubs": 0,
            }

        def get_squad(self, save_id, club_uid):
            self.calls.append(("get_squad", save_id, club_uid))
            return None

        def apply_roster(self, draft_id, save_id, club_uid, side, scope):
            self.calls.append(("apply_roster", draft_id, save_id, club_uid, side, scope))
            return None

        def undo_roster(self, draft_id):
            self.calls.append(("undo_roster", draft_id))
            return None

    fake = FakeService()
    second = create_app(settings, database, save_import_service=fake)
    client = TestClient(second)
    headers = auth(settings)
    created = client.post(
        "/api/saves/import",
        json={"source_path": "/tmp/save.fm"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["save_id"] == "fake-save"
    assert fake.calls == [("import_save", "/tmp/save.fm", False)]


def test_http_apply_roster_accepts_drafts_with_generated_placeholders(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    imported = import_save(client, headers, source_file(tmp_path))
    apply_body = {"save_id": imported["save_id"], "club_uid": 7, "side": "home", "scope": "starters"}

    starters_draft = create_placeholder_draft(client, headers)
    before = client.get(f"/api/drafts/{starters_draft['id']}", headers=headers).json()
    starters = client.post(
        f"/api/drafts/{starters_draft['id']}/apply-roster",
        json=apply_body,
        headers=headers,
    )
    assert starters.status_code == 200, starters.text
    assert starters.json()["applied"] == {"starters": 11, "substitutes": 0}
    fetched = client.get(f"/api/drafts/{starters_draft['id']}", headers=headers).json()
    home = fetched["scenario"]["teams"][0]
    assert [player["source_uid"] for player in home["players"][:STARTERS]] == SAVED_STARTERS
    assert all(player.get("generated") is True for player in home["players"][STARTERS:])
    assert home["captains"] == [3]
    assert home["takers"]["penalties"] == [3]
    assert fetched["scenario"]["teams"][1] == before["scenario"]["teams"][1]

    bench_draft = create_placeholder_draft(client, headers)
    bench_before = client.get(f"/api/drafts/{bench_draft['id']}", headers=headers).json()
    bench = client.post(
        f"/api/drafts/{bench_draft['id']}/apply-roster",
        json={**apply_body, "side": "away", "scope": "bench"},
        headers=headers,
    )
    assert bench.status_code == 200, bench.text
    assert bench.json()["applied"] == {"starters": 0, "substitutes": 12}
    fetched = client.get(f"/api/drafts/{bench_draft['id']}", headers=headers).json()
    away = fetched["scenario"]["teams"][1]
    assert away["players"][:STARTERS] == bench_before["scenario"]["teams"][1]["players"][:STARTERS]
    assert any(player.get("generated") is True for player in away["players"][:STARTERS])
    assert [player["source_uid"] for player in away["players"][STARTERS:]] == SAVED_SUBSTITUTES
    assert away["captains"] == bench_before["scenario"]["teams"][1]["captains"]

    both_draft = create_placeholder_draft(client, headers)
    both = client.post(
        f"/api/drafts/{both_draft['id']}/apply-roster",
        json={**apply_body, "scope": "both"},
        headers=headers,
    )
    assert both.status_code == 200, both.text
    assert both.json()["applied"] == {"starters": 11, "substitutes": 12}
    home = client.get(f"/api/drafts/{both_draft['id']}", headers=headers).json()["scenario"]["teams"][0]
    assert [player["source_uid"] for player in home["players"]] == SAVED_UIDS
    assert all(not player.get("generated") for player in home["players"])


def test_http_save_import_unreadable_source_is_validation_error(tmp_path: Path, monkeypatch):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    path = source_file(tmp_path)

    def denied(self, *args, **kwargs):
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(Path, "open", denied)
    response = client.post("/api/saves/import", json={"source_path": str(path)}, headers=headers)
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert "存档无法读取" in error["message"]
    assert app.state.saves.list(limit=256)["items"] == []


def test_http_save_import_missing_reader_dependency_is_validation_error(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)

    class MissingDependencyReader:
        def read_info(self):
            raise RuntimeError("未安装存档读取依赖 fmsave")

    service = SaveImportService(
        SavesService(SavesRepository(database)),
        DraftService(DraftRepository(database)),
        lambda _path: MissingDependencyReader(),
    )
    app = create_app(settings, database, save_import_service=service)
    client = TestClient(app)
    response = client.post(
        "/api/saves/import",
        json={"source_path": str(source_file(tmp_path))},
        headers=auth(settings),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
    assert "存档无法读取" in response.json()["error"]["message"]
    assert app.state.saves.list(limit=256)["items"] == []


def test_http_save_import_replace_preserves_leagues(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    path = source_file(tmp_path)
    imported = import_save(client, headers, path)
    payload = client.post(
        f"/api/saves/{imported['save_id']}/import",
        json={"leagues": {"英超": {"clubs": [1, 2]}}, "clubs": {}},
        headers=headers,
    )
    assert payload.status_code == 200, payload.text
    assert [row["league_key"] for row in app.state.saves.leagues(imported["save_id"])] == ["英超"]

    replaced = import_save(client, headers, path, replace=True)

    assert replaced["save_id"] == imported["save_id"]
    leagues = app.state.saves.leagues(imported["save_id"])
    assert [row["league_key"] for row in leagues] == ["英超"]
    assert leagues[0]["payload"] == {"clubs": [1, 2]}
    squad = client.get(
        f"/api/saves/{imported['save_id']}/squad",
        params={"club_uid": 7},
        headers=headers,
    )
    assert squad.status_code == 200


def test_http_save_import_cleans_quoted_and_padded_paths(tmp_path: Path):
    path = source_file(tmp_path)
    wrappers = (f'"{path}"', f"'{path}'", f'  "{path}"  ', f"  {path}  ")
    for index, raw in enumerate(wrappers):
        case_dir = tmp_path / f"case{index}"
        case_dir.mkdir()
        app, settings, _ = make_import_app(case_dir)
        client = TestClient(app)
        response = client.post("/api/saves/import", json={"source_path": raw}, headers=auth(settings))
        assert response.status_code == 201, raw
        record = app.state.saves.get(response.json()["save_id"])
        assert record["source_path"] == str(path)


def test_http_save_import_rejects_path_with_unpaired_quote(tmp_path: Path):
    app, settings, _ = make_import_app(tmp_path)
    client = TestClient(app)
    path = source_file(tmp_path)
    response = client.post(
        "/api/saves/import",
        json={"source_path": f'"{path}'},
        headers=auth(settings),
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert error["message"] == "存档文件不存在"
    assert error["retriable"] is False
    assert app.state.saves.list(limit=256)["items"] == []
