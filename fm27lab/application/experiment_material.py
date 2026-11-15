"""Experiment materialization into engine match configurations."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.engine_native.scenario_codec import encode_scenario, validate_scenario
from fm27lab.application.drafts import DraftService
from fm27lab.config import Settings
from fm27lab.domain.pool import draws, expand_away_scenarios, normalize_away_pool, summary
from fm27lab.domain.scenario import upgrade_legacy_scenario

CONFIG_CODEC = "FM27CFG1"
SCENARIO_SCHEMA = "fm27lab-scenario/1"
PROVENANCE_FILE = "provenance.json"
EXPERIMENT_DIRECTORY = "experiments"
MAX_SEED = 0xFFFFFFFF
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CATALOG_CANDIDATES = ("fm27_native/catalog.json", "catalog.json")
VARIANTS = ("A", "B")
ENGINE_ROOT_MISSING = "引擎目录未配置，无法生成比赛配置"
CATALOG_MISSING = "未找到引擎目录文件，无法生成比赛配置"
JOB_ID_ERROR = "任务标识不合法，无法生成比赛配置"
SEED_ERROR = "种子必须为非空且不重复的 0–4294967295 整数列表"
SCENARIO_ERROR = "草案场景格式无效"
EXPERIMENT_ROOT_ERROR = "实验目录不合法"


class DraftNotFound(ValueError):
    def __init__(self, draft_id: str, *, baseline: bool = False):
        super().__init__("基线草案不存在" if baseline else "草案不存在")
        self.draft_id = draft_id
        self.baseline = baseline


class ExperimentMaterializer:
    def __init__(
        self,
        drafts: DraftService,
        settings: Settings,
        *,
        assets_loader: Callable[..., Any] = load_scenario_assets,
        encoder: Callable[..., bytes] = encode_scenario,
        validator: Callable[..., dict[str, Any]] = validate_scenario,
    ):
        self._drafts = drafts
        self._settings = settings
        self._assets_loader = assets_loader
        self._encoder = encoder
        self._validator = validator

    def prepare(
        self,
        *,
        job_id: str,
        draft_id: str,
        baseline_draft_id: str | None,
        seeds: Sequence[int],
    ) -> dict[str, Any]:
        _validate_job_id(job_id)
        seed_values = _validate_seeds(seeds)
        draft_scenario = self._scenario(draft_id, baseline=False)
        baseline_scenario = (
            None if baseline_draft_id is None else self._scenario(baseline_draft_id, baseline=True)
        )
        variants: list[tuple[str, dict[str, Any]]] = (
            [("B", draft_scenario)]
            if baseline_scenario is None
            else [("A", baseline_scenario), ("B", draft_scenario)]
        )
        engine_root, catalog_path = self._resources()
        assets = self._assets_loader(engine_root, catalog_path)
        pool_value = draft_scenario.get("away_tactic_pool")
        if pool_value is None and baseline_scenario is not None:
            pool_value = baseline_scenario.get("away_tactic_pool")
        pool_summary: dict[str, Any] | None = None
        entries_by_seed: dict[int, int] = {}
        expanded: dict[str, list[dict[str, Any]]] = {}
        if pool_value is not None:
            normalized_pool = normalize_away_pool(pool_value)
            if normalized_pool["enabled"]:
                entries = normalized_pool["entries"]
                rotation = normalized_pool["rotation"]
                entries_by_seed = draws(
                    entries,
                    seed_values,
                    job_id,
                    rotation_enabled=rotation["enabled"],
                    rounds=rotation["rounds"],
                )
                pool_summary = summary(
                    entries,
                    rotation=rotation,
                    uniform=normalized_pool["uniform"],
                    real=normalized_pool["real"],
                    salt=job_id,
                    profile=normalized_pool["profile"],
                    enabled=True,
                )
                pool_summary["draws"] = {
                    str(seed): entries_by_seed[seed] for seed in seed_values
                }
                for label, scenario in variants:
                    expanded[label] = expand_away_scenarios(
                        scenario, pool_value, seed_values, job_id
                    )
        for label, scenario in variants:
            if label not in expanded:
                expanded[label] = [copy.deepcopy(scenario) for _ in seed_values]

        root = self._experiment_root()
        root.mkdir(parents=True, exist_ok=True)
        target = root / job_id
        staging = Path(tempfile.mkdtemp(dir=root, prefix=f".{job_id}-"))
        configs: list[dict[str, Any]] = []
        try:
            for index, seed in enumerate(seed_values):
                for label, _ in variants:
                    validated = self._validator(assets, expanded[label][index])
                    config_bytes = self._encoder(assets, validated, absolute=False)
                    config_name = f"{label}-{seed}.bin"
                    scenario_name = f"{label}-{seed}.json"
                    (staging / config_name).write_bytes(config_bytes)
                    scenario_text = (
                        json.dumps(
                            validated,
                            sort_keys=True,
                            ensure_ascii=False,
                            allow_nan=False,
                            indent=2,
                        )
                        + "\n"
                    )
                    (staging / scenario_name).write_bytes(scenario_text.encode("utf-8"))
                    configs.append(
                        {
                            "variant": label,
                            "seed": seed,
                            "entry": entries_by_seed.get(seed),
                            "config_file": str((target / config_name).resolve()),
                            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
                            "scenario_file": str((target / scenario_name).resolve()),
                            "scenario_sha256": hashlib.sha256(
                                scenario_text.encode("utf-8")
                            ).hexdigest(),
                        }
                    )
            provenance = {
                "job_id": job_id,
                "salt": job_id,
                "codec": CONFIG_CODEC,
                "scenario_schema": SCENARIO_SCHEMA,
                "engine_root": str(Path(engine_root).resolve()),
                "catalog_path": str(Path(catalog_path).resolve()),
                "draft_id": draft_id,
                "baseline_draft_id": baseline_draft_id,
                "seeds": seed_values,
                "variants": [label for label, _ in variants],
                "pool": pool_summary,
                "configs": configs,
            }
            provenance_text = (
                json.dumps(provenance, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
                + "\n"
            )
            (staging / PROVENANCE_FILE).write_bytes(provenance_text.encode("utf-8"))
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "dir": str(target.resolve()),
            "codec": CONFIG_CODEC,
            "configs": configs,
            "pool": pool_summary,
        }

    def discard(self, job_id: str) -> None:
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            return
        root = self._experiment_root()
        target = (root / job_id).resolve()
        if not target.is_relative_to(root):
            return
        shutil.rmtree(target, ignore_errors=True)

    def _experiment_root(self) -> Path:
        data_dir = Path(self._settings.data_dir).resolve()
        root = (data_dir / "agent" / EXPERIMENT_DIRECTORY).resolve()
        if not root.is_relative_to(data_dir):
            raise ValueError(EXPERIMENT_ROOT_ERROR)
        return root

    def _scenario(self, draft_id: str, *, baseline: bool) -> dict[str, Any]:
        row = self._drafts.get(draft_id)
        if row is None:
            raise DraftNotFound(draft_id, baseline=baseline)
        scenario = row.get("scenario") if isinstance(row, Mapping) else None
        if not isinstance(scenario, Mapping):
            raise ValueError(SCENARIO_ERROR)
        return dict(upgrade_legacy_scenario(scenario))

    def _resources(self) -> tuple[Path, Path]:
        configured = self._settings.engine_root
        if configured is None:
            raise ValueError(ENGINE_ROOT_MISSING)
        engine_root = Path(configured)
        for relative in CATALOG_CANDIDATES:
            candidate = engine_root / relative
            if candidate.is_file():
                return engine_root, candidate
        fallback = self._settings.data_dir / "catalog.json"
        if fallback.is_file():
            return engine_root, fallback
        raise ValueError(CATALOG_MISSING)


def _validate_job_id(job_id: Any) -> str:
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError(JOB_ID_ERROR)
    return job_id


def _validate_seeds(seeds: Any) -> list[int]:
    if not isinstance(seeds, Sequence) or isinstance(seeds, (str, bytes)):
        raise ValueError(SEED_ERROR)
    values = list(seeds)
    if not values or any(type(seed) is not int or not 0 <= seed <= MAX_SEED for seed in values):
        raise ValueError(SEED_ERROR)
    if len(set(values)) != len(values):
        raise ValueError(SEED_ERROR)
    return values
