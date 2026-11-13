"""FMF v2 编解码适配器：魔数、长度头与规范化 JSON 场景。"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from typing import Any

from fm27lab.domain.scenario import normalize_scenario
from fm27lab.ports.fmf import FMF_LENGTH_BYTES, FMF_MAGIC

DECODE_ERROR = "FMF 文件无效"
ENCODE_ERROR = "场景无法编码为 FMF 文件"
HEADER_SIZE = len(FMF_MAGIC) + FMF_LENGTH_BYTES
CONVERSION_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError)
JSON_OPTIONS: dict[str, Any] = {
    "ensure_ascii": False,
    "separators": (",", ":"),
    "sort_keys": True,
    "allow_nan": False,
}


def _reject_constant(text: str) -> None:
    raise ValueError(text)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _payload(data: Any) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError(DECODE_ERROR)
    return bytes(data)


def _restore_roster_trim(
    source: Mapping[str, Any],
    fallback: Mapping[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    source_teams = source.get("teams")
    fallback_teams = fallback.get("teams")
    target_teams = target.get("teams")
    if not isinstance(source_teams, list) or not isinstance(fallback_teams, list):
        return target
    if not isinstance(target_teams, list):
        return target
    for index, team in enumerate(source_teams):
        trim = team.get("roster_trim") if isinstance(team, Mapping) else None
        if not isinstance(trim, Mapping) and index < len(fallback_teams):
            other = fallback_teams[index]
            trim = other.get("roster_trim") if isinstance(other, Mapping) else None
        if isinstance(trim, Mapping) and index < len(target_teams):
            # 归一化会按 23 人名单重算 roster_trim；保留输入来源记录，导出与导入才能逐字段往返一致。
            target_teams[index]["roster_trim"] = copy.deepcopy(dict(trim))
    return target


class FmfCodec:
    """v2 FMF 编解码器，实现 FmfCodec 端口协议。"""

    def encode(self, scenario: Mapping[str, Any]) -> bytes:
        try:
            normalized = normalize_scenario(scenario)
            canonical = _restore_roster_trim(scenario, normalized, normalized)
        except ValueError:
            raise
        except CONVERSION_ERRORS as error:
            raise ValueError(ENCODE_ERROR) from error
        try:
            document = json.dumps(canonical, **JSON_OPTIONS).encode("utf-8")
        except CONVERSION_ERRORS as error:
            raise ValueError(ENCODE_ERROR) from error
        return FMF_MAGIC + len(document).to_bytes(FMF_LENGTH_BYTES, "big") + document

    def decode(self, data: bytes) -> Mapping[str, Any]:
        payload = _payload(data)
        if len(payload) < HEADER_SIZE or payload[: len(FMF_MAGIC)] != FMF_MAGIC:
            raise ValueError(DECODE_ERROR)
        body = payload[HEADER_SIZE:]
        declared = int.from_bytes(payload[len(FMF_MAGIC) : HEADER_SIZE], "big")
        if len(body) != declared:
            raise ValueError(DECODE_ERROR)
        try:
            value = json.loads(
                body.decode("utf-8"),
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
            normalized = normalize_scenario(value)
            return _restore_roster_trim(value, normalized, normalized)
        except CONVERSION_ERRORS as error:
            raise ValueError(DECODE_ERROR) from error
