"""联赛对手战术：教练偏好、原装预设匹配、导出与入池。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.coach_presets import (
    CoachPresetError,
    PresetCatalog,
    PresetVariant,
    StaffPreference,
    decode_staff,
    export_catalog,
    variants,
)
from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.adapters.engine_native.tactic_file import TacticFileError
from fm27lab.adapters.save_fmsave.league import (
    Coach,
    League,
    LeagueCatalog,
    read_coaches,
    read_league_catalog,
)
from fm27lab.adapters.save_fmsave.reader import read_squads
from fm27lab.application.source_paths import clean_path_text
from fm27lab.application.tactic_export import TacticExporter
from fm27lab.application.tactic_import import build_scenario
from fm27lab.config import Settings
from fm27lab.domain.pool import MAX_NAME, normalize_away_pool, normalize_pool_roster
from fm27lab.domain.roster import MATCH_ROSTER_SIZE

LEAGUE_INDEX_BASE = 10_000
LEAGUE_INDEX_STRIDE = 1_000
SAVE_MISSING_ERROR = "存档文件不可用，请重新导入存档"
LEAGUE_MISSING_ERROR = "所选联赛不在当前存档目录中，请重新读取存档"
LEAGUE_LIST_REQUIRED = "请先刷新联赛战术列表"
ENGINE_UNAVAILABLE = "引擎资源未配置或不兼容，无法读取联赛对手战术；请在设置页重新导入与游戏匹配的引擎资源"
ENGINE_MISMATCH = "当前引擎与游戏版本不一致，无法读取联赛对手战术；请更新引擎资源"
NO_COACH = "存档中未找到可确认的一线队主教练"
PREFERENCE_MISMATCH = "主次偏好阵型未通过原版读回"
COACH_SOURCE = "coach_preset"
MAX_CACHE = 4
MAX_LEAGUE_ITEMS = 128
ATTRIBUTE_COUNT = 69
POSITION_ATTRIBUTES = 15
DEFAULT_WEIGHT = 1

CatalogReader = Callable[[Path], LeagueCatalog]
CoachReader = Callable[[Path, Iterable[int]], tuple[Coach, ...]]
PresetExporter = Callable[..., PresetCatalog]
StaffDecoder = Callable[..., dict[int, StaffPreference]]
AssetsLoader = Callable[..., ScenarioAssets]
Builder = Callable[..., dict[str, Any]]
SquadsReader = Callable[[Path, Iterable[int]], dict[int, list[dict[str, Any]]]]
Exporter = Callable[..., bytes]

__all__ = [
    "LEAGUE_INDEX_BASE",
    "LeagueTactic",
    "LeagueTacticsService",
]


@dataclass(frozen=True, slots=True)
class LeagueTactic:
    index: int
    name: str
    club_uid: int
    club_name: str
    coach_name: str
    variant: int
    formation_code: int
    exact: bool
    source: str
    scenario: dict[str, Any] = field(repr=False)
    league_key: str = ""
    roster: dict[str, Any] | None = field(default=None, repr=False)
    available: bool = True
    reason: str | None = None

    def public(self) -> dict[str, Any]:
        teams = self.scenario.get("teams") if isinstance(self.scenario, Mapping) else None
        team = teams[0] if isinstance(teams, list) and teams else {}
        return {
            "index": self.index,
            "name": self.name,
            "style": "教练偏好预设",
            "mentality": team.get("mentality"),
            "club_uid": self.club_uid,
            "club_name": self.club_name,
            "team_slot": 0,
            "importable": self.available,
            "source": self.source,
            "league_key": self.league_key or None,
            "coach_name": self.coach_name,
            "variant": self.variant,
            "formation_code": self.formation_code,
            "exact": self.exact,
            "available": self.available,
            "reason": self.reason,
        }


class LeagueTacticsService:
    def __init__(
        self,
        saves: Any,
        settings: Settings,
        pools: Any = None,
        *,
        catalog_reader: CatalogReader = read_league_catalog,
        coach_reader: CoachReader = read_coaches,
        preset_exporter: PresetExporter = export_catalog,
        staff_decoder: StaffDecoder = decode_staff,
        assets_loader: AssetsLoader = load_scenario_assets,
        builder: Builder = build_scenario,
        squads_reader: SquadsReader | None = None,
        exporter: TacticExporter | None = None,
    ) -> None:
        self.saves = saves
        self.settings = settings
        self.pools = pools
        self.catalog_reader = catalog_reader
        self.coach_reader = coach_reader
        self.preset_exporter = preset_exporter
        self.staff_decoder = staff_decoder
        self.assets_loader = assets_loader
        self.builder = builder
        self.squads_reader = squads_reader or read_squads
        self.exporter = exporter if exporter is not None else TacticExporter()
        self._catalogs: dict[str, tuple[tuple[int, int], LeagueCatalog]] = {}
        self._variants: dict[tuple[str, str, tuple[int, int]], tuple[LeagueTactic, ...]] = {}
        self._rosters: dict[
            tuple[str, tuple[int, int], str], dict[int, dict[str, Any] | None]
        ] = {}
        self._presets: dict[tuple[str, str], PresetCatalog] = {}

    def catalog(self, save_id: str) -> dict[str, Any]:
        """联赛列表与当前联赛；不触发原生调用。"""
        save, path = self._source(save_id)
        catalog = self._catalog(save_id, path)
        rows = []
        for league in catalog.leagues:
            summary = league.summary()
            summary["own"] = any(uid in league.club_uids for uid in catalog.managed)
            summary["name"] = _league_name(league)
            summary["opponent_count"] = sum(1 for uid in league.club_uids if uid not in catalog.managed)
            rows.append(summary)
        current = catalog.current
        return {
            "save": {
                "id": save_id,
                "source": save.get("source_path"),
                "date": catalog.save_date,
            },
            "leagues": rows,
            "current": None
            if current is None
            else {
                **current.summary(),
                "name": _league_name(current),
                "own": True,
                "opponent_count": sum(
                    1 for uid in current.club_uids if uid not in catalog.managed
                ),
            },
            "ambiguous": [item.key for item in catalog.ambiguous],
            "warnings": [] if current is not None else ["当前联赛范围未唯一确定，请手动选择联赛"],
        }

    def rows(self, save_id: str, league_key: str) -> list[dict[str, Any]]:
        return [item.public() for item in self._variants_for(save_id, league_key)]

    def items(self, save_id: str, league_key: str) -> list[dict[str, Any]]:
        return [item.public() for item in self._variants_for(save_id, league_key) if item.available]

    def failures(self, save_id: str, league_key: str) -> list[dict[str, Any]]:
        catalog = self._catalog(save_id, self._source(save_id)[1])
        league = _league(catalog, league_key)
        rows = [item.public() for item in self._variants_for(save_id, league_key)]
        available = {row["club_uid"] for row in rows if row["available"]}
        names = {uid: _club_name(catalog, uid) for uid in league.club_uids}
        coaches = {row.get("club_uid"): row.get("coach_name") for row in rows}
        return [
            {
                "club_uid": uid,
                "club_name": names[uid],
                "coach_name": coaches.get(uid),
                "reason": _first_reason(rows, uid) or "该队教练偏好预设尚不可用",
            }
            for uid in sorted(league.club_uids)
            if uid not in catalog.managed and uid not in available
        ]

    def materialize(self, save_id: str, index: int) -> LeagueTactic:
        _save, path = self._source(save_id)
        current = _signature(path)
        for (cached_save, _league, signature), items in list(self._variants.items()):
            if cached_save != save_id or signature != current:
                continue
            for item in items:
                if item.index == index:
                    return item
        raise ValueError(LEAGUE_LIST_REQUIRED)

    def export_fmf(self, save_id: str, index: int) -> tuple[str, bytes]:
        item = self.materialize(save_id, index)
        if not item.available:
            raise ValueError(item.reason or "该战术尚不可用")
        engine_root, game_root = self._roots()
        payload = self.exporter.export(
            name=item.name,
            scenario=item.scenario,
            engine_root=engine_root,
            game_root=game_root,
        )
        return item.name, payload

    def pool_entry(self, save_id: str, index: int) -> dict[str, Any]:
        item = self.materialize(save_id, index)
        if not item.available:
            raise ValueError(item.reason or "该战术尚不可用")
        entry = {
            "name": item.name,
            "weight": DEFAULT_WEIGHT,
            "tactic": _tactic(item.scenario),
        }
        roster = self._roster_for(save_id, item)
        if roster is not None:
            entry["roster"] = roster
        return normalize_away_pool({"entries": [entry]})["entries"][0]

    def _variants_for(self, save_id: str, league_key: str) -> tuple[LeagueTactic, ...]:
        save, path = self._source(save_id)
        signature = _signature(path)
        key = (save_id, league_key, signature)
        cached = self._variants.get(key)
        if cached is not None:
            return cached
        catalog = self._catalog(save_id, path)
        league = _league(catalog, league_key)
        opponents = [uid for uid in league.club_uids if uid not in catalog.managed]
        slot = _league_slot(catalog, league_key)
        built = self._build(path, catalog, opponents, slot=slot, league_key=league_key)
        if len(built) > MAX_LEAGUE_ITEMS:
            raise ValueError(f"联赛战术最多 {MAX_LEAGUE_ITEMS} 条，请缩小联赛范围")
        for existing in list(self._variants):
            if existing[0] == save_id and existing != key and existing[2] != signature:
                self._variants.pop(existing, None)
        if len(self._variants) >= MAX_CACHE:
            self._variants.pop(next(iter(self._variants)), None)
        self._variants[key] = built
        return built

    def _build(
        self,
        path: Path,
        catalog: LeagueCatalog,
        opponents: Sequence[int],
        *,
        slot: int,
        league_key: str,
    ) -> tuple[LeagueTactic, ...]:
        names = {uid: _club_name(catalog, uid) for uid in opponents}
        try:
            coaches = {coach.club_uid: coach for coach in self.coach_reader(path, opponents)}
        except (OSError, RuntimeError, ValueError) as error:
            return tuple(
                _assign_indices(
                    _unavailable(opponents, names, {}, f"教练偏好读取失败：{error}"),
                    slot=slot,
                    league_key=league_key,
                )
            )
        engine_root, game_root = self._roots(required=False)
        if engine_root is None or game_root is None:
            return tuple(
                _assign_indices(
                    _unavailable(opponents, names, coaches, ENGINE_UNAVAILABLE),
                    slot=slot,
                    league_key=league_key,
                )
            )
        try:
            presets = self._preset_catalog(engine_root, game_root)
            preferences = self.staff_decoder(
                {coach.selector: coach.fragment for coach in coaches.values()},
                engine_root=engine_root,
                game_root=game_root,
            )
            assets = self.assets_loader(engine_root)
        except (TacticFileError, CoachPresetError, OSError, ValueError) as error:
            reason = ENGINE_MISMATCH if "版本" in str(error) or "兼容" in str(error) else str(error)
            return tuple(
                _assign_indices(
                    _unavailable(opponents, names, coaches, reason or ENGINE_UNAVAILABLE),
                    slot=slot,
                    league_key=league_key,
                )
            )
        result: list[LeagueTactic] = []
        for club_uid in sorted(opponents, key=lambda uid: (names[uid], uid)):
            club_name = names[club_uid]
            coach = coaches.get(club_uid)
            if coach is None:
                result.append(_failure_item(club_uid, club_name, None, NO_COACH))
                continue
            preference = preferences.get(coach.selector)
            if (
                preference is None
                or preference.profile_hex != coach.profile_hex
                or preference.codes_hex != coach.codes_hex
            ):
                result.append(_failure_item(club_uid, club_name, coach.name, PREFERENCE_MISMATCH))
                continue
            try:
                options = variants(
                    presets,
                    style=preference.style,
                    primary=preference.primary,
                    secondary=preference.secondary,
                )
            except CoachPresetError as error:
                result.append(_failure_item(club_uid, club_name, coach.name, str(error)))
                continue
            for option in options:
                result.append(
                    _variant_item(
                        club_uid,
                        club_name,
                        coach.name,
                        option,
                        self.builder,
                        assets,
                        league_key,
                    )
                )
        return tuple(_assign_indices(result, slot=slot, league_key=league_key))

    def _roster_for(self, save_id: str, item: LeagueTactic) -> dict[str, Any] | None:
        if not item.league_key:
            return None
        _save, path = self._source(save_id)
        signature = _signature(path)
        key = (save_id, signature, item.league_key)
        cached = self._rosters.get(key)
        if cached is None:
            catalog = self._catalog(save_id, path)
            league = _league(catalog, item.league_key)
            opponents = [uid for uid in league.club_uids if uid not in catalog.managed]
            names = {uid: _club_name(catalog, uid) for uid in opponents}
            coaches = {
                row.club_uid: row.coach_name
                for rows in self._variants.values()
                for row in rows
                if row.league_key == item.league_key
            }
            try:
                squads = self.squads_reader(path, opponents)
            except (OSError, RuntimeError, ValueError):
                squads = {}
            cached = {
                uid: _roster_from(
                    squads.get(uid, []),
                    uid,
                    names[uid],
                    coaches.get(uid, ""),
                )
                for uid in opponents
            }
            if len(self._rosters) >= MAX_CACHE:
                self._rosters.pop(next(iter(self._rosters)))
            self._rosters[key] = cached
        return cached.get(item.club_uid)

    def _preset_catalog(self, engine_root: Path, game_root: Path) -> PresetCatalog:
        key = (str(engine_root), str(game_root))
        cached = self._presets.get(key)
        if cached is not None:
            return cached
        presets = self.preset_exporter(engine_root=engine_root, game_root=game_root)
        if len(self._presets) >= MAX_CACHE:
            self._presets.pop(next(iter(self._presets)))
        self._presets[key] = presets
        return presets

    def _catalog(self, save_id: str, path: Path) -> LeagueCatalog:
        signature = _signature(path)
        cached = self._catalogs.get(save_id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        catalog = self.catalog_reader(path)
        if len(self._catalogs) >= MAX_CACHE:
            self._catalogs.pop(next(iter(self._catalogs)))
        self._catalogs[save_id] = (signature, catalog)
        return catalog

    def _source(self, save_id: str) -> tuple[Mapping[str, Any], Path]:
        save = self.saves.get(save_id)
        if save is None:
            raise ValueError("存档不存在")
        text = clean_path_text(save.get("source_path"))
        if text is None:
            raise ValueError(SAVE_MISSING_ERROR)
        path = Path(text)
        if not path.is_file():
            raise ValueError(SAVE_MISSING_ERROR)
        return save, path

    def _roots(self, *, required: bool = True) -> tuple[Path | None, Path | None]:
        engine = self.settings.engine_root
        game = self.settings.game_root
        if required and (engine is None or game is None):
            raise TacticFileError(ENGINE_UNAVAILABLE)
        return engine, game


def _roster_from(
    squad: Sequence[Mapping[str, Any]],
    club_uid: int,
    club_name: str,
    coach_name: str,
) -> dict[str, Any] | None:
    players = [player for player in squad if _roster_player_ok(player)]
    if len(players) < MATCH_ROSTER_SIZE:
        return None
    goalkeepers = [player for player in players if str(player.get("position") or "").startswith("GK")]
    if not goalkeepers:
        return None
    others = [player for player in players if player not in goalkeepers]
    goalkeepers.sort(key=lambda player: -_ability(player))
    others.sort(key=lambda player: -_ability(player))
    reserve = goalkeepers[1:2]
    chosen = ([goalkeepers[0]] + others)[: MATCH_ROSTER_SIZE - len(reserve)] + reserve
    if len(chosen) != MATCH_ROSTER_SIZE:
        return None
    indexes = {id(player): index for index, player in enumerate(chosen)}
    lineup = [indexes[id(chosen[0])]]
    lineup.extend(range(1, 11))
    roster = {
        "club_uid": club_uid,
        "club": _clip(club_name, 40),
        "coach": _clip(coach_name, 60),
        "source": COACH_SOURCE,
        "roster_size": len(chosen),
        "lineup": lineup,
        "players": [
            {
                "name": _clip(str(player.get("name") or "球员"), 48),
                "source_uid": int(player["source_uid"]),
                "attributes": _attributes(player.get("attributes")),
            }
            for player in chosen
        ],
    }
    return normalize_pool_roster(roster)


def _league_slot(catalog: LeagueCatalog, key: str) -> int:
    ordered = sorted(catalog.leagues, key=lambda league: league.key)
    return next(
        (index for index, league in enumerate(ordered) if league.key == key),
        0,
    )


def _league(catalog: LeagueCatalog, key: str) -> League:
    league = next((item for item in catalog.leagues if item.key == key), None)
    if league is None:
        raise ValueError(LEAGUE_MISSING_ERROR)
    return league


def _league_name(league: League) -> str:
    return f"联赛 #{league.database_id or league.competition_id} · {league.season or '当前赛季'}"


def _club_name(catalog: LeagueCatalog, uid: int) -> str:
    club = catalog.clubs.get(uid)
    if club is None:
        return str(uid)
    return club.short_name or club.name


def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as error:
        raise ValueError(SAVE_MISSING_ERROR) from error
    return (stat.st_size, stat.st_mtime_ns)


def _unavailable(
    opponents: Sequence[int],
    names: Mapping[int, str],
    coaches: Mapping[int, Coach],
    reason: str,
) -> tuple[LeagueTactic, ...]:
    return tuple(
        _failure_item(uid, names[uid], coaches.get(uid).name if coaches.get(uid) else None, reason)
        for uid in opponents
    )


def _failure_item(club_uid: int, club_name: str, coach_name: str | None, reason: str) -> LeagueTactic:
    return LeagueTactic(
        index=LEAGUE_INDEX_BASE,
        name=f"{club_name} · 战术不可用",
        club_uid=club_uid,
        club_name=club_name,
        coach_name=coach_name or "",
        variant=0,
        formation_code=0,
        exact=False,
        source=COACH_SOURCE,
        scenario={},
        available=False,
        reason=reason,
    )


def _variant_item(
    club_uid: int,
    club_name: str,
    coach_name: str,
    option: PresetVariant,
    builder: Builder,
    assets: ScenarioAssets,
    league_key: str,
) -> LeagueTactic:
    label = "主偏好" if option.variant == 1 else "次偏好"
    name = _clip(f"{club_name} · {option.template.name} · {label}", MAX_NAME)
    tactic_name = _clip(f"{coach_name} · {option.template.name} · {label}", 80)
    try:
        scenario = builder(assets, option.template.plan, tactic_name=tactic_name)
    except (ValueError, TacticFileError) as error:
        return _failure_item(club_uid, club_name, coach_name, str(error))
    return LeagueTactic(
        index=LEAGUE_INDEX_BASE,
        name=name,
        club_uid=club_uid,
        club_name=club_name,
        coach_name=coach_name,
        variant=option.variant,
        formation_code=option.formation_code,
        exact=option.exact,
        source=COACH_SOURCE,
        league_key=league_key,
        scenario=scenario,
    )


def _assign_indices(
    items: Iterable[LeagueTactic],
    *,
    slot: int,
    league_key: str,
) -> list[LeagueTactic]:
    base = LEAGUE_INDEX_BASE + slot * LEAGUE_INDEX_STRIDE
    result = []
    for offset, item in enumerate(items):
        result.append(
            LeagueTactic(
                index=base + offset,
                name=item.name,
                club_uid=item.club_uid,
                club_name=item.club_name,
                coach_name=item.coach_name,
                variant=item.variant,
                formation_code=item.formation_code,
                exact=item.exact,
                source=item.source,
                league_key=league_key,
                scenario=item.scenario,
                roster=item.roster,
                available=item.available,
                reason=item.reason,
            )
        )
    return result


def _first_reason(rows: Sequence[Mapping[str, Any]], club_uid: int) -> str | None:
    return next(
        (str(row["reason"]) for row in rows if row["club_uid"] == club_uid and row.get("reason")),
        None,
    )


def _tactic(scenario: Mapping[str, Any]) -> dict[str, Any]:
    team = scenario["teams"][0]
    return {
        "tactic_name": team.get("tactic_name") or "",
        "mentality": team.get("mentality"),
        "instructions": team.get("instructions") or {},
        "native_extra_team_bits": team.get("native_extra_team_bits") or "0",
        "phases": team.get("phases"),
    }


def _roster_player_ok(player: Mapping[str, Any]) -> bool:
    attributes = player.get("attributes")
    uid = player.get("source_uid")
    return (
        isinstance(attributes, list)
        and len(attributes) == ATTRIBUTE_COUNT
        and type(uid) is int
        and 0 <= uid <= 0xFFFFFFFF
        and isinstance(player.get("name"), str)
    )


def _ability(player: Mapping[str, Any]) -> int:
    value = player.get("ability")
    return value if type(value) is int else 0


def _attributes(values: Any) -> list[int]:
    attributes = [int(value) for value in values]
    return [
        min(20, max(0, value)) if index < POSITION_ATTRIBUTES else min(100, max(1, value))
        for index, value in enumerate(attributes)
    ]


def _clip(text: str, limit: int) -> str:
    cleaned = "".join(character for character in text if ord(character) >= 32 and ord(character) != 127)
    return (cleaned.strip() or "战术")[:limit]
