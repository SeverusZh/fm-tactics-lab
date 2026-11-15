"""阵型模板领域、应用与 HTTP 测试。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fm27lab.application.formations import FormationsService
from fm27lab.application.tactics_validation import TacticalValidator
from fm27lab.domain.formations import (
    FORMATIONS,
    POSITION_COORDINATES,
    formation,
    formation_ids,
    formations,
)
from fm27lab.domain.tactics import Catalog, validate_phases
from fm27lab.tests.test_http_drafts import auth, body, player
from fm27lab.tests.test_http_health import make_app

POSITION_MASKS = {
    "GK": 1,
    "DC": 16,
    "DCR": 16,
    "DCL": 16,
    "DR": 16,
    "DL": 16,
    "WBR": 16,
    "WBL": 16,
    "DMC": 32,
    "DMR": 32,
    "DML": 32,
    "MR": 32,
    "MCR": 32,
    "MC": 32,
    "MCL": 32,
    "ML": 32,
    "AMR": 32,
    "AMCR": 32,
    "AMC": 32,
    "AMCL": 32,
    "AML": 32,
    "ST": 128,
    "STR": 128,
    "STL": 128,
}


def template_roles() -> tuple[dict[str, int], dict[str, list[set[str]]]]:
    roles: dict[str, int] = {}
    eligibility: dict[str, list[set[str]]] = {}
    for item in formations():
        for phase, cells in enumerate(item.phases):
            for cell in cells:
                roles[cell.role] = phase
                slots = eligibility.setdefault(cell.position, [set(), set()])
                slots[phase].add(cell.role)
    return roles, eligibility


def catalog_document(context: bool = False) -> dict[str, Any]:
    roles, eligibility = template_roles()
    document: dict[str, Any] = {
        "positions": [
            {
                "id": position,
                "mask": POSITION_MASKS[position],
                "x": POSITION_COORDINATES[position][0],
                "y": POSITION_COORDINATES[position][1],
            }
            for position in sorted(eligibility)
        ],
        "roles": [
            {"id": role, "label": role, "phase": phase, "flags": "0"}
            for role, phase in sorted(roles.items(), key=lambda item: (item[1], item[0]))
        ],
        "duties": ["0", "2097152"],
        "role_eligibility": {
            position: [sorted(slots[0]), sorted(slots[1])]
            for position, slots in sorted(eligibility.items())
        },
        "player_instructions": [
            {"id": 14, "label": "盯防方式", "options": [{"id": 0}, {"id": 34}, {"id": 35}]},
            {"id": 8, "label": "压迫强度", "options": [{"id": 0}, {"id": 1}]},
        ],
        "team_instructions": [],
        "mentalities": [],
    }
    if context:
        document["role_eligibility_context"] = {
            bucket: copy.deepcopy(document["role_eligibility"])
            for bucket in ("0:0", "0:1", "3:0", "3:1")
        }
        document["role_eligibility_context"]["3:0"]["DR"] = [["WingBack"], ["OPWingBack"]]
    return document


def scenario(players: bool = True) -> dict[str, Any]:
    rosters = [player(100 + index) for index in range(16)] if players else []
    team = {
        "name": "Home",
        "players": rosters,
        "roster_size": len(rosters),
        "lineup": list(range(11)),
        "captains": [],
        "takers": {},
        "setpieces": {"role_priorities": {}},
    }
    return {"schema": 3, "teams": [copy.deepcopy(team), copy.deepcopy(team)]}


class _Drafts:
    def __init__(self, scenarios: dict[str, Any], validator: Any = None):
        self.scenarios = scenarios
        self.validator = validator

    def get(self, draft_id: str) -> dict[str, Any] | None:
        value = self.scenarios.get(draft_id)
        if value is None:
            return None
        return {"id": draft_id, "scenario": copy.deepcopy(value)}


class _CatalogRepository:
    def __init__(self, document: Any):
        self.document = document

    def load_document(self) -> Any:
        if isinstance(self.document, Exception):
            raise self.document
        return copy.deepcopy(self.document)


class _Validator:
    def __init__(self, error: str | None = None):
        self.error = error
        self.calls: list[Any] = []

    def validate(self, value: Any) -> None:
        self.calls.append(value)
        if self.error:
            raise ValueError(self.error)


_DEFAULT = object()


def service(document: Any = _DEFAULT, value: Any = None, validator: Any = None) -> FormationsService:
    drafts = _Drafts({"draft-1": value if value is not None else scenario()}, validator)
    resolved = catalog_document() if document is _DEFAULT else document
    return FormationsService(drafts, _CatalogRepository(resolved))


def test_builtin_formations_cover_six_templates():
    assert formation_ids() == ("4-4-2", "4-2-3-1", "4-3-3", "3-5-2", "5-3-2", "4-1-4-1")
    assert [item.id for item in formations()] == list(formation_ids())
    assert len(FORMATIONS) == 6


def test_each_formation_fills_two_phases_with_eleven_unique_slots():
    for item in formations():
        assert len(item.phases) == 2
        for cells in item.phases:
            assert len(cells) == 11
            assert len({cell.position for cell in cells}) == 11
            for cell in cells:
                assert cell.position in POSITION_COORDINATES
                assert cell.role
                assert 0 <= cell.x <= 100 and 0 <= cell.y <= 100
        assert item.phases[0][0].position == "GK"
        assert item.phases[1][0].position == "GK"
        assert {cell.role for cell in item.phases[1]} != {cell.role for cell in item.phases[0]}


def test_formation_lookup_returns_template_or_none():
    assert formation("4-2-3-1") is FORMATIONS[1]
    assert formation("custom") is None


def test_service_lists_templates_with_editing_metadata():
    value = service().list()
    assert [item["id"] for item in value["formations"]] == list(formation_ids())
    first = value["formations"][0]
    assert len(first["phases"]) == 2
    assert len(first["phases"][0]) == 11
    assert set(first["phases"][0][0]) == {"position", "role", "x", "y"}
    editing = value["editing"]
    assert editing["duties"] == ["0", "2097152"]
    assert [group["id"] for group in editing["player_instructions"]] == [14, 8]
    assert "DR" in editing["role_eligibility"]
    assert {"id": "DR", "mask": 16} in editing["positions"]
    assert editing["role_eligibility_context"] is None


def test_service_returns_missing_editing_when_catalog_unavailable():
    value = service(document=ValueError("目录文件无效")).list()
    assert value["editing"] is None


def test_service_applies_template_and_assigns_lineup_by_familiarity():
    applied = service().apply("draft-1", "4-4-2")
    assert applied is not None
    assert applied["formation_id"] == "4-4-2"
    assert applied["notes"] == []
    teams = applied["scenario"]["teams"]
    assert len(teams) == 2
    for team in teams:
        cells = team["phases"][0]
        assert [cell["position"] for cell in cells] == [
            cell.position for cell in FORMATIONS[0].phases[0]
        ]
        assert [cell["role"] for cell in cells] == [
            cell.role for cell in FORMATIONS[0].phases[0]
        ]
        assert all(cell["duty"] == "0" for cell in cells)
        assert all(cell["instructions"] == {"8": 0, "14": 0} for cell in cells)
        assert all(cell["target_player"] == 255 for cell in cells)
        assert all(cell["target_position"] == 0 for cell in cells)
        assert len(team["phases"][1]) == 11
        assert team["lineup"][0] == 0
        assert sorted(team["lineup"]) == list(range(11))


def test_service_keeps_existing_cell_fields_when_not_overwriting():
    first = service().apply("draft-1", "4-4-2")
    edited = copy.deepcopy(first["scenario"])
    for team in edited["teams"]:
        cell = team["phases"][0][1]
        cell["duty"] = "2097152"
        cell["instructions"] = {"14": 35}
        cell["target_player"] = 3
        cell["target_position"] = 128
    applied = service(value=edited).apply("draft-1", "4-4-2", scenario=edited)
    for team in applied["scenario"]["teams"]:
        cell = team["phases"][0][1]
        assert cell["position"] == "DR"
        assert cell["duty"] == "2097152"
        assert cell["instructions"] == {"14": 35}
        assert cell["target_player"] == 3
        assert cell["target_position"] == 128


def test_service_overwrite_resets_optional_cell_fields():
    first = service().apply("draft-1", "4-4-2")
    edited = copy.deepcopy(first["scenario"])
    for team in edited["teams"]:
        cell = team["phases"][0][1]
        cell["duty"] = "2097152"
        cell["instructions"] = {"14": 35}
        cell["target_player"] = 3
        cell["target_position"] = 128
    applied = service(value=edited).apply("draft-1", "4-4-2", overwrite=True, scenario=edited)
    for team in applied["scenario"]["teams"]:
        cell = team["phases"][0][1]
        assert cell["duty"] == "0"
        assert cell["instructions"] == {"8": 0, "14": 0}
        assert cell["target_player"] == 255
        assert cell["target_position"] == 0


def test_service_reports_missing_players_and_fills_positions_in_order():
    applied = service(value=scenario(players=False)).apply("draft-1", "4-3-3")
    assert "缺少球员名单，按位置顺序填充" in applied["notes"][0]
    assert applied["notes"][0].startswith("主队：")
    assert applied["notes"][1].startswith("客队：")
    for team in applied["scenario"]["teams"]:
        assert team["lineup"] == list(range(11))


def test_service_uses_role_eligibility_context_when_present():
    applied = service(document=catalog_document(context=True)).apply("draft-1", "4-4-2")
    for team in applied["scenario"]["teams"]:
        assert team["phases"][0][1]["role"] == "WingBack"
        assert team["phases"][1][1]["role"] == "OPWingBack"


def test_service_falls_back_to_role_when_template_role_is_not_eligible():
    document = catalog_document()
    document["role_eligibility"]["DR"] = [["WingBack"], ["OPWingBack"]]
    applied = service(document=document).apply("draft-1", "4-4-2")
    for team in applied["scenario"]["teams"]:
        assert team["phases"][0][1]["role"] == "WingBack"


def test_service_keeps_template_role_without_catalog():
    applied = service(document=ValueError("目录文件无效")).apply("draft-1", "4-4-2")
    for team in applied["scenario"]["teams"]:
        assert team["phases"][0][1]["role"] == "FullBack"


def test_service_returns_none_for_unknown_draft():
    assert service().apply("missing", "4-4-2") is None


def test_service_rejects_unknown_template():
    with pytest.raises(ValueError, match="阵型模板不存在"):
        service().apply("draft-1", "custom")


def test_service_propagates_validation_errors():
    applied = service(validator=_Validator("球队缺少门将"))
    with pytest.raises(ValueError, match="球队缺少门将"):
        applied.apply("draft-1", "4-4-2")


def test_service_rejects_malformed_scenario():
    with pytest.raises(ValueError, match="场景必须包含两支球队"):
        service(value={"schema": 3, "teams": []}).apply("draft-1", "4-4-2")


def test_service_preview_passes_domain_validation_with_instruction_groups():
    document = catalog_document()
    validator = TacticalValidator(_CatalogRepository(document))
    applied = service(document=document, validator=validator).apply("draft-1", "4-4-2")
    assert applied is not None
    for team in applied["scenario"]["teams"]:
        for cells in team["phases"]:
            for cell in cells:
                assert set(cell["instructions"]) == {"8", "14"}
                assert cell["instructions"]["8"] in (0, 1)
                assert cell["instructions"]["14"] in (0, 34, 35)
        validate_phases(team["phases"], Catalog.from_mapping(document))


def test_service_keeps_edited_cell_values_through_domain_normalization():
    document = catalog_document()
    validator = TacticalValidator(_CatalogRepository(document))
    first = service(document=document, validator=validator).apply("draft-1", "4-4-2")
    edited = copy.deepcopy(first["scenario"])
    for team in edited["teams"]:
        cell = team["phases"][0][1]
        cell["duty"] = "2097152"
        cell["instructions"] = {"14": 35}
        cell["target_player"] = 3
        cell["target_position"] = 128
    applied = service(document=document, value=edited, validator=validator).apply(
        "draft-1", "4-4-2", scenario=edited
    )
    assert applied is not None
    for team in applied["scenario"]["teams"]:
        cell = team["phases"][0][1]
        assert cell["duty"] == "2097152"
        assert cell["target_player"] == 3
        assert cell["target_position"] == 128
        assert cell["instructions"]["14"] == 35
        assert set(cell["instructions"]) == {"8", "14"}
        validate_phases(team["phases"], Catalog.from_mapping(document))


def test_service_prefers_goalkeeper_and_position_familiarity():
    value = scenario()
    for index, team in enumerate(value["teams"]):
        roster = [player(200 + index * 20 + slot) for slot in range(16)]
        for item in roster:
            item["attributes"] = [0] * 69
        roster[5]["attributes"][0] = 20
        roster[7]["attributes"][3] = 20
        team["players"] = roster
    applied = service(value=value).apply("draft-1", "4-4-2")
    for team in applied["scenario"]["teams"]:
        assert team["lineup"][0] == 5
        assert team["lineup"][2] == 7


def test_service_keeps_other_draft_fields_untouched():
    source = scenario()
    source["extra"] = {"note": "keep"}
    applied = service(value=source).apply("draft-1", "5-3-2")
    assert applied["scenario"]["extra"] == {"note": "keep"}


def write_catalog(settings: Any, document: dict[str, Any]) -> None:
    path = settings.data_dir / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def create_draft(client: TestClient, settings: Any) -> dict[str, Any]:
    created = client.post("/api/drafts", json=body(), headers=auth(settings))
    assert created.status_code == 201
    return created.json()


def test_http_formations_lists_templates_and_editing_options(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    response = client.get("/api/formations", headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["formations"]] == list(formation_ids())
    assert payload["editing"]["duties"] == ["0", "2097152"]
    assert payload["editing"]["player_instructions"][0]["id"] == 14


def test_http_formations_lists_templates_without_catalog(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.get("/api/formations", headers=auth(settings))
    assert response.status_code == 200
    assert len(response.json()["formations"]) == 6
    assert response.json()["editing"] is None


def test_http_draft_formation_applies_template_without_persisting(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    draft = create_draft(client, settings)
    response = client.post(
        f"/api/drafts/{draft['id']}/formation",
        json={"formation_id": "4-2-3-1"},
        headers=auth(settings),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["formation_id"] == "4-2-3-1"
    assert payload["notes"] == []
    scenario_value = payload["scenario"]
    assert [cell["position"] for cell in scenario_value["teams"][0]["phases"][0]][:3] == [
        "GK",
        "DR",
        "DCR",
    ]
    fetched = client.get(f"/api/drafts/{draft['id']}", headers=auth(settings)).json()
    assert "phases" not in fetched["scenario"]["teams"][0]
    updated = client.patch(
        f"/api/drafts/{draft['id']}",
        json={"scenario": scenario_value},
        headers=auth(settings),
    )
    assert updated.status_code == 200
    stored = updated.json()["scenario"]["teams"][0]
    assert len(stored["phases"]) == 2
    assert len(stored["phases"][0]) == 11


def test_http_draft_formation_accepts_scenario_override(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    draft = create_draft(client, settings)
    override = draft["scenario"]
    response = client.post(
        f"/api/drafts/{draft['id']}/formation",
        json={"formation_id": "3-5-2", "overwrite": True, "scenario": override},
        headers=auth(settings),
    )
    assert response.status_code == 200
    assert response.json()["scenario"]["teams"][0]["phases"][0][0]["position"] == "GK"


def test_http_draft_formation_returns_404_for_unknown_draft(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    response = client.post(
        "/api/drafts/missing/formation",
        json={"formation_id": "4-4-2"},
        headers=auth(settings),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_http_draft_formation_returns_400_for_unknown_template(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    draft = create_draft(client, settings)
    response = client.post(
        f"/api/drafts/{draft['id']}/formation",
        json={"formation_id": "custom"},
        headers=auth(settings),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
    assert "阵型模板不存在" in response.json()["error"]["message"]


def test_http_draft_formation_rejects_unknown_body_field(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_catalog(settings, catalog_document())
    client = TestClient(app)
    draft = create_draft(client, settings)
    response = client.post(
        f"/api/drafts/{draft['id']}/formation",
        json={"formation_id": "4-4-2", "bogus": 1},
        headers=auth(settings),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"


def test_http_formations_require_token(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/formations").status_code == 401
    assert client.post("/api/drafts/x/formation", json={"formation_id": "4-4-2"}).status_code == 401


def test_http_formations_openapi_documents_both_operations(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    schema = app.openapi()
    listing = schema["paths"]["/api/formations"]["get"]
    applying = schema["paths"]["/api/drafts/{draft_id}/formation"]["post"]
    assert "422" not in listing["responses"]
    assert "422" not in applying["responses"]
    assert "400" in applying["responses"]
    assert "404" in applying["responses"]
