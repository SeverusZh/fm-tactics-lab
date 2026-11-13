from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.engine_native.scenario_codec import validate_scenario
from fm27lab.application.experiment_material import (
    CONFIG_CODEC,
    SCENARIO_SCHEMA,
    DraftNotFound,
    ExperimentMaterializer,
)
from fm27lab.application.experiments import ExperimentService
from fm27lab.config import Settings
from fm27lab.tests.test_experiments_service import PLAN, SUBMIT_OPTIONS, FakeEngine, job_service
from fm27lab.tests.test_scenario_assets import write_engine_root

JOB_ID = "job-material"


def make_settings(tmp_path: Path, engine_root: Path | None) -> Settings:
    return Settings.create(
        data_dir=tmp_path / "data",
        engine_root=engine_root,
        token="c" * 64,
        dev=True,
    )


class StubDrafts:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows
        self.requests: list[str] = []

    def get(self, draft_id: str):
        self.requests.append(draft_id)
        row = self.rows.get(draft_id)
        return None if row is None else copy.deepcopy(row)


def engine_scenario(assets, *, home_name: str = "主队", pool: dict | None = None) -> dict:
    scenario: dict = {
        "schema": 3,
        "rules": "lab",
        "fixture": "bundled_match_pkm",
        "teams": [
            copy.deepcopy(assets.default_teams[0]),
            copy.deepcopy(assets.default_teams[1]),
        ],
    }
    scenario["teams"][0]["name"] = home_name
    if pool is not None:
        scenario["away_tactic_pool"] = copy.deepcopy(pool)
    return scenario


def away_tactic(assets, name: str) -> dict:
    away = assets.default_teams[1]
    return {
        "tactic_name": name,
        "mentality": away["mentality"],
        "instructions": copy.deepcopy(away["instructions"]),
        "native_extra_team_bits": away["native_extra_team_bits"],
        "phases": copy.deepcopy(away["phases"]),
    }


def away_pool(
    assets,
    *,
    names: tuple[str, ...] = ("客队战术甲", "客队战术乙"),
    enabled: bool = True,
    rotation: dict | None = None,
    uniform: dict | None = None,
) -> dict:
    value: dict = {
        "profile": "away-tactic-pool-v1",
        "enabled": enabled,
        "entries": [
            {"name": name, "weight": 1, "tactic": away_tactic(assets, name)} for name in names
        ],
    }
    if rotation is not None:
        value["rotation"] = rotation
    if uniform is not None:
        value["uniform"] = uniform
    return value


def draft_row(scenario: dict, *, name: str = "候选") -> dict:
    return {"id": "draft-1", "name": name, "scenario": copy.deepcopy(scenario), "source": None}


@pytest.fixture
def engine_root(tmp_path: Path) -> Path:
    return write_engine_root(tmp_path)


@pytest.fixture
def assets(engine_root: Path):
    return load_scenario_assets(engine_root)


def materializer(tmp_path, engine_root, rows: dict[str, dict], **overrides) -> ExperimentMaterializer:
    return ExperimentMaterializer(
        StubDrafts(rows),
        make_settings(tmp_path, engine_root),
        **overrides,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_writes_single_variant_configs(tmp_path, assets, engine_root):
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[5, 9])
    expected_dir = (tmp_path / "data" / "agent" / "experiments" / JOB_ID).resolve()
    assert Path(result["dir"]) == expected_dir
    assert Path(result["dir"]).is_relative_to((tmp_path / "data").resolve())
    assert result["codec"] == CONFIG_CODEC
    assert [(item["variant"], item["seed"]) for item in result["configs"]] == [("B", 5), ("B", 9)]
    assert all(item["entry"] is None for item in result["configs"])
    assert result["pool"] is None
    for item in result["configs"]:
        config_path = Path(item["config_file"])
        scenario_path = Path(item["scenario_file"])
        assert config_path.name == f"B-{item['seed']}.bin"
        assert scenario_path.name == f"B-{item['seed']}.json"
        assert config_path.parent == scenario_path.parent == expected_dir
        config_bytes = config_path.read_bytes()
        assert config_bytes.startswith(b"FM27CFG1")
        assert item["config_sha256"] == hashlib.sha256(config_bytes).hexdigest()
        scenario_bytes = scenario_path.read_bytes()
        assert item["scenario_sha256"] == hashlib.sha256(scenario_bytes).hexdigest()
        assert read_json(scenario_path)["teams"][0]["name"] == "主队"
    json.dumps(result, allow_nan=False)


def test_prepare_writes_ab_variants_from_baseline_and_draft(tmp_path, assets, engine_root):
    baseline_scenario = engine_scenario(assets, home_name="基线主队")
    baseline_scenario["teams"][0]["mentality"] = 3
    rows = {
        "draft-1": draft_row(engine_scenario(assets, home_name="候选主队")),
        "draft-0": draft_row(baseline_scenario, name="基线"),
    }
    worker = materializer(tmp_path, engine_root, rows)
    result = worker.prepare(
        job_id=JOB_ID,
        draft_id="draft-1",
        baseline_draft_id="draft-0",
        seeds=[1],
    )
    assert [(item["variant"], item["seed"]) for item in result["configs"]] == [("A", 1), ("B", 1)]
    snapshots = {
        item["variant"]: read_json(Path(item["scenario_file"])) for item in result["configs"]
    }
    assert snapshots["A"]["teams"][0]["name"] == "基线主队"
    assert snapshots["B"]["teams"][0]["name"] == "候选主队"
    a_bytes = Path(result["configs"][0]["config_file"]).read_bytes()
    b_bytes = Path(result["configs"][1]["config_file"]).read_bytes()
    assert a_bytes != b_bytes


def test_prepare_orders_configs_by_seed_then_variant(tmp_path, assets, engine_root):
    rows = {
        "draft-1": draft_row(engine_scenario(assets)),
        "draft-0": draft_row(engine_scenario(assets), name="基线"),
    }
    worker = materializer(tmp_path, engine_root, rows)
    result = worker.prepare(
        job_id=JOB_ID,
        draft_id="draft-1",
        baseline_draft_id="draft-0",
        seeds=[7, 3],
    )
    assert [(item["variant"], item["seed"]) for item in result["configs"]] == [
        ("A", 7),
        ("B", 7),
        ("A", 3),
        ("B", 3),
    ]


def test_prepare_writes_normalized_scenario_snapshot(tmp_path, assets, engine_root):
    scenario = engine_scenario(assets)
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(scenario)})
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[2])
    snapshot = read_json(Path(result["configs"][0]["scenario_file"]))
    assert snapshot["schema"] == 3
    assert snapshot["fixture"] == "bundled_match_pkm"
    assert len(snapshot["teams"]) == 2
    assert "away_tactic_pool" not in snapshot
    assert snapshot == validate_scenario(assets, scenario)
    raw = Path(result["configs"][0]["scenario_file"]).read_text(encoding="utf-8")
    assert raw == json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def test_prepare_writes_provenance(tmp_path, assets, engine_root):
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[2, 4])
    provenance = read_json(Path(result["dir"]) / "provenance.json")
    assert provenance["job_id"] == JOB_ID
    assert provenance["salt"] == JOB_ID
    assert provenance["codec"] == CONFIG_CODEC
    assert provenance["scenario_schema"] == SCENARIO_SCHEMA
    assert Path(provenance["engine_root"]) == engine_root.resolve()
    assert Path(provenance["catalog_path"]) == (engine_root / "fm27_native" / "catalog.json").resolve()
    assert provenance["seeds"] == [2, 4]
    assert provenance["variants"] == ["B"]
    assert provenance["pool"] is None
    assert provenance["configs"] == result["configs"]


def test_prepare_pool_random_draw_shares_entry_across_variants(tmp_path, assets, engine_root):
    pool = away_pool(assets)
    rows = {
        "draft-1": draft_row(engine_scenario(assets, home_name="候选主队", pool=pool)),
        "draft-0": draft_row(engine_scenario(assets, home_name="基线主队", pool=pool), name="基线"),
    }
    worker = materializer(tmp_path, engine_root, rows)
    seeds = [11, 22, 33]
    result = worker.prepare(
        job_id=JOB_ID,
        draft_id="draft-1",
        baseline_draft_id="draft-0",
        seeds=seeds,
    )
    entries = {(item["variant"], item["seed"]): item["entry"] for item in result["configs"]}
    for seed in seeds:
        assert entries[("A", seed)] == entries[("B", seed)]
        assert 0 <= entries[("B", seed)] < 2
    summary = result["pool"]
    assert summary["enabled"] is True
    assert summary["mode"] == "random"
    assert summary["entries"][0]["name"] == "客队战术甲"
    assert len(summary["entries"]) == 2
    assert summary["draws"] == {str(seed): entries[("B", seed)] for seed in seeds}
    names = ["客队战术甲", "客队战术乙"]
    for item in result["configs"]:
        snapshot = read_json(Path(item["scenario_file"]))
        assert snapshot["teams"][1]["tactic_name"] == names[item["entry"]]
        home = "基线主队" if item["variant"] == "A" else "候选主队"
        assert snapshot["teams"][0]["name"] == home


def test_prepare_pool_rotation_expands_entries_in_order(tmp_path, assets, engine_root):
    pool = away_pool(assets, rotation={"enabled": True, "rounds": 1})
    worker = materializer(
        tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets, pool=pool))}
    )
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[10, 20])
    assert [item["entry"] for item in result["configs"]] == [0, 1]
    names = [read_json(Path(item["scenario_file"]))["teams"][1]["tactic_name"] for item in result["configs"]]
    assert names == ["客队战术甲", "客队战术乙"]
    assert result["pool"]["mode"] == "rotation"
    assert result["pool"]["rounds"] == 1


def test_prepare_pool_rotation_rejects_wrong_seed_count(tmp_path, assets, engine_root):
    pool = away_pool(assets, rotation={"enabled": True, "rounds": 1})
    worker = materializer(
        tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets, pool=pool))}
    )
    with pytest.raises(ValueError, match="轮战模式每方案需要 2 套 × 1 轮 = 2 场，当前种子数为 1"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[10])
    experiments = tmp_path / "data" / "agent" / "experiments"
    assert not (experiments / JOB_ID).exists()


def test_prepare_disabled_pool_does_not_expand(tmp_path, assets, engine_root):
    pool = away_pool(assets, enabled=False)
    worker = materializer(
        tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets, pool=pool))}
    )
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])
    assert result["pool"] is None
    snapshot = read_json(Path(result["configs"][0]["scenario_file"]))
    assert "away_tactic_pool" not in snapshot
    assert snapshot["teams"][1]["tactic_name"] == assets.default_teams[1]["tactic_name"]


def test_prepare_pool_falls_back_to_baseline(tmp_path, assets, engine_root):
    baseline_pool = away_pool(assets, names=("基线池甲",))
    rows = {
        "draft-1": draft_row(engine_scenario(assets, home_name="候选主队")),
        "draft-0": draft_row(
            engine_scenario(assets, home_name="基线主队", pool=baseline_pool), name="基线"
        ),
    }
    worker = materializer(tmp_path, engine_root, rows)
    result = worker.prepare(
        job_id=JOB_ID,
        draft_id="draft-1",
        baseline_draft_id="draft-0",
        seeds=[1, 2],
    )
    assert result["pool"]["entries"][0]["name"] == "基线池甲"
    for item in result["configs"]:
        snapshot = read_json(Path(item["scenario_file"]))
        assert snapshot["teams"][1]["tactic_name"] == "基线池甲"


def test_prepare_rejects_unknown_draft(tmp_path, assets, engine_root):
    worker = materializer(tmp_path, engine_root, {})
    with pytest.raises(DraftNotFound) as error:
        worker.prepare(job_id=JOB_ID, draft_id="missing", baseline_draft_id=None, seeds=[1])
    assert str(error.value) == "草案不存在"
    assert error.value.draft_id == "missing"
    assert error.value.baseline is False

    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    with pytest.raises(DraftNotFound) as baseline_error:
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id="missing", seeds=[1])
    assert str(baseline_error.value) == "基线草案不存在"
    assert baseline_error.value.baseline is True


def test_prepare_rejects_missing_engine_root(tmp_path, assets):
    worker = materializer(tmp_path, None, {"draft-1": draft_row(engine_scenario(assets))})
    with pytest.raises(ValueError, match="引擎目录未配置，无法生成比赛配置"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])


def test_prepare_rejects_missing_catalog(tmp_path, assets, engine_root):
    (engine_root / "fm27_native" / "catalog.json").unlink()
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    with pytest.raises(ValueError, match="未找到引擎目录文件，无法生成比赛配置"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])


def test_prepare_uses_engine_root_catalog_fallback(tmp_path, assets, engine_root):
    native_catalog = engine_root / "fm27_native" / "catalog.json"
    payload = native_catalog.read_bytes()
    native_catalog.unlink()
    (engine_root / "catalog.json").write_bytes(payload)
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])
    provenance = read_json(Path(result["dir"]) / "provenance.json")
    assert Path(provenance["catalog_path"]) == (engine_root / "catalog.json").resolve()


def test_prepare_uses_data_dir_catalog_fallback(tmp_path, assets, engine_root):
    native_catalog = engine_root / "fm27_native" / "catalog.json"
    payload = native_catalog.read_bytes()
    native_catalog.unlink()
    settings = make_settings(tmp_path, engine_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "catalog.json").write_bytes(payload)
    worker = ExperimentMaterializer(
        StubDrafts({"draft-1": draft_row(engine_scenario(assets))}),
        settings,
    )
    result = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])
    provenance = read_json(Path(result["dir"]) / "provenance.json")
    assert Path(provenance["catalog_path"]) == (settings.data_dir / "catalog.json").resolve()


def test_prepare_removes_partial_output_when_encoding_fails(tmp_path, assets, engine_root):
    calls: list[bool] = []

    def failing_encoder(assets_value, scenario, *, absolute=True):
        calls.append(absolute)
        if len(calls) == 2:
            raise RuntimeError("编码失败")
        return b"FM27CFG1" + b"\x00" * 8

    worker = materializer(
        tmp_path,
        engine_root,
        {"draft-1": draft_row(engine_scenario(assets))},
        encoder=failing_encoder,
    )
    with pytest.raises(RuntimeError, match="编码失败"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1, 2])
    assert calls == [False, False]
    experiments = tmp_path / "data" / "agent" / "experiments"
    assert not (experiments / JOB_ID).exists()
    assert not experiments.exists() or list(experiments.iterdir()) == []


@pytest.mark.parametrize("job_id", ["", "../escape", "a/b", "x" * 65, "bad id", "job.1", 7])
def test_prepare_rejects_illegal_job_id(tmp_path, assets, engine_root, job_id):
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    with pytest.raises(ValueError, match="任务标识"):
        worker.prepare(job_id=job_id, draft_id="draft-1", baseline_draft_id=None, seeds=[1])
    assert not (tmp_path / "data" / "agent" / "escape").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "seeds",
    [[], [1, 1], [True], [False], [-1], [2**32], [1.5], ["1"]],
)
def test_prepare_rejects_invalid_seeds(tmp_path, assets, engine_root, seeds):
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    with pytest.raises(ValueError, match="种子"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=seeds)


def test_prepare_rejects_invalid_away_pool(tmp_path, assets, engine_root):
    scenario = engine_scenario(assets, pool={"enabled": True, "entries": []})
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(scenario)})
    with pytest.raises(ValueError, match="客队战术池"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])


def test_prepare_rejects_invalid_scenario(tmp_path, assets, engine_root):
    scenario = {"schema": 3, "rules": "lab", "fixture": "bundled_match_pkm", "teams": []}
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(scenario)})
    with pytest.raises(ValueError) as error:
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])
    assert any("\u4e00" <= char <= "\u9fff" for char in str(error.value))


def test_prepare_is_deterministic_for_same_inputs(tmp_path, assets, engine_root):
    worker = materializer(tmp_path, engine_root, {"draft-1": draft_row(engine_scenario(assets))})
    first = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[3, 4])
    directory = Path(first["dir"])
    first_bytes = {path.name: path.read_bytes() for path in sorted(directory.iterdir())}
    second = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[3, 4])
    assert second == first
    second_bytes = {path.name: path.read_bytes() for path in sorted(Path(second["dir"]).iterdir())}
    assert second_bytes == first_bytes
WINDOWS_SYMLINK = pytest.mark.skipif(sys.platform == "win32", reason="符号链接语义依赖平台")


@WINDOWS_SYMLINK
def test_prepare_rejects_experiments_root_escaping_data_dir(tmp_path, engine_root, assets):
    settings = make_settings(tmp_path, engine_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (settings.data_dir / "agent").symlink_to(outside)
    worker = ExperimentMaterializer(
        StubDrafts({"draft-1": draft_row(engine_scenario(assets))}),
        settings,
    )

    with pytest.raises(ValueError, match="实验目录不合法"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])

    assert not (outside / "experiments" / JOB_ID).exists()


@WINDOWS_SYMLINK
def test_prepare_rejects_experiment_root_escaping_into_prefixed_sibling(tmp_path, engine_root, assets):
    settings = make_settings(tmp_path, engine_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sibling = tmp_path / "data-evil"
    sibling.mkdir()
    sentinel = sibling / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    (settings.data_dir / "agent").symlink_to(sibling)
    worker = ExperimentMaterializer(
        StubDrafts({"draft-1": draft_row(engine_scenario(assets))}),
        settings,
    )

    with pytest.raises(ValueError, match="实验目录不合法"):
        worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])

    assert not (sibling / "experiments").exists()
    assert sorted(path.name for path in sibling.iterdir()) == ["sentinel.txt"]
    assert sentinel.read_text(encoding="utf-8") == "keep"


@WINDOWS_SYMLINK
def test_discard_rejects_experiments_root_escaping_data_dir(tmp_path, engine_root):
    settings = make_settings(tmp_path, engine_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "experiments" / JOB_ID
    target.mkdir(parents=True)
    (settings.data_dir / "agent").symlink_to(outside)
    worker = ExperimentMaterializer(StubDrafts({}), settings)

    with pytest.raises(ValueError, match="实验目录不合法"):
        worker.discard(JOB_ID)

    assert target.is_dir()


@WINDOWS_SYMLINK
def test_discard_rejects_experiment_root_escaping_into_prefixed_sibling(tmp_path, engine_root):
    settings = make_settings(tmp_path, engine_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sibling = tmp_path / "data-evil"
    target = sibling / "experiments" / JOB_ID
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    (settings.data_dir / "agent").symlink_to(sibling)
    worker = ExperimentMaterializer(StubDrafts({}), settings)

    with pytest.raises(ValueError, match="实验目录不合法"):
        worker.discard(JOB_ID)

    assert target.is_dir()
    assert sorted(path.name for path in target.iterdir()) == ["sentinel.txt"]
    assert sentinel.read_text(encoding="utf-8") == "keep"


@WINDOWS_SYMLINK
def test_discard_does_not_follow_job_directory_symlink_outside_experiment_root(tmp_path, engine_root):
    settings = make_settings(tmp_path, engine_root)
    root = settings.data_dir / "agent" / "experiments"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    other_job = root / "job-other"
    other_job.mkdir()
    kept = other_job / "keep.txt"
    kept.write_text("keep", encoding="utf-8")
    (root / JOB_ID).symlink_to(outside)
    worker = ExperimentMaterializer(StubDrafts({}), settings)

    assert worker.discard(JOB_ID) is None

    assert outside.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (root / JOB_ID).is_symlink()
    assert kept.read_text(encoding="utf-8") == "keep"


def test_discard_removes_job_directory_and_keeps_experiments_root(tmp_path, engine_root):
    settings = make_settings(tmp_path, engine_root)
    root = settings.data_dir / "agent" / "experiments"
    target = root / JOB_ID
    target.mkdir(parents=True)
    (target / "config.json").write_text("{}", encoding="utf-8")
    other_job = root / "job-other"
    other_job.mkdir()
    kept = other_job / "keep.txt"
    kept.write_text("keep", encoding="utf-8")
    worker = ExperimentMaterializer(StubDrafts({}), settings)

    worker.discard(JOB_ID)

    assert not target.exists()
    assert root.is_dir()
    assert kept.read_text(encoding="utf-8") == "keep"


@WINDOWS_SYMLINK
def test_prepare_and_discard_allow_symlinked_data_dir(tmp_path, engine_root, assets):
    real = tmp_path / "real-data"
    real.mkdir()
    link = tmp_path / "link-data"
    link.symlink_to(real)
    settings = Settings(data_dir=link, engine_root=engine_root, token="c" * 64)
    worker = ExperimentMaterializer(
        StubDrafts({"draft-1": draft_row(engine_scenario(assets))}),
        settings,
    )

    prepared = worker.prepare(job_id=JOB_ID, draft_id="draft-1", baseline_draft_id=None, seeds=[1])

    expected = (real / "agent" / "experiments" / JOB_ID).resolve()
    assert Path(prepared["dir"]) == expected
    assert expected.is_dir()
    worker.discard(JOB_ID)
    assert not expected.exists()


def test_failed_submit_removes_materialized_directory_and_job(tmp_path, assets, engine_root):
    settings = make_settings(tmp_path, engine_root)
    jobs = job_service(tmp_path)
    worker = ExperimentMaterializer(
        StubDrafts({"draft-1": draft_row(engine_scenario(assets))}),
        settings,
    )
    original_prepare = worker.prepare
    prepared: list[str] = []

    def prepare_then_delete(**kwargs):
        result = original_prepare(**kwargs)
        prepared.append(kwargs["job_id"])
        jobs.delete(kwargs["job_id"])
        return result

    worker.prepare = prepare_then_delete
    service = ExperimentService(jobs, FakeEngine(), PLAN, materializer=worker)

    with pytest.raises(ValueError, match="任务创建失败"):
        service.submit({"seeds": [5]}, draft_id="draft-1", **SUBMIT_OPTIONS)

    assert jobs.list()["items"] == []
    assert len(prepared) == 1
    root = (settings.data_dir / "agent" / "experiments").resolve()
    assert not (root / prepared[0]).exists()
    assert list(root.iterdir()) == []
