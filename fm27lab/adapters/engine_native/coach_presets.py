"""原装教练预设导出、教练偏好读回与阵型匹配。"""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.tactic_file import TacticCell, TacticPlan, execute_host

PRESET_EXPORT_ENVIRONMENT = "FM27_COACH_PRESET_EXPORT"
STAFF_FRAGMENT_ENVIRONMENT = "FM27_STAFF_FRAGMENT_DIRECTORY"
EXPORT_COMPLETE_EVENT = "coach_preset_export_complete"
STYLE_EVENT = "coach_preset_style"
FORMATION_EVENT = "coach_preset_formation"
TEMPLATE_EVENT = "installed_tactic_preset"
STAFF_EVENT = "staff_body_read"
PHASE_COUNT = 2
SLOTS = 11
STYLE_INDEX = 20
CODES_INDEX = 11

__all__ = [
    "PresetCatalog",
    "PresetTemplate",
    "PresetVariant",
    "StaffPreference",
    "decode_staff",
    "export_catalog",
    "variants",
]


class CoachPresetError(ValueError):
    """教练预设无法完整导出或未通过原生读回。"""


@dataclass(frozen=True, slots=True)
class PresetTemplate:
    index: int
    style_code: int
    name: str
    plan: TacticPlan


@dataclass(frozen=True, slots=True)
class PresetCatalog:
    styles: Mapping[int, int]
    formations: Mapping[int, tuple[int, ...]]
    templates: tuple[PresetTemplate, ...]

    def by_style(self, style: int) -> tuple[PresetTemplate, ...]:
        code = self.styles.get(style)
        if code is None:
            raise CoachPresetError("该教练未存储可用的预设风格")
        return tuple(item for item in self.templates if item.style_code == code)


@dataclass(frozen=True, slots=True)
class PresetVariant:
    variant: int
    formation_code: int
    template: PresetTemplate
    exact: bool
    position_difference: int
    policy: str


@dataclass(frozen=True, slots=True)
class StaffPreference:
    selector: int
    style: int
    primary: int
    secondary: int
    profile_hex: str
    codes_hex: str


def export_catalog(
    *,
    engine_root: Path | None,
    game_root: Path | None,
    executable: Path | None = None,
    timeout_seconds: float = 120.0,
) -> PresetCatalog:
    """调用原生宿主导出安装目录中的原装预设与阵型编码。"""
    run = execute_host(
        engine_root=engine_root,
        game_root=game_root,
        executable=executable,
        timeout_seconds=timeout_seconds,
        environment={PRESET_EXPORT_ENVIRONMENT: "1"},
    )
    if not run.events:
        raise CoachPresetError("原生宿主未返回事件，请确认引擎与游戏版本一致")
    complete = _one(run.events, EXPORT_COMPLETE_EVENT)
    try:
        styles = {
            int(event["id"]): int(event["style_code"])
            for event in run.events
            if event.get("event") == STYLE_EVENT
        }
        formations = {
            int(event["code"]): tuple(int(item) for item in event.get("positions") or ())
            for event in run.events
            if event.get("event") == FORMATION_EVENT
        }
        templates = tuple(
            _template(event) for event in run.events if event.get("event") == TEMPLATE_EVENT
        )
    except CoachPresetError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CoachPresetError("原装预设事件字段无效") from error
    if int(complete.get("styles", -1)) != len(styles):
        raise CoachPresetError("原装预设风格目录未通过完整读取核对")
    if int(complete.get("formations", -1)) != len(formations):
        raise CoachPresetError("原装预设阵型目录未通过完整读取核对")
    if int(complete.get("templates", -1)) != len(templates) or not templates:
        raise CoachPresetError("原装预设模板目录未通过完整读取核对")
    if any(len(item.plan.phases) != PHASE_COUNT for item in templates):
        raise CoachPresetError("原装预设双阶段不完整")
    return PresetCatalog(styles=styles, formations=formations, templates=templates)


def decode_staff(
    fragments: Mapping[int, bytes],
    *,
    engine_root: Path | None,
    game_root: Path | None,
    executable: Path | None = None,
    timeout_seconds: float = 120.0,
) -> dict[int, StaffPreference]:
    """把偏好片段交给原版读取器，返回风格与主次阵型。"""
    if not fragments:
        return {}
    with tempfile.TemporaryDirectory(prefix="fm27lab-staff-") as directory:
        root = Path(directory)
        for selector, payload in fragments.items():
            (root / f"{int(selector)}.bin").write_bytes(bytes(payload))
        run = execute_host(
            engine_root=engine_root,
            game_root=game_root,
            executable=executable,
            timeout_seconds=timeout_seconds,
            environment={STAFF_FRAGMENT_ENVIRONMENT: str(root)},
        )
    decoded: dict[int, StaffPreference] = {}
    for event in run.events:
        if event.get("event") != STAFF_EVENT:
            continue
        selector = _int(event.get("selector"), "教练标识")
        if event.get("accepted") is not True or event.get("error"):
            raise CoachPresetError(f"教练偏好未通过原版读回：{selector}")
        try:
            raw = bytes.fromhex(str(event.get("native_d4_to_f4_hex") or ""))
        except ValueError as error:
            raise CoachPresetError(f"教练偏好读回格式无效：{selector}") from error
        if len(raw) < STYLE_INDEX + 1:
            raise CoachPresetError(f"教练偏好读回长度不足：{selector}")
        profile = str(event.get("profile_hex") or "")
        if len(profile) != 104:
            raise CoachPresetError(f"教练偏好画像长度不足：{selector}")
        decoded[selector] = StaffPreference(
            selector=selector,
            style=raw[STYLE_INDEX],
            primary=raw[CODES_INDEX],
            secondary=raw[CODES_INDEX + 1],
            profile_hex=profile,
            codes_hex=raw[CODES_INDEX : CODES_INDEX + 8].hex(),
        )
    if set(decoded) != {int(selector) for selector in fragments}:
        raise CoachPresetError("教练偏好读回缺少条目")
    return decoded


def variants(
    catalog: PresetCatalog,
    *,
    style: int,
    primary: int,
    secondary: int,
) -> tuple[PresetVariant, ...]:
    """按风格、主偏好阵型、次偏好阵型匹配最多两套原装预设。"""
    candidates = catalog.by_style(style)
    primary_positions = catalog.formations.get(primary)
    if primary_positions is None:
        raise CoachPresetError("该教练主偏好阵型尚未映射")
    secondary_positions = catalog.formations.get(secondary)
    first, difference = _rank(candidates, primary_positions, secondary_positions)
    match = {
        "primary_code": primary,
        "secondary_code": secondary,
        "primary_positions": list(primary_positions),
        "secondary_positions": list(secondary_positions) if secondary_positions else None,
        "primary_exact": difference == 0,
        "secondary_exact": False,
        "position_difference_counts": [difference, 0],
        "selection_policy": "same_style_then_primary_shape_then_secondary_shape_then_stable_index",
    }
    result = [
        PresetVariant(
            variant=1,
            formation_code=primary,
            template=first,
            exact=difference == 0,
            position_difference=difference,
            policy=str(match["selection_policy"]),
        )
    ]
    if not secondary_positions or secondary == primary:
        return tuple(result)
    second, second_difference = _rank(candidates, secondary_positions, primary_positions)
    if second.index == first.index:
        ordered = sorted(
            candidates,
            key=lambda item: (
                _distance(secondary_positions, _positions(item.plan, 0)),
                item.index,
            ),
        )
        second = next((item for item in ordered if item.index != first.index), None)
        if second is None:
            return tuple(result)
        second_difference = _distance(secondary_positions, _positions(second.plan, 0))
    result.append(
        PresetVariant(
            variant=2,
            formation_code=secondary,
            template=second,
            exact=second_difference == 0,
            position_difference=second_difference,
            policy="same_style_then_secondary_shape_then_primary_phase",
        )
    )
    return tuple(result)


def _rank(
    candidates: Sequence[PresetTemplate],
    shape: Sequence[int],
    other: Sequence[int] | None,
) -> tuple[PresetTemplate, int]:
    def key(item: PresetTemplate) -> tuple[int, int, int]:
        first = _distance(shape, _positions(item.plan, 0))
        second = _distance(other, _positions(item.plan, 1)) if other is not None else 0
        return (first, second, item.index)

    best = min(candidates, key=key)
    return best, key(best)[0]


def _distance(shape: Sequence[int], positions: Sequence[int]) -> int:
    return sum((Counter(shape) - Counter(positions)).values())


def _positions(plan: TacticPlan, phase: int) -> tuple[int, ...]:
    return tuple(cell.position for cell in plan.phases[phase])


def _template(event: Mapping[str, Any]) -> PresetTemplate:
    name = bytes.fromhex(str(event.get("name_utf8_hex") or "")).decode("utf8", errors="replace")
    team_bits = _team_bits(event.get("team_bits"))
    mapping = tuple(int(item) for item in event.get("mapping") or ())
    phases = event.get("phases")
    if not isinstance(phases, list) or len(phases) != PHASE_COUNT:
        raise CoachPresetError("原装预设双阶段不完整")
    cells: list[tuple[TacticCell, ...]] = []
    for phase in phases:
        if not isinstance(phase, list) or len(phase) != SLOTS:
            raise CoachPresetError("原装预设阶段必须包含 11 个位置")
        cells.append(
            tuple(
                TacticCell(
                    position=int(cell["position"]),
                    role_flags=_int(cell.get("role_flags"), "角色位"),
                    pi_flags=_int(cell.get("pi_flags"), "个人指令位"),
                    target_player=int(cell.get("target_player", 255)),
                    target_position=int(cell.get("target_position", 0)),
                )
                for cell in phase
            )
        )
    return PresetTemplate(
        index=_int(event.get("index"), "预设序号"),
        style_code=_int(event.get("style_code"), "预设风格"),
        name=name,
        plan=TacticPlan(
            name=name,
            mentality=int(event.get("mentality", 0)),
            team_bits=team_bits,
            mapping=mapping,
            phases=tuple(cells),
        ),
    )


def _team_bits(value: Any) -> int:
    if not isinstance(value, str) or len(value) != 32:
        raise CoachPresetError("原装预设球队指令位无效")
    try:
        return int.from_bytes(bytes.fromhex(value), "little")
    except ValueError as error:
        raise CoachPresetError("原装预设球队指令位无效") from error


def _one(events: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    found = [event for event in events if event.get("event") == name]
    if len(found) != 1:
        raise CoachPresetError(f"缺少原生事件：{name}")
    return found[0]


def _int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise CoachPresetError(f"{label}无效") from error
