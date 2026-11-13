from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import typer

import fm27lab
from fm27lab.client import SidecarClient, SidecarError, discover_endpoint
from fm27lab.config import Settings
from fm27lab.interfaces.mcp.protocol import McpServer
from fm27lab.interfaces.mcp.tools import build_tools
from fm27lab.sidecar import run

app = typer.Typer(add_completion=False, no_args_is_help=True)
pools_app = typer.Typer(add_completion=False, no_args_is_help=True, help="战术池条目")
drafts_app = typer.Typer(add_completion=False, no_args_is_help=True, help="场景草案")
jobs_app = typer.Typer(add_completion=False, no_args_is_help=True, help="实验任务")
saves_app = typer.Typer(add_completion=False, no_args_is_help=True, help="存档库")

app.add_typer(pools_app, name="pools")
app.add_typer(drafts_app, name="drafts")
app.add_typer(jobs_app, name="jobs")
app.add_typer(saves_app, name="saves")


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
        engine_root=engine_root or base.engine_root,
        token=token or base.token,
        host=base.host if host is None else host,
        port=base.port if port is None else port,
        dev=base.dev if dev is None else dev,
    )
    raise typer.Exit(run(settings))


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


def main() -> None:
    app()
