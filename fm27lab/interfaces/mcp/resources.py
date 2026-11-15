"""MCP 资源：以只读 JSON 视图暴露 sidecar 列表接口。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fm27lab.client import SidecarClient
from fm27lab.interfaces.mcp.protocol import McpResource

DRAFTS_LIMIT = 128
POOLS_LIMIT = 128
JOBS_LIMIT = 256
SAVES_LIMIT = 256


@dataclass(frozen=True, slots=True)
class _ResourceSpec:
    uri: str
    name: str
    description: str
    path: str
    limit: int

    def read(self, client: SidecarClient) -> str:
        payload = client.request_json("GET", self.path, query={"limit": self.limit, "offset": 0})
        return _compact_json(payload)


_SPECS: tuple[_ResourceSpec, ...] = (
    _ResourceSpec("fm27lab://drafts", "drafts", "场景草案分页列表", "/api/drafts", DRAFTS_LIMIT),
    _ResourceSpec("fm27lab://pools", "pools", "战术池条目分页列表", "/api/pools", POOLS_LIMIT),
    _ResourceSpec("fm27lab://jobs", "jobs", "实验任务分页列表", "/api/jobs", JOBS_LIMIT),
    _ResourceSpec("fm27lab://saves", "saves", "存档分页列表", "/api/saves", SAVES_LIMIT),
)


def build_resources(client: SidecarClient) -> list[McpResource]:
    return [
        McpResource(
            uri=spec.uri,
            name=spec.name,
            description=spec.description,
            mime_type="application/json",
            handler=_reader(client, spec),
        )
        for spec in _SPECS
    ]


def _reader(client: SidecarClient, spec: _ResourceSpec) -> Callable[[], str]:
    def handler() -> str:
        return spec.read(client)

    return handler


def _compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
