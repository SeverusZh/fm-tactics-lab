"""内置阵型模板。"""

from __future__ import annotations

from dataclasses import dataclass

POSITION_COORDINATES: dict[str, tuple[float, float]] = {
    "GK": (50, 92),
    "DC": (50, 78),
    "DCR": (67, 78),
    "DCL": (33, 78),
    "DR": (86, 76),
    "DL": (14, 76),
    "WBR": (91, 62),
    "WBL": (9, 62),
    "DMC": (50, 61),
    "DMR": (67, 61),
    "DML": (33, 61),
    "MR": (89, 45),
    "MCR": (67, 45),
    "MC": (50, 45),
    "MCL": (33, 45),
    "ML": (11, 45),
    "AMR": (88, 28),
    "AMCR": (67, 28),
    "AMC": (50, 28),
    "AMCL": (33, 28),
    "AML": (12, 28),
    "ST": (50, 12),
    "STR": (67, 12),
    "STL": (33, 12),
}


@dataclass(frozen=True, slots=True)
class FormationCell:
    position: str
    role: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Formation:
    id: str
    name: str
    phases: tuple[tuple[FormationCell, ...], ...]


def _formation(identifier: str, slots: tuple[tuple[str, str, str], ...]) -> Formation:
    offense = tuple(
        FormationCell(position, offense_role, *POSITION_COORDINATES[position])
        for position, offense_role, _defense_role in slots
    )
    defense = tuple(
        FormationCell(position, defense_role, *POSITION_COORDINATES[position])
        for position, _offense_role, defense_role in slots
    )
    return Formation(identifier, identifier, (offense, defense))


FORMATIONS: tuple[Formation, ...] = (
    _formation(
        "4-4-2",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("DR", "FullBack", "OPFullBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DL", "FullBack", "OPFullBack"),
            ("MR", "Winger", "OPWideMidfielder"),
            ("MCR", "CentralMidfielder", "OPCentralMidfielder"),
            ("MCL", "CentralMidfielder", "OPCentralMidfielder"),
            ("ML", "Winger", "OPWideMidfielder"),
            ("STR", "CentreForward", "OPCentreForward"),
            ("STL", "CentreForward", "OPCentreForward"),
        ),
    ),
    _formation(
        "4-2-3-1",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("DR", "FullBack", "OPFullBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DL", "FullBack", "OPFullBack"),
            ("DMR", "DefensiveMidfielder", "OPDefensiveMidfielder"),
            ("DML", "DefensiveMidfielder", "OPDefensiveMidfielder"),
            ("AMR", "Winger", "OPWinger"),
            ("AMC", "AttackingMidfielder", "OPAttackingMidfielder"),
            ("AML", "Winger", "OPWinger"),
            ("ST", "CentreForward", "OPCentreForward"),
        ),
    ),
    _formation(
        "4-3-3",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("DR", "FullBack", "OPFullBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DL", "FullBack", "OPFullBack"),
            ("MCL", "CentralMidfielder", "OPCentralMidfielder"),
            ("MC", "CentralMidfielder", "OPCentralMidfielder"),
            ("MCR", "CentralMidfielder", "OPCentralMidfielder"),
            ("AML", "Winger", "OPWinger"),
            ("ST", "CentreForward", "OPCentreForward"),
            ("AMR", "Winger", "OPWinger"),
        ),
    ),
    _formation(
        "3-5-2",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DC", "CentreBack", "OPCentreBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("WBL", "WingBack", "OPWingBack"),
            ("MCL", "CentralMidfielder", "OPCentralMidfielder"),
            ("MC", "CentralMidfielder", "OPCentralMidfielder"),
            ("MCR", "CentralMidfielder", "OPCentralMidfielder"),
            ("WBR", "WingBack", "OPWingBack"),
            ("STR", "CentreForward", "OPCentreForward"),
            ("STL", "CentreForward", "OPCentreForward"),
        ),
    ),
    _formation(
        "5-3-2",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("WBL", "WingBack", "OPWingBack"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DC", "CentreBack", "OPCentreBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("WBR", "WingBack", "OPWingBack"),
            ("MCL", "CentralMidfielder", "OPCentralMidfielder"),
            ("MC", "CentralMidfielder", "OPCentralMidfielder"),
            ("MCR", "CentralMidfielder", "OPCentralMidfielder"),
            ("STR", "CentreForward", "OPCentreForward"),
            ("STL", "CentreForward", "OPCentreForward"),
        ),
    ),
    _formation(
        "4-1-4-1",
        (
            ("GK", "Goalkeeper", "OPGoalkeeper"),
            ("DR", "FullBack", "OPFullBack"),
            ("DCR", "CentreBack", "OPCentreBack"),
            ("DCL", "CentreBack", "OPCentreBack"),
            ("DL", "FullBack", "OPFullBack"),
            ("DMC", "DefensiveMidfielder", "OPDefensiveMidfielder"),
            ("ML", "Winger", "OPWideMidfielder"),
            ("MCL", "CentralMidfielder", "OPCentralMidfielder"),
            ("MCR", "CentralMidfielder", "OPCentralMidfielder"),
            ("MR", "Winger", "OPWideMidfielder"),
            ("ST", "CentreForward", "OPCentreForward"),
        ),
    ),
)


def formations() -> tuple[Formation, ...]:
    return FORMATIONS


def formation(identifier: str) -> Formation | None:
    for item in FORMATIONS:
        if item.id == identifier:
            return item
    return None


def formation_ids() -> tuple[str, ...]:
    return tuple(item.id for item in FORMATIONS)
