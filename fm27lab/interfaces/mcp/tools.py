"""基于 sidecar HTTP 客户端的 MCP 工具面。"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from fm27lab.client import SidecarClient, SidecarError
from fm27lab.interfaces.mcp.protocol import McpTool

MAX_OFFSET = 2**31 - 1

_ID: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 64}
_ID_BODY: dict[str, Any] = {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,64}$"}
_NAME_80: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 80}
_NAME_100: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 100}
_KIND: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 64}
_TEXT: dict[str, Any] = {"type": "string", "minLength": 1}
_FILTER: dict[str, Any] = {"type": "string"}
_OBJECT: dict[str, Any] = {"type": "object"}
_OBJECT_MAP: dict[str, Any] = {"type": "object", "additionalProperties": {"type": "object"}}
_WEIGHT: dict[str, Any] = {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1}
_WORKERS: dict[str, Any] = {"type": "integer", "minimum": 1, "maximum": 256, "default": 1}
_TOTAL: dict[str, Any] = {"type": "integer", "minimum": 0, "default": 0}
_COMPLETED: dict[str, Any] = {"type": "integer", "minimum": 0}
_STRING: dict[str, Any] = {"type": "string"}
_BOOL: dict[str, Any] = {"type": "boolean"}
_ANY_JSON: dict[str, Any] = {
    "type": ["array", "boolean", "integer", "null", "number", "object", "string"],
}
_CLUB_UID: dict[str, Any] = {"type": "integer", "minimum": 1, "maximum": MAX_OFFSET}
_WORKERS_BOUNDED: dict[str, Any] = {"type": "integer", "minimum": 1, "maximum": 256}
_CPU_COUNT: dict[str, Any] = {"type": "integer", "minimum": 1}
_BYTES: dict[str, Any] = {"type": "integer", "minimum": 0}
_IDS: dict[str, Any] = {
    "type": "array",
    "items": _ID_BODY,
    "minItems": 1,
    "maxItems": 256,
    "uniqueItems": True,
}
_SEEDS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "integer", "minimum": 0, "maximum": 2**32 - 1},
    "minItems": 1,
}
_VARIANTS: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "minItems": 1}


def _pagination(limit_maximum: int, limit_default: int) -> dict[str, Any]:
    return {
        "limit": {"type": "integer", "minimum": 1, "maximum": limit_maximum, "default": limit_default},
        "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET, "default": 0},
    }


@dataclass(frozen=True, slots=True)
class _ToolSpec:
    name: str
    description: str
    method: str
    path: str
    properties: Mapping[str, Any]
    required: tuple[str, ...] = ()
    query_keys: tuple[str, ...] = ()
    body_keys: tuple[str, ...] | None = None
    require_any_body_key: bool = False
    download: bool = False

    @property
    def path_ids(self) -> tuple[str, ...]:
        return tuple(re.findall(r"{(\w+)}", self.path))

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(self.properties),
            "required": list(self.required),
            "additionalProperties": False,
        }


_SPECS: tuple[_ToolSpec, ...] = (
    _ToolSpec(
        name="pools_list",
        description="分页列出战术池条目",
        method="GET",
        path="/api/pools",
        properties=_pagination(128, 128),
        query_keys=("limit", "offset"),
    ),
    _ToolSpec(
        name="pools_get",
        description="查看单个战术池条目",
        method="GET",
        path="/api/pools/{entry_id}",
        properties={"entry_id": _ID},
        required=("entry_id",),
    ),
    _ToolSpec(
        name="pools_create",
        description="创建战术池条目",
        method="POST",
        path="/api/pools",
        properties={
            "name": _NAME_80,
            "weight": _WEIGHT,
            "tactic": _OBJECT,
            "roster": _OBJECT,
            "id": _ID_BODY,
        },
        required=("name", "tactic"),
        body_keys=("name", "weight", "tactic", "roster", "id"),
    ),
    _ToolSpec(
        name="pools_delete",
        description="删除战术池条目",
        method="DELETE",
        path="/api/pools/{entry_id}",
        properties={"entry_id": _ID},
        required=("entry_id",),
    ),
    _ToolSpec(
        name="drafts_list",
        description="分页列出场景草案",
        method="GET",
        path="/api/drafts",
        properties=_pagination(128, 128),
        query_keys=("limit", "offset"),
    ),
    _ToolSpec(
        name="drafts_get",
        description="查看单个场景草案",
        method="GET",
        path="/api/drafts/{draft_id}",
        properties={"draft_id": _ID},
        required=("draft_id",),
    ),
    _ToolSpec(
        name="drafts_create",
        description="创建场景草案",
        method="POST",
        path="/api/drafts",
        properties={"name": _NAME_80, "scenario": _OBJECT, "source": _OBJECT},
        required=("name", "scenario"),
        body_keys=("name", "scenario", "source"),
    ),
    _ToolSpec(
        name="drafts_update",
        description="更新场景草案",
        method="PATCH",
        path="/api/drafts/{draft_id}",
        properties={"draft_id": _ID, "name": _NAME_80, "scenario": _OBJECT, "source": _OBJECT},
        required=("draft_id",),
        body_keys=("name", "scenario", "source"),
        require_any_body_key=True,
    ),
    _ToolSpec(
        name="drafts_delete",
        description="删除场景草案",
        method="DELETE",
        path="/api/drafts/{draft_id}",
        properties={"draft_id": _ID},
        required=("draft_id",),
    ),
    _ToolSpec(
        name="jobs_list",
        description="分页列出实验任务",
        method="GET",
        path="/api/jobs",
        properties={"status": _FILTER, **_pagination(256, 50)},
        query_keys=("status", "limit", "offset"),
    ),
    _ToolSpec(
        name="jobs_get",
        description="查看单个实验任务",
        method="GET",
        path="/api/jobs/{job_id}",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="jobs_create",
        description="创建实验任务",
        method="POST",
        path="/api/jobs",
        properties={
            "kind": _KIND,
            "name": _NAME_100,
            "config": _OBJECT,
            "workers": _WORKERS,
            "total": _TOTAL,
        },
        required=("kind",),
        body_keys=("kind", "name", "config", "workers", "total"),
    ),
    _ToolSpec(
        name="jobs_update",
        description="更新任务状态、进度或摘要",
        method="PATCH",
        path="/api/jobs/{job_id}",
        properties={
            "job_id": _ID,
            "status": _FILTER,
            "completed": _COMPLETED,
            "summary": _OBJECT,
            "name": _NAME_100,
        },
        required=("job_id",),
        body_keys=("status", "completed", "summary", "name"),
        require_any_body_key=True,
    ),
    _ToolSpec(
        name="jobs_cancel",
        description="取消实验任务",
        method="POST",
        path="/api/jobs/{job_id}/cancel",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="jobs_delete",
        description="删除实验任务及其逐场记录",
        method="DELETE",
        path="/api/jobs/{job_id}",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="jobs_runs",
        description="分页查看任务逐场记录",
        method="GET",
        path="/api/jobs/{job_id}/runs",
        properties={"job_id": _ID, **_pagination(200, 50)},
        required=("job_id",),
        query_keys=("limit", "offset"),
    ),
    _ToolSpec(
        name="saves_list",
        description="分页列出存档",
        method="GET",
        path="/api/saves",
        properties={"status": _FILTER, **_pagination(256, 50)},
        query_keys=("status", "limit", "offset"),
    ),
    _ToolSpec(
        name="saves_get",
        description="查看单个存档",
        method="GET",
        path="/api/saves/{save_id}",
        properties={"save_id": _ID},
        required=("save_id",),
    ),
    _ToolSpec(
        name="saves_create",
        description="登记存档",
        method="POST",
        path="/api/saves",
        properties={
            "source_path": _TEXT,
            "source_sha256": _TEXT,
            "status": _FILTER,
            "stage": _FILTER,
            "metadata": _OBJECT,
        },
        required=("source_path", "source_sha256"),
        body_keys=("source_path", "source_sha256", "status", "stage", "metadata"),
    ),
    _ToolSpec(
        name="saves_update",
        description="更新存档状态或元数据",
        method="PATCH",
        path="/api/saves/{save_id}",
        properties={"save_id": _ID, "status": _FILTER, "stage": _FILTER, "metadata": _OBJECT},
        required=("save_id",),
        body_keys=("status", "stage", "metadata"),
        require_any_body_key=True,
    ),
    _ToolSpec(
        name="saves_delete",
        description="删除存档",
        method="DELETE",
        path="/api/saves/{save_id}",
        properties={"save_id": _ID},
        required=("save_id",),
    ),
    _ToolSpec(
        name="saves_import",
        description="导入存档联赛与俱乐部数据",
        method="POST",
        path="/api/saves/{save_id}/import",
        properties={"save_id": _ID, "leagues": _OBJECT_MAP, "clubs": _OBJECT_MAP, "stage": _FILTER},
        required=("save_id", "leagues", "clubs"),
        body_keys=("leagues", "clubs", "stage"),
    ),
    _ToolSpec(
        name="drafts_attributes",
        description="批量编辑场景草案球员属性",
        method="POST",
        path="/api/drafts/{draft_id}/attributes",
        properties={
            "draft_id": _ID,
            "side": _STRING,
            "scope": _STRING,
            "player_index": {"type": "integer", "minimum": 0},
            "operation": _STRING,
            "params": _OBJECT,
        },
        required=("draft_id", "side", "scope", "operation", "params"),
        body_keys=("side", "scope", "player_index", "operation", "params"),
    ),
    _ToolSpec(
        name="drafts_export_fmf",
        description="导出场景草案为 FMF 文件",
        method="GET",
        path="/api/drafts/{draft_id}/export.fmf",
        properties={"draft_id": _ID},
        required=("draft_id",),
        download=True,
    ),
    _ToolSpec(
        name="drafts_import_fmf",
        description="从 FMF 文件导入场景草案",
        method="POST",
        path="/api/drafts/import-fmf",
        properties={"name": _NAME_80, "content_base64": _STRING, "source": _OBJECT},
        required=("name", "content_base64"),
        body_keys=("name", "content_base64", "source"),
    ),
    _ToolSpec(
        name="drafts_apply_roster",
        description="把存档名单同步到场景草案阵容",
        method="POST",
        path="/api/drafts/{draft_id}/apply-roster",
        properties={
            "draft_id": _ID,
            "save_id": _ID,
            "club_uid": _CLUB_UID,
            "side": _STRING,
            "scope": _STRING,
        },
        required=("draft_id", "save_id", "club_uid", "side", "scope"),
        body_keys=("save_id", "club_uid", "side", "scope"),
    ),
    _ToolSpec(
        name="drafts_undo_roster",
        description="撤销场景草案的阵容同步",
        method="POST",
        path="/api/drafts/{draft_id}/undo-roster",
        properties={"draft_id": _ID},
        required=("draft_id",),
    ),
    _ToolSpec(
        name="jobs_batch_actions",
        description="批量取消或删除实验任务",
        method="POST",
        path="/api/jobs/actions",
        properties={"action": {"type": "string", "enum": ["cancel", "delete"]}, "ids": _IDS},
        required=("action", "ids"),
        body_keys=("action", "ids"),
    ),
    _ToolSpec(
        name="jobs_batch_delete",
        description="批量删除实验任务",
        method="DELETE",
        path="/api/jobs",
        properties={"ids": _IDS},
        required=("ids",),
        body_keys=("ids",),
    ),
    _ToolSpec(
        name="jobs_export",
        description="导出任务结果 CSV",
        method="GET",
        path="/api/jobs/{job_id}/export.csv",
        properties={"job_id": _ID},
        required=("job_id",),
        download=True,
    ),
    _ToolSpec(
        name="jobs_pool_summary",
        description="查看任务客队战术池汇总",
        method="GET",
        path="/api/jobs/{job_id}/pool-summary",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="saves_import_file",
        description="从存档文件导入存档与俱乐部名单",
        method="POST",
        path="/api/saves/import",
        properties={"source_path": _TEXT, "replace": {**_BOOL, "default": False}},
        required=("source_path",),
        body_keys=("source_path", "replace"),
    ),
    _ToolSpec(
        name="saves_squad",
        description="读取存档中的俱乐部名单",
        method="GET",
        path="/api/saves/{save_id}/squad",
        properties={"save_id": _ID, "club_uid": _CLUB_UID},
        required=("save_id", "club_uid"),
        query_keys=("club_uid",),
    ),
    _ToolSpec(
        name="artifacts_list",
        description="分页列出产物",
        method="GET",
        path="/api/artifacts",
        properties={"kind": _STRING, "job_id": _STRING, **_pagination(256, 50)},
        query_keys=("kind", "job_id", "limit", "offset"),
    ),
    _ToolSpec(
        name="artifacts_get",
        description="查看单个产物",
        method="GET",
        path="/api/artifacts/{artifact_id}",
        properties={"artifact_id": _ID},
        required=("artifact_id",),
    ),
    _ToolSpec(
        name="artifacts_content",
        description="下载产物文件内容",
        method="GET",
        path="/api/artifacts/{artifact_id}/content",
        properties={"artifact_id": _ID},
        required=("artifact_id",),
        download=True,
    ),
    _ToolSpec(
        name="artifacts_create",
        description="登记产物",
        method="POST",
        path="/api/artifacts",
        properties={"kind": _STRING, "filename": _STRING, "content_base64": _STRING, "job_id": _STRING},
        required=("kind", "filename", "content_base64"),
        body_keys=("kind", "filename", "content_base64", "job_id"),
    ),
    _ToolSpec(
        name="artifacts_delete",
        description="删除产物",
        method="DELETE",
        path="/api/artifacts/{artifact_id}",
        properties={"artifact_id": _ID},
        required=("artifact_id",),
    ),
    _ToolSpec(
        name="settings_list",
        description="列出设置项",
        method="GET",
        path="/api/settings",
        properties={},
    ),
    _ToolSpec(
        name="settings_get",
        description="查看单个设置项",
        method="GET",
        path="/api/settings/{key}",
        properties={"key": _ID},
        required=("key",),
    ),
    _ToolSpec(
        name="settings_put",
        description="写入设置项",
        method="PUT",
        path="/api/settings/{key}",
        properties={"key": _ID, "value": _ANY_JSON, "note": _STRING},
        required=("key", "value"),
        body_keys=("value", "note"),
    ),
    _ToolSpec(
        name="settings_delete",
        description="删除设置项",
        method="DELETE",
        path="/api/settings/{key}",
        properties={"key": _ID},
        required=("key",),
    ),
    _ToolSpec(
        name="concurrency_check",
        description="并发资源预检",
        method="GET",
        path="/api/concurrency/check",
        properties={
            "workers": _WORKERS_BOUNDED,
            "cpu_count": _CPU_COUNT,
            "available_memory_bytes": _BYTES,
            "free_disk_bytes": _BYTES,
            "allow_oversubscription": _BOOL,
        },
        required=(
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
            "allow_oversubscription",
        ),
        query_keys=(
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
            "allow_oversubscription",
        ),
    ),
    _ToolSpec(
        name="experiments_submit",
        description="提交实验批次",
        method="POST",
        path="/api/experiments",
        properties={
            "name": _NAME_100,
            "seeds": _SEEDS,
            "variants": _VARIANTS,
            "workers": _WORKERS_BOUNDED,
            "cpu_count": _CPU_COUNT,
            "available_memory_bytes": _BYTES,
            "free_disk_bytes": _BYTES,
            "allow_oversubscription": {**_BOOL, "default": False},
        },
        required=(
            "seeds",
            "variants",
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
        ),
        body_keys=(
            "name",
            "seeds",
            "variants",
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
            "allow_oversubscription",
        ),
    ),
    _ToolSpec(
        name="experiments_start",
        description="启动下一个待运行实验",
        method="POST",
        path="/api/experiments/start",
        properties={},
    ),
    _ToolSpec(
        name="experiments_cancel",
        description="取消实验任务",
        method="POST",
        path="/api/experiments/{job_id}/cancel",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="experiments_resume",
        description="恢复实验任务",
        method="POST",
        path="/api/experiments/{job_id}/resume",
        properties={"job_id": _ID},
        required=("job_id",),
    ),
    _ToolSpec(
        name="catalog_snapshot",
        description="读取运行时目录快照",
        method="GET",
        path="/api/catalog",
        properties={},
    ),
)

_TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in _SPECS)


def tool_names() -> tuple[str, ...]:
    return _TOOL_NAMES


def build_tools(client: SidecarClient) -> list[McpTool]:
    return [
        McpTool(
            name=spec.name,
            description=spec.description,
            input_schema=spec.schema(),
            handler=_build_handler(client, spec),
        )
        for spec in _SPECS
    ]


def _validation_error(message: str) -> SidecarError:
    return SidecarError("validation_failed", message)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_kind(value: Any) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _validate_value(schema: Mapping[str, Any], value: Any, label: str) -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        kind = _json_kind(value)
        if kind is None or kind not in expected:
            raise _validation_error(f"参数 {label} 类型无效")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise _validation_error(f"参数 {label} 类型必须是字符串")
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            raise _validation_error(f"参数 {label} 长度不能小于 {minimum}")
        maximum = schema.get("maxLength")
        if maximum is not None and len(value) > maximum:
            raise _validation_error(f"参数 {label} 长度不能大于 {maximum}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            raise _validation_error(f"参数 {label} 格式无效")
        allowed = schema.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            raise _validation_error(f"参数 {label} 不在允许范围内")
    elif expected == "integer":
        if not _is_integer(value):
            raise _validation_error(f"参数 {label} 类型必须是整数")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise _validation_error(f"参数 {label} 不能小于 {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise _validation_error(f"参数 {label} 不能大于 {maximum}")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise _validation_error(f"参数 {label} 类型必须是布尔值")
    elif expected == "object":
        if not isinstance(value, dict):
            raise _validation_error(f"参数 {label} 类型必须是对象")
        nested = schema.get("additionalProperties")
        if isinstance(nested, Mapping):
            for key, item in value.items():
                _validate_value(nested, item, f"{label}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise _validation_error(f"参数 {label} 类型必须是数组")
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            raise _validation_error(f"参数 {label} 至少需要 {minimum} 项")
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > maximum:
            raise _validation_error(f"参数 {label} 不能超过 {maximum} 项")
        if schema.get("uniqueItems"):
            seen: list[Any] = []
            for item in value:
                if item in seen:
                    raise _validation_error(f"参数 {label} 不能包含重复项")
                seen.append(item)
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate_value(items, item, f"{label}[{index}]")


def _validate_arguments(schema: Mapping[str, Any], arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise _validation_error("工具参数必须是 JSON 对象")
    properties = schema.get("properties") or {}
    for key in arguments:
        if key not in properties:
            raise _validation_error(f"未知参数：{key}")
    for key in schema.get("required") or ():
        if key not in arguments:
            raise _validation_error(f"缺少必填参数：{key}")
    for key, value in arguments.items():
        _validate_value(properties[key], value, key)


def _download_envelope(content: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
    return {
        "content_base64": base64.b64encode(content).decode("ascii"),
        "content_type": headers.get("content-type", ""),
        "bytes": len(content),
    }


def _build_handler(client: SidecarClient, spec: _ToolSpec) -> Callable[[dict[str, Any]], dict[str, Any]]:
    schema = spec.schema()

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        _validate_arguments(schema, arguments)
        body = None
        if spec.body_keys is not None:
            body = {key: arguments[key] for key in spec.body_keys if key in arguments}
            if spec.require_any_body_key and not body:
                raise _validation_error("至少需要提供一项更新字段")
        query = {
            key: arguments[key] for key in spec.query_keys if key in arguments and arguments[key] is not None
        }
        path_values = {name: quote(arguments[name], safe="") for name in spec.path_ids}
        path = spec.path.format(**path_values)
        if spec.download:
            content, headers = client.request_bytes(spec.method, path, query=query or None, accept="*/*")
            return _download_envelope(content, headers)
        return client.request_json(spec.method, path, query=query or None, body=body)

    return handler
