from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import typer

import fm27lab
from fm27lab.client import SidecarClient, SidecarError, discover_endpoint
from fm27lab.config import Settings
from fm27lab.interfaces.mcp.prompts import build_prompts
from fm27lab.interfaces.mcp.protocol import McpServer
from fm27lab.interfaces.mcp.resources import build_resources
from fm27lab.interfaces.mcp.tools import build_tools
from fm27lab.sidecar import run

app = typer.Typer(add_completion=False, no_args_is_help=True)
pools_app = typer.Typer(add_completion=False, no_args_is_help=True, help="战术池条目")
drafts_app = typer.Typer(add_completion=False, no_args_is_help=True, help="场景草案")
jobs_app = typer.Typer(add_completion=False, no_args_is_help=True, help="实验任务")
saves_app = typer.Typer(add_completion=False, no_args_is_help=True, help="存档库")
artifacts_app = typer.Typer(add_completion=False, no_args_is_help=True, help="产物")
settings_app = typer.Typer(add_completion=False, no_args_is_help=True, help="设置")
concurrency_app = typer.Typer(add_completion=False, no_args_is_help=True, help="并发资源预检")
experiments_app = typer.Typer(add_completion=False, no_args_is_help=True, help="实验调度")
catalog_app = typer.Typer(add_completion=False, no_args_is_help=True, help="运行时目录")
results_app = typer.Typer(add_completion=False, no_args_is_help=True, help="结果对比")
system_app = typer.Typer(add_completion=False, no_args_is_help=True, help="宿主资源")

app.add_typer(pools_app, name="pools")
app.add_typer(drafts_app, name="drafts")
app.add_typer(jobs_app, name="jobs")
app.add_typer(saves_app, name="saves")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(settings_app, name="settings")
app.add_typer(concurrency_app, name="concurrency")
app.add_typer(experiments_app, name="experiments")
app.add_typer(catalog_app, name="catalog")
app.add_typer(results_app, name="results")
app.add_typer(system_app, name="system")


@app.callback()
def configure(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        help="数据目录；省略时读取 FM27LAB_DATA 或平台默认路径",
    ),
) -> None:
    """通过 loopback sidecar 管理战术池、草案、任务与存档。"""
    ctx.obj = {"data_dir": data_dir.expanduser().resolve() if data_dir is not None else None}


@app.command()
def version() -> None:
    """Print the sidecar version and API name."""
    typer.echo(f"{fm27lab.__version__} {fm27lab.API_VERSION}")


@app.command()
def serve(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Data directory"),
    engine_root: Path | None = typer.Option(None, "--engine-root", help="Engine workspace"),
    game_root: Path | None = typer.Option(None, "--game-root", help="Game installation directory"),
    host: str | None = typer.Option(None, "--host", help="Loopback host"),
    port: int | None = typer.Option(None, "--port", help="Port; 0 selects a free port"),
    token: str | None = typer.Option(None, "--token", help="Bearer token; generated when omitted"),
    dev: bool | None = typer.Option(None, "--dev/--no-dev", help="Allow the Vite development origin"),
) -> None:
    """Run the local HTTP sidecar until shutdown."""
    base = Settings.from_env()
    root_data_dir = ctx.obj.get("data_dir") if isinstance(ctx.obj, dict) else None
    settings = Settings.create(
        data_dir=data_dir or root_data_dir or base.data_dir,
        token=token or base.token,
        host=base.host if host is None else host,
        port=base.port if port is None else port,
        dev=base.dev if dev is None else dev,
    )
    explicit: dict[str, Path] = {}
    if engine_root is not None:
        explicit["engine_root"] = engine_root
    if game_root is not None:
        explicit["game_root"] = game_root
    raise typer.Exit(run(settings) if not explicit else run(settings, **explicit))


@app.command()
def mcp(ctx: typer.Context) -> None:
    """以 MCP stdio 服务暴露 sidecar 工具。"""
    raise typer.Exit(run_mcp(_resolve_data_dir(ctx), sys.stdin.buffer, sys.stdout.buffer))


def _resolve_data_dir(ctx: typer.Context) -> Path:
    override = ctx.obj.get("data_dir") if isinstance(ctx.obj, dict) else None
    if override is not None:
        return Path(override)
    try:
        return Settings.from_env().data_dir
    except ValueError as error:
        raise typer.BadParameter(f"数据目录无效：{error}", param_hint="--data-dir") from None


def _client_for(data_dir: Path) -> SidecarClient:
    endpoint = discover_endpoint(data_dir)
    return SidecarClient(str(endpoint["url"]), str(endpoint["token"]))


MCP_SERVER_NAME = "fm27lab"
MCP_READY_PATH = "/api/health"


def _ready_client(data_dir: Path) -> SidecarClient:
    client = _client_for(data_dir)
    client.request_json("GET", MCP_READY_PATH)
    return client


def run_mcp(
    data_dir: Path,
    instream: BinaryIO | TextIO,
    outstream: BinaryIO | TextIO,
) -> int:
    try:
        client = _ready_client(Path(data_dir))
    except SidecarError as error:
        sys.stderr.write(f"无法启动 MCP 服务：{error.code}: {error.message}\n")
        sys.stderr.flush()
        return 1
    server = McpServer(
        name=MCP_SERVER_NAME,
        version=fm27lab.__version__,
        tools=build_tools(client),
        resources=build_resources(client),
        prompts=build_prompts(),
    )
    server.serve(instream, outstream)
    return 0


def _invoke(ctx: typer.Context, request: Callable[[SidecarClient], Any]) -> Any:
    try:
        return request(_client_for(_resolve_data_dir(ctx)))
    except SidecarError as error:
        typer.echo(f"{error.code}: {error.message}", err=True)
        raise typer.Exit(1) from error


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _json_value(raw: str, name: str) -> Any:
    text = raw
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise typer.BadParameter(f"无法读取 {name} 文件：{path}（{error}）") from None
    try:
        return json.loads(text)
    except ValueError as error:
        raise typer.BadParameter(f"{name} 必须是有效的 JSON：{error}") from None


def _json_object(raw: str | None, name: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _json_value(raw, name)
    if not isinstance(value, dict):
        raise typer.BadParameter(f"{name} 必须是 JSON 对象", param_hint=f"--{name}")
    return value


def _delete(ctx: typer.Context, path: str) -> None:
    _invoke(ctx, lambda client: client.request_json("DELETE", path))
    _emit({"deleted": True})


def _changes(**values: Any) -> dict[str, Any]:
    changes = {key: value for key, value in values.items() if value is not None}
    if not changes:
        raise typer.BadParameter("至少需要提供一项更新字段")
    return changes


def _json_array(raw: str, name: str) -> list[Any]:
    value = _json_value(raw, name)
    if not isinstance(value, list):
        raise typer.BadParameter(f"{name} 必须是 JSON 数组", param_hint=f"--{name}")
    return value


def _base64_file(raw: str, name: str) -> str:
    path = Path(raw).expanduser()
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise typer.BadParameter(f"无法读取 {name} 文件：{path}（{error}）") from None
    return base64.b64encode(payload).decode("ascii")


def _download(
    ctx: typer.Context,
    request: Callable[[SidecarClient], tuple[bytes, dict[str, str]]],
    output: Path,
) -> None:
    payload, _headers = _invoke(ctx, request)
    target = output.expanduser()
    try:
        target.write_bytes(payload)
    except OSError as error:
        typer.echo(f"无法写入文件：{target}（{error}）", err=True)
        raise typer.Exit(1) from error
    _emit({"path": str(target), "bytes": len(payload)})


POOLS_LIMIT = typer.Option(128, "--limit", min=1, max=128, help="每页数量")
POOLS_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
DRAFTS_LIMIT = typer.Option(128, "--limit", min=1, max=128, help="每页数量")
DRAFTS_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
JOBS_LIMIT = typer.Option(50, "--limit", min=1, max=256, help="每页数量")
JOBS_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
RUNS_LIMIT = typer.Option(50, "--limit", min=1, max=200, help="每页数量")
RUNS_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
SAVES_LIMIT = typer.Option(50, "--limit", min=1, max=256, help="每页数量")
SAVES_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
ARTIFACTS_LIMIT = typer.Option(50, "--limit", min=1, max=256, help="每页数量")
ARTIFACTS_OFFSET = typer.Option(0, "--offset", min=0, help="分页偏移")
JOB_BATCH_ACTIONS = frozenset({"cancel", "delete"})


@pools_app.command("list")
def pools_list(
    ctx: typer.Context,
    limit: int = POOLS_LIMIT,
    offset: int = POOLS_OFFSET,
) -> None:
    """列出战术池条目。"""
    query = {"limit": limit, "offset": offset}
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/pools", query=query)))


@pools_app.command("get")
def pools_get(ctx: typer.Context, entry_id: str = typer.Argument(..., help="条目 ID")) -> None:
    """查看单个战术池条目。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/pools/{entry_id}")))


@pools_app.command("create")
def pools_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="条目名称"),
    tactic: str = typer.Option(..., "--tactic", help="战术 JSON，可用 @文件"),
    weight: int = typer.Option(1, "--weight", min=1, max=1000, help="抽取权重"),
    roster: str | None = typer.Option(None, "--roster", help="名单 JSON，可用 @文件"),
    entry_id: str | None = typer.Option(None, "--id", help="条目 ID"),
) -> None:
    """创建战术池条目。"""
    body: dict[str, Any] = {
        "name": name,
        "weight": weight,
        "tactic": _json_object(tactic, "tactic"),
    }
    roster_value = _json_object(roster, "roster")
    if roster_value is not None:
        body["roster"] = roster_value
    if entry_id is not None:
        body["id"] = entry_id
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/pools", body=body)))


@pools_app.command("delete")
def pools_delete(ctx: typer.Context, entry_id: str = typer.Argument(..., help="条目 ID")) -> None:
    """删除战术池条目。"""
    _delete(ctx, f"/api/pools/{entry_id}")


@drafts_app.command("list")
def drafts_list(
    ctx: typer.Context,
    limit: int = DRAFTS_LIMIT,
    offset: int = DRAFTS_OFFSET,
) -> None:
    """列出场景草案。"""
    query = {"limit": limit, "offset": offset}
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/drafts", query=query)))


@drafts_app.command("get")
def drafts_get(ctx: typer.Context, draft_id: str = typer.Argument(..., help="草案 ID")) -> None:
    """查看单个草案。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/drafts/{draft_id}")))


@drafts_app.command("create")
def drafts_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="草案名称"),
    scenario: str = typer.Option(..., "--scenario", help="场景 JSON，可用 @文件"),
    source: str | None = typer.Option(None, "--source", help="来源 JSON，可用 @文件"),
) -> None:
    """创建场景草案。"""
    body: dict[str, Any] = {"name": name, "scenario": _json_object(scenario, "scenario")}
    source_value = _json_object(source, "source")
    if source_value is not None:
        body["source"] = source_value
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/drafts", body=body)))


@drafts_app.command("update")
def drafts_update(
    ctx: typer.Context,
    draft_id: str = typer.Argument(..., help="草案 ID"),
    name: str | None = typer.Option(None, "--name", help="草案名称"),
    scenario: str | None = typer.Option(None, "--scenario", help="场景 JSON，可用 @文件"),
    source: str | None = typer.Option(None, "--source", help="来源 JSON，可用 @文件"),
) -> None:
    """更新场景草案。"""
    changes = _changes(
        name=name,
        scenario=_json_object(scenario, "scenario"),
        source=_json_object(source, "source"),
    )
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("PATCH", f"/api/drafts/{draft_id}", body=changes),
        )
    )


@drafts_app.command("delete")
def drafts_delete(ctx: typer.Context, draft_id: str = typer.Argument(..., help="草案 ID")) -> None:
    """删除场景草案。"""
    _delete(ctx, f"/api/drafts/{draft_id}")


@jobs_app.command("list")
def jobs_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status", help="按状态过滤"),
    limit: int = JOBS_LIMIT,
    offset: int = JOBS_OFFSET,
) -> None:
    """列出实验任务。"""
    query = {"status": status, "limit": limit, "offset": offset}
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/jobs", query=query)))


@jobs_app.command("get")
def jobs_get(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """查看单个任务。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/jobs/{job_id}")))


@jobs_app.command("create")
def jobs_create(
    ctx: typer.Context,
    kind: str = typer.Option(..., "--kind", help="任务类型"),
    name: str | None = typer.Option(None, "--name", help="任务名称"),
    config: str | None = typer.Option(None, "--config", help="任务配置 JSON，可用 @文件"),
    workers: int = typer.Option(1, "--workers", min=1, max=256, help="并行数"),
    total: int = typer.Option(0, "--total", min=0, help="总场数"),
) -> None:
    """创建实验任务。"""
    body: dict[str, Any] = {
        "kind": kind,
        "config": _json_object(config, "config") or {},
        "workers": workers,
        "total": total,
    }
    if name is not None:
        body["name"] = name
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/jobs", body=body)))


@jobs_app.command("update")
def jobs_update(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="任务 ID"),
    status: str | None = typer.Option(None, "--status", help="任务状态"),
    completed: int | None = typer.Option(None, "--completed", min=0, help="已完成场数"),
    summary: str | None = typer.Option(None, "--summary", help="任务摘要 JSON，可用 @文件"),
    name: str | None = typer.Option(None, "--name", help="任务名称"),
) -> None:
    """更新任务状态、进度或摘要。"""
    changes = _changes(
        status=status,
        completed=completed,
        summary=_json_object(summary, "summary"),
        name=name,
    )
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("PATCH", f"/api/jobs/{job_id}", body=changes),
        )
    )


@jobs_app.command("cancel")
def jobs_cancel(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """取消任务。"""
    _emit(_invoke(ctx, lambda client: client.request_json("POST", f"/api/jobs/{job_id}/cancel")))


@jobs_app.command("delete")
def jobs_delete(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """删除任务及其逐场记录。"""
    _delete(ctx, f"/api/jobs/{job_id}")


@jobs_app.command("runs")
def jobs_runs(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="任务 ID"),
    limit: int = RUNS_LIMIT,
    offset: int = RUNS_OFFSET,
) -> None:
    """分页查看任务逐场记录。"""
    query = {"limit": limit, "offset": offset}
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("GET", f"/api/jobs/{job_id}/runs", query=query),
        )
    )


@jobs_app.command("summary")
def jobs_summary(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="任务 ID"),
    side: int = typer.Option(0, "--side", min=0, max=1, help="统计视角；0 主队，1 客队"),
) -> None:
    """显示任务结果汇总。"""
    query = {"side": side}
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("GET", f"/api/jobs/{job_id}/summary", query=query),
        )
    )


@saves_app.command("list")
def saves_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status", help="按状态过滤"),
    limit: int = SAVES_LIMIT,
    offset: int = SAVES_OFFSET,
) -> None:
    """列出存档。"""
    query = {"status": status, "limit": limit, "offset": offset}
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/saves", query=query)))


@saves_app.command("get")
def saves_get(ctx: typer.Context, save_id: str = typer.Argument(..., help="存档 ID")) -> None:
    """查看单个存档。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/saves/{save_id}")))


@saves_app.command("create")
def saves_create(
    ctx: typer.Context,
    source_path: str = typer.Option(..., "--source-path", help="存档源路径"),
    source_sha256: str = typer.Option(..., "--source-sha256", help="存档源 SHA-256"),
    status: str | None = typer.Option(None, "--status", help="初始状态"),
    stage: str | None = typer.Option(None, "--stage", help="导入阶段"),
    metadata: str | None = typer.Option(None, "--metadata", help="元数据 JSON，可用 @文件"),
) -> None:
    """登记存档。"""
    body: dict[str, Any] = {"source_path": source_path, "source_sha256": source_sha256}
    if status is not None:
        body["status"] = status
    if stage is not None:
        body["stage"] = stage
    metadata_value = _json_object(metadata, "metadata")
    if metadata_value is not None:
        body["metadata"] = metadata_value
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/saves", body=body)))


@saves_app.command("update")
def saves_update(
    ctx: typer.Context,
    save_id: str = typer.Argument(..., help="存档 ID"),
    status: str | None = typer.Option(None, "--status", help="存档状态"),
    stage: str | None = typer.Option(None, "--stage", help="导入阶段"),
    metadata: str | None = typer.Option(None, "--metadata", help="元数据 JSON，可用 @文件"),
) -> None:
    """更新存档状态或元数据。"""
    changes = _changes(
        status=status,
        stage=stage,
        metadata=_json_object(metadata, "metadata"),
    )
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("PATCH", f"/api/saves/{save_id}", body=changes),
        )
    )


@saves_app.command("delete")
def saves_delete(ctx: typer.Context, save_id: str = typer.Argument(..., help="存档 ID")) -> None:
    """删除存档。"""
    _delete(ctx, f"/api/saves/{save_id}")


@saves_app.command("import")
def saves_import(
    ctx: typer.Context,
    save_id: str = typer.Argument(..., help="存档 ID"),
    leagues: str = typer.Option(..., "--leagues", help="联赛 JSON，可用 @文件"),
    clubs: str = typer.Option(..., "--clubs", help="俱乐部 JSON，可用 @文件"),
    stage: str | None = typer.Option(None, "--stage", help="导入阶段"),
) -> None:
    """导入存档联赛与俱乐部数据。"""
    body: dict[str, Any] = {
        "leagues": _json_object(leagues, "leagues"),
        "clubs": _json_object(clubs, "clubs"),
    }
    if stage is not None:
        body["stage"] = stage
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("POST", f"/api/saves/{save_id}/import", body=body),
        )
    )


@drafts_app.command("attributes")
def drafts_attributes(
    ctx: typer.Context,
    draft_id: str = typer.Argument(..., help="草案 ID"),
    side: str = typer.Option(..., "--side", help="球队视角"),
    scope: str = typer.Option(..., "--scope", help="编辑范围"),
    operation: str = typer.Option(..., "--operation", help="属性操作"),
    params: str = typer.Option(..., "--params", help="操作参数 JSON，可用 @文件"),
    player_index: int | None = typer.Option(None, "--player-index", min=0, help="球员序号"),
) -> None:
    """批量编辑场景草案球员属性。"""
    body: dict[str, Any] = {
        "side": side,
        "scope": scope,
        "operation": operation,
        "params": _json_object(params, "params"),
    }
    if player_index is not None:
        body["player_index"] = player_index
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("POST", f"/api/drafts/{draft_id}/attributes", body=body),
        )
    )


@drafts_app.command("export-fmf")
def drafts_export_fmf(
    ctx: typer.Context,
    draft_id: str = typer.Argument(..., help="草案 ID"),
    output: Path = typer.Option(..., "--output", help="写入的文件路径"),
) -> None:
    """导出场景草案为 FMF 文件。"""
    _download(
        ctx,
        lambda client: client.request_bytes("GET", f"/api/drafts/{draft_id}/export.fmf"),
        output,
    )


@drafts_app.command("import-fmf")
def drafts_import_fmf(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="草案名称"),
    file_path: str = typer.Option(..., "--file", help="FMF 文件路径"),
    source: str | None = typer.Option(None, "--source", help="来源 JSON，可用 @文件"),
) -> None:
    """从 FMF 文件导入场景草案。"""
    body: dict[str, Any] = {"name": name, "content_base64": _base64_file(file_path, "FMF")}
    source_value = _json_object(source, "source")
    if source_value is not None:
        body["source"] = source_value
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/drafts/import-fmf", body=body)))


@drafts_app.command("import-fmf-file")
def drafts_import_fmf_file(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="本地 FMF 文件路径"),
    name: str | None = typer.Option(None, "--name", help="草案名称"),
) -> None:
    """从本地文件路径导入场景草案。"""
    body: dict[str, Any] = {"source_path": file}
    if name is not None:
        body["name"] = name
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("POST", "/api/drafts/import-fmf-file", body=body),
        )
    )


@drafts_app.command("apply-roster")
def drafts_apply_roster(
    ctx: typer.Context,
    draft_id: str = typer.Argument(..., help="草案 ID"),
    save_id: str = typer.Option(..., "--save-id", help="存档 ID"),
    club_uid: int = typer.Option(..., "--club-uid", min=1, help="俱乐部 UID"),
    side: str = typer.Option(..., "--side", help="球队视角"),
    scope: str = typer.Option(..., "--scope", help="应用范围"),
) -> None:
    """把存档名单同步到场景草案阵容。"""
    body = {"save_id": save_id, "club_uid": club_uid, "side": side, "scope": scope}
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("POST", f"/api/drafts/{draft_id}/apply-roster", body=body),
        )
    )


@drafts_app.command("undo-roster")
def drafts_undo_roster(ctx: typer.Context, draft_id: str = typer.Argument(..., help="草案 ID")) -> None:
    """撤销场景草案的阵容同步。"""
    _emit(_invoke(ctx, lambda client: client.request_json("POST", f"/api/drafts/{draft_id}/undo-roster")))


@jobs_app.command("batch-action")
def jobs_batch_actions(
    ctx: typer.Context,
    action: str = typer.Option(..., "--action", help="批量动作：cancel 或 delete"),
    ids: list[str] = typer.Option(..., "--ids", help="任务 ID，可重复"),
) -> None:
    """批量取消或删除实验任务。"""
    if action not in JOB_BATCH_ACTIONS:
        raise typer.BadParameter(f"批量动作必须是 cancel 或 delete：{action}", param_hint="--action")
    body = {"action": action, "ids": ids}
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/jobs/actions", body=body)))


@jobs_app.command("batch-delete")
def jobs_batch_delete(
    ctx: typer.Context,
    ids: list[str] = typer.Option(..., "--ids", help="任务 ID，可重复"),
) -> None:
    """批量删除实验任务。"""
    body = {"ids": ids}
    _emit(_invoke(ctx, lambda client: client.request_json("DELETE", "/api/jobs", body=body)))


@jobs_app.command("export")
def jobs_export(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="任务 ID"),
    output: Path = typer.Option(..., "--output", help="写入的文件路径"),
) -> None:
    """导出任务结果 CSV。"""
    _download(ctx, lambda client: client.request_bytes("GET", f"/api/jobs/{job_id}/export.csv"), output)


@jobs_app.command("pool-summary")
def jobs_pool_summary(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """查看任务客队战术池汇总。"""
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("GET", f"/api/jobs/{job_id}/pool-summary"),
        )
    )


@saves_app.command("import-file")
def saves_import_file(
    ctx: typer.Context,
    source_path: str = typer.Option(..., "--source-path", help="存档文件路径"),
    replace: bool = typer.Option(False, "--replace/--no-replace", help="覆盖已有存档"),
) -> None:
    """从存档文件导入存档与俱乐部名单。"""
    body = {"source_path": source_path, "replace": replace}
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/saves/import", body=body)))


@saves_app.command("squad")
def saves_squad(
    ctx: typer.Context,
    save_id: str = typer.Argument(..., help="存档 ID"),
    club_uid: int = typer.Option(..., "--club-uid", min=1, max=2**31 - 1, help="俱乐部 UID"),
) -> None:
    """读取存档中的俱乐部名单。"""
    query = {"club_uid": club_uid}
    _emit(
        _invoke(
            ctx,
            lambda client: client.request_json("GET", f"/api/saves/{save_id}/squad", query=query),
        )
    )


@artifacts_app.command("list")
def artifacts_list(
    ctx: typer.Context,
    kind: str | None = typer.Option(None, "--kind", help="按类型过滤"),
    job_id: str | None = typer.Option(None, "--job-id", help="按任务 ID 过滤"),
    limit: int = ARTIFACTS_LIMIT,
    offset: int = ARTIFACTS_OFFSET,
) -> None:
    """分页列出产物。"""
    query = {"kind": kind, "job_id": job_id, "limit": limit, "offset": offset}
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/artifacts", query=query)))


@artifacts_app.command("get")
def artifacts_get(ctx: typer.Context, artifact_id: str = typer.Argument(..., help="产物 ID")) -> None:
    """查看单个产物。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/artifacts/{artifact_id}")))


@artifacts_app.command("content")
def artifacts_content(
    ctx: typer.Context,
    artifact_id: str = typer.Argument(..., help="产物 ID"),
    output: Path = typer.Option(..., "--output", help="写入的文件路径"),
) -> None:
    """下载产物文件内容。"""
    _download(
        ctx,
        lambda client: client.request_bytes("GET", f"/api/artifacts/{artifact_id}/content"),
        output,
    )


@artifacts_app.command("create")
def artifacts_create(
    ctx: typer.Context,
    kind: str = typer.Option(..., "--kind", help="产物类型"),
    filename: str = typer.Option(..., "--filename", help="文件名"),
    file_path: str = typer.Option(..., "--file", help="产物内容文件路径"),
    job_id: str | None = typer.Option(None, "--job-id", help="关联任务 ID"),
) -> None:
    """登记产物。"""
    body: dict[str, Any] = {
        "kind": kind,
        "filename": filename,
        "content_base64": _base64_file(file_path, "产物"),
    }
    if job_id is not None:
        body["job_id"] = job_id
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/artifacts", body=body)))


@artifacts_app.command("delete")
def artifacts_delete(ctx: typer.Context, artifact_id: str = typer.Argument(..., help="产物 ID")) -> None:
    """删除产物。"""
    _delete(ctx, f"/api/artifacts/{artifact_id}")


@settings_app.command("list")
def settings_list(ctx: typer.Context) -> None:
    """列出设置项。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/settings")))


@settings_app.command("get")
def settings_get(ctx: typer.Context, key: str = typer.Argument(..., help="设置键")) -> None:
    """查看单个设置项。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", f"/api/settings/{key}")))


@settings_app.command("put")
def settings_put(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="设置键"),
    value: str = typer.Option(..., "--value", help="设置值 JSON，可用 @文件"),
    note: str | None = typer.Option(None, "--note", help="备注"),
) -> None:
    """写入设置项。"""
    body: dict[str, Any] = {"value": _json_value(value, "value")}
    if note is not None:
        body["note"] = note
    _emit(_invoke(ctx, lambda client: client.request_json("PUT", f"/api/settings/{key}", body=body)))


@settings_app.command("delete")
def settings_delete(ctx: typer.Context, key: str = typer.Argument(..., help="设置键")) -> None:
    """删除设置项。"""
    _delete(ctx, f"/api/settings/{key}")


@concurrency_app.command("check")
def concurrency_check(
    ctx: typer.Context,
    workers: int = typer.Option(..., "--workers", min=1, max=256, help="并行数"),
    cpu_count: int = typer.Option(..., "--cpu-count", min=1, help="CPU 数量"),
    available_memory_bytes: int = typer.Option(..., "--available-memory-bytes", min=0, help="可用内存字节"),
    free_disk_bytes: int = typer.Option(..., "--free-disk-bytes", min=0, help="空闲磁盘字节"),
    allow_oversubscription: bool = typer.Option(
        False,
        "--allow-oversubscription/--no-allow-oversubscription",
        help="允许超额订阅",
    ),
) -> None:
    """并发资源预检。"""
    query = {
        "workers": workers,
        "cpu_count": cpu_count,
        "available_memory_bytes": available_memory_bytes,
        "free_disk_bytes": free_disk_bytes,
        "allow_oversubscription": allow_oversubscription,
    }
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/concurrency/check", query=query)))


def _resolved_resources(
    ctx: typer.Context,
    cpu_count: int | None,
    available_memory_bytes: int | None,
    free_disk_bytes: int | None,
) -> dict[str, int]:
    def resolve(client: SidecarClient) -> dict[str, int]:
        given = {
            "cpu_count": cpu_count,
            "available_memory_bytes": available_memory_bytes,
            "free_disk_bytes": free_disk_bytes,
        }
        probed: dict[str, Any] = {}
        if any(value is None for value in given.values()):
            payload = client.request_json("GET", "/api/system/resources")
            if not isinstance(payload, dict):
                raise SidecarError("invalid_response", "宿主资源响应不是对象")
            probed = payload
        resolved: dict[str, int] = {}
        for name, value in given.items():
            if value is not None:
                resolved[name] = value
                continue
            fallback = probed.get(name)
            minimum = 1 if name == "cpu_count" else 0
            if isinstance(fallback, bool) or not isinstance(fallback, int) or fallback < minimum:
                raise SidecarError("invalid_response", f"宿主资源字段无效：{name}")
            resolved[name] = fallback
        return resolved

    return _invoke(ctx, resolve)


@experiments_app.command("submit")
def experiments_submit(
    ctx: typer.Context,
    draft_id: str = typer.Option(..., "--draft-id", help="草案标识"),
    seed: list[int] = typer.Option(..., "--seed", help="随机种子，可重复"),
    workers: int = typer.Option(..., "--workers", min=1, max=256, help="并行数"),
    cpu_count: int | None = typer.Option(None, "--cpu-count", min=1, help="缺省时自动探测 CPU 数量"),
    available_memory_bytes: int | None = typer.Option(
        None,
        "--available-memory-bytes",
        min=0,
        help="缺省时自动探测 可用内存字节",
    ),
    free_disk_bytes: int | None = typer.Option(
        None,
        "--free-disk-bytes",
        min=0,
        help="缺省时自动探测 空闲磁盘字节",
    ),
    baseline_draft_id: str | None = typer.Option(None, "--baseline-draft-id", help="基线草案标识"),
    name: str | None = typer.Option(None, "--name", help="批次名称"),
    allow_oversubscription: bool = typer.Option(
        False,
        "--allow-oversubscription/--no-allow-oversubscription",
        help="允许超额订阅",
    ),
) -> None:
    """提交实验批次。"""
    body: dict[str, Any] = {
        "seeds": list(seed),
        "draft_id": draft_id,
        "workers": workers,
        "allow_oversubscription": allow_oversubscription,
        **_resolved_resources(ctx, cpu_count, available_memory_bytes, free_disk_bytes),
    }
    if baseline_draft_id is not None:
        body["baseline_draft_id"] = baseline_draft_id
    if name is not None:
        body["name"] = name
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/experiments", body=body)))


@experiments_app.command("start")
def experiments_start(ctx: typer.Context) -> None:
    """启动下一个待运行实验。"""
    _emit(_invoke(ctx, lambda client: client.request_json("POST", "/api/experiments/start")))


@experiments_app.command("cancel")
def experiments_cancel(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """取消实验任务。"""
    _emit(_invoke(ctx, lambda client: client.request_json("POST", f"/api/experiments/{job_id}/cancel")))


@experiments_app.command("resume")
def experiments_resume(ctx: typer.Context, job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """恢复实验任务。"""
    _emit(_invoke(ctx, lambda client: client.request_json("POST", f"/api/experiments/{job_id}/resume")))


@catalog_app.command("show")
def catalog_show(ctx: typer.Context) -> None:
    """读取运行时目录快照。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/catalog")))


@system_app.command("resources")
def system_resources(ctx: typer.Context) -> None:
    """探测宿主可用资源并给出推荐并行数。"""
    _emit(_invoke(ctx, lambda client: client.request_json("GET", "/api/system/resources")))


@results_app.command("compare")
def results_compare(
    ctx: typer.Context,
    baseline: str = typer.Option(..., "--baseline", help="基线任务 ID"),
    candidate: list[str] = typer.Option(..., "--candidate", help="候选任务 ID，可重复"),
    variant: str = typer.Option("B", "--variant", help="变体 A 或 B"),
    side: int = typer.Option(0, "--side", min=0, max=1, help="统计视角 0 主队 / 1 客队"),
    reps: int = typer.Option(2000, "--reps", min=1, max=20000, help="bootstrap 次数"),
) -> None:
    """跨任务同种子配对比较。"""
    body: dict[str, Any] = {
        "baseline_job_id": baseline,
        "candidate_job_ids": candidate,
        "variant": variant,
        "side": side,
        "reps": reps,
    }
    value = _invoke(
        ctx, lambda client: client.request_json("POST", "/api/results/compare", body=body)
    )
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    app()
