"""基于 sidecar HTTP 客户端的 MCP 工具面。"""

from __future__ import annotations

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


def _validate_value(schema: Mapping[str, Any], value: Any, label: str) -> None:
    expected = schema.get("type")
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
    elif expected == "integer":
        if not _is_integer(value):
            raise _validation_error(f"参数 {label} 类型必须是整数")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise _validation_error(f"参数 {label} 不能小于 {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise _validation_error(f"参数 {label} 不能大于 {maximum}")
    elif expected == "object":
        if not isinstance(value, dict):
            raise _validation_error(f"参数 {label} 类型必须是对象")
        nested = schema.get("additionalProperties")
        if isinstance(nested, Mapping):
            for key, item in value.items():
                _validate_value(nested, item, f"{label}.{key}")


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
        return client.request_json(
            spec.method, spec.path.format(**path_values), query=query or None, body=body
        )

    return handler
