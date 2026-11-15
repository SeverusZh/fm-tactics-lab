"""应用层战术校验接线测试。"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from fm27lab.application.tactics_validation import TacticalValidator

ELIGIBILITY_ERROR = "战术角色不具备该位置资格"


def catalog_document(context: bool = False) -> dict[str, Any]:
    document: dict[str, Any] = {
        "positions": [
            {"id": "GK", "mask": 1, "x": 50, "y": 92},
            {"id": "DC", "mask": 16, "x": 50, "y": 76},
            {"id": "ST", "mask": 128, "x": 50, "y": 20},
        ],
        "roles": [
            {"id": "Goalkeeper", "label": "门将", "phase": 0, "flags": "1"},
            {"id": "CentreBack", "label": "中后卫", "phase": 0, "flags": "2"},
            {"id": "Sweeper", "label": "清道夫", "phase": 0, "flags": "5"},
            {"id": "Striker", "label": "中锋", "phase": 0, "flags": "4"},
            {"id": "OPGoalkeeper", "label": "防守门将", "phase": 1, "flags": "8"},
            {"id": "OPCentreBack", "label": "防守中卫", "phase": 1, "flags": "16"},
            {"id": "OPStriker", "label": "防守中锋", "phase": 1, "flags": "32"},
        ],
        "duties": ["0", "2097152"],
        "role_eligibility": {
            "GK": [["Goalkeeper"], ["OPGoalkeeper"]],
            "DC": [["CentreBack", "Sweeper"], ["OPCentreBack"]],
            "ST": [["Striker"], ["OPStriker"]],
        },
    }
    if context:
        document["role_eligibility_context"] = {
            f"{defenders}:{holding}": {
                "GK": [["Goalkeeper"], ["OPGoalkeeper"]],
                "DC": [
                    ["CentreBack", "Sweeper"] if defenders == 0 and holding == 0 else ["CentreBack"],
                    ["OPCentreBack"],
                ],
                "ST": [["Striker"], ["OPStriker"]],
            }
            for defenders in (0, 3)
            for holding in (0, 1)
        }
    return document


def cell(position: str = "DC", role: str = "CentreBack", duty: str = "0", **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "position": position,
        "role": role,
        "duty": duty,
        "instructions": {},
        "target_player": 255,
        "target_position": 0,
    }
    value.update(extra)
    return value


def phases() -> list[list[dict[str, Any]]]:
    first = [cell() for _ in range(11)]
    second = [cell(role="OPCentreBack") for _ in range(11)]
    return [first, second]


def scenario(plan: Any = None, away_plan: Any = None) -> dict[str, Any]:
    home = phases() if plan is None else plan
    away = phases() if away_plan is None else away_plan
    return {"teams": [{"phases": copy.deepcopy(home)}, {"phases": copy.deepcopy(away)}]}


def invalid_plan() -> list[list[dict[str, Any]]]:
    plan = phases()
    plan[0][0]["role"] = "Striker"
    return plan


class StubCatalog:
    def __init__(self, document: Any = None, error: Exception | None = None) -> None:
        self.document = document
        self.error = error
        self.loads = 0

    def load_document(self) -> Any:
        self.loads += 1
        if self.error is not None:
            raise self.error
        return self.document


def test_valid_document_and_tactic_plan_pass():
    validator = TacticalValidator(StubCatalog(catalog_document()))
    assert validator.validate(scenario()) is None


def test_missing_catalog_skips_validation():
    repository = StubCatalog(None)
    TacticalValidator(repository).validate(scenario(invalid_plan()))
    assert repository.loads == 1


def test_corrupt_catalog_skips_validation():
    repository = StubCatalog(error=ValueError("目录文件无效"))
    TacticalValidator(repository).validate(scenario(invalid_plan()))
    assert repository.loads == 1


def test_catalog_without_validation_sections_skips_validation():
    document = catalog_document()
    document.pop("duties")
    TacticalValidator(StubCatalog(document)).validate(scenario(invalid_plan()))


def test_ineligible_role_is_rejected():
    validator = TacticalValidator(StubCatalog(catalog_document()))
    with pytest.raises(ValueError, match="资格"):
        validator.validate(scenario(invalid_plan()))


def test_role_phase_mismatch_is_rejected():
    plan = phases()
    plan[0][0] = cell(role="OPCentreBack")
    with pytest.raises(ValueError, match="阶段"):
        TacticalValidator(StubCatalog(catalog_document())).validate(scenario(plan))


def test_invalid_duty_is_rejected():
    plan = phases()
    plan[1][0]["duty"] = "999"
    with pytest.raises(ValueError, match="职责"):
        TacticalValidator(StubCatalog(catalog_document())).validate(scenario(plan))


def test_wrong_phase_count_is_rejected():
    plan = phases()[:1]
    with pytest.raises(ValueError, match="两个阶段"):
        TacticalValidator(StubCatalog(catalog_document())).validate(scenario(plan))


def test_wrong_slot_count_is_rejected():
    plan = phases()
    plan[0] = plan[0][:10]
    with pytest.raises(ValueError, match="11"):
        TacticalValidator(StubCatalog(catalog_document())).validate(scenario(plan))


def test_unknown_position_is_rejected():
    plan = phases()
    plan[0][0]["position"] = "XX"
    with pytest.raises(ValueError, match="位置"):
        TacticalValidator(StubCatalog(catalog_document())).validate(scenario(plan))


def test_points_without_phases_are_skipped():
    validator = TacticalValidator(StubCatalog(catalog_document()))
    assert validator.validate({"teams": [{}, {"players": []}]}) is None


def test_both_teams_are_validated():
    validator = TacticalValidator(StubCatalog(catalog_document()))
    with pytest.raises(ValueError, match="职责"):
        validator.validate(scenario(away_plan=invalid_duty_plan()))
    with pytest.raises(ValueError, match="资格"):
        validator.validate(scenario(invalid_plan(), away_plan=phases()))


def invalid_duty_plan() -> list[list[dict[str, Any]]]:
    plan = phases()
    plan[1][0]["duty"] = "5"
    return plan


def test_context_bucket_changes_eligibility():
    validator = TacticalValidator(StubCatalog(catalog_document(context=True)))
    two_sweepers = [cell(position="GK", role="Goalkeeper") for _ in range(9)] + [
        cell(role="Sweeper") for _ in range(2)
    ]
    second = [cell(position="GK", role="OPGoalkeeper") for _ in range(11)]
    assert validator.validate(scenario([two_sweepers, second])) is None
    three_sweepers = [cell(position="GK", role="Goalkeeper") for _ in range(8)] + [
        cell(role="Sweeper") for _ in range(3)
    ]
    with pytest.raises(ValueError, match="资格"):
        validator.validate(scenario([three_sweepers, second]))


def test_validation_does_not_mutate_input():
    value = scenario()
    value["teams"][1]["phases"][0][0]["duty"] = "2097152"
    at_start = copy.deepcopy(value)
    TacticalValidator(StubCatalog(catalog_document())).validate(value)
    assert value == at_start
    assert value["teams"][0]["phases"][0][0]["duty"] == "0"
    assert value["teams"][1]["phases"][0][0]["duty"] == "2097152"
