"""FMF v2 编解码端口与适配器契约测试。"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from fm27lab.adapters.fmf import FmfCodec
from fm27lab.adapters.fmf.tactics import DECODE_ERROR, HEADER_SIZE
from fm27lab.domain.scenario import normalize_scenario
from fm27lab.ports.fmf import FMF_LENGTH_BYTES, FMF_MAGIC
from fm27lab.ports.fmf import FmfCodec as FmfCodecPort
from fm27lab.tests.test_http_drafts import scenario

ENCODE_ERROR = "场景无法编码为 FMF 文件"


def canonical_json(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def framed(document: bytes) -> bytes:
    return FMF_MAGIC + len(document).to_bytes(4, "big") + document


def normalized(count: int = 26) -> dict:
    return normalize_scenario(scenario(count))


def invalid_payloads() -> dict[str, bytes | str]:
    valid = canonical_json(normalized(23))
    return {
        "empty": b"",
        "short_header": FMF_MAGIC,
        "wrong_magic": b"FMFV1" + (2).to_bytes(4, "big") + b"{}",
        "missing_body": FMF_MAGIC + (0).to_bytes(4, "big"),
        "declared_longer": FMF_MAGIC + (10).to_bytes(4, "big") + b"{}",
        "declared_shorter": FMF_MAGIC + (1).to_bytes(4, "big") + b"{}",
        "trailing_bytes": framed(valid) + b"x",
        "truncated_body": framed(valid)[:-4],
        "not_json": framed(b"not json"),
        "invalid_utf8": framed(b"\xff\xfe"),
        "json_sequence": framed(b"[]"),
        "json_null": framed(b"null"),
        "missing_teams": framed(b'{"schema":4}'),
        "broken_team": framed(b'{"teams":[{},{}]}'),
        "nan_literal": framed(b'{"teams":[],"value":NaN}'),
        "text": "FMFV2",
    }


def test_port_declares_versioned_magic_and_codec_protocol():
    assert FMF_MAGIC == b"FMFV2"
    assert isinstance(FmfCodec(), FmfCodecPort)


def test_encode_writes_magic_length_and_canonical_json():
    value = normalized(26)
    payload = FmfCodec().encode(value)
    assert payload[: len(FMF_MAGIC)] == FMF_MAGIC
    body = payload[len(FMF_MAGIC) :]
    assert int.from_bytes(body[:4], "big") == len(body) - 4
    assert body[4:] == canonical_json(value)


def test_encode_counts_length_in_utf8_bytes():
    value = normalized(23)
    value["teams"][0]["name"] = "主队"
    value["teams"][1]["name"] = "客队"
    payload = FmfCodec().encode(value)
    body = payload[len(FMF_MAGIC) :]
    assert int.from_bytes(body[:4], "big") == len(body) - 4
    assert "主队".encode() in body[4:]
    assert FmfCodec().decode(payload) == value


def test_encode_is_deterministic_and_key_order_independent():
    value = normalized(26)
    codec = FmfCodec()
    payload = codec.encode(value)
    assert codec.encode(value) == payload
    reordered = dict(reversed(list(value.items())))
    assert codec.encode(reordered) == payload


def test_round_trip_preserves_normalized_scenario():
    codec = FmfCodec()
    for count in (20, 23, 26, 30):
        value = normalize_scenario(scenario(count))
        payload = codec.encode(value)
        decoded = codec.decode(payload)
        assert isinstance(decoded, Mapping)
        assert decoded == value, count
        assert codec.encode(decoded) == payload, count


def test_round_trip_normalizes_untrusted_document():
    codec = FmfCodec()
    raw = scenario(26)
    assert codec.decode(framed(canonical_json(raw))) == normalize_scenario(raw)


def test_decode_accepts_bytes_like():
    payload = FmfCodec().encode(normalized(23))
    assert FmfCodec().decode(bytearray(payload)) == normalized(23)
    assert FmfCodec().decode(memoryview(payload)) == normalized(23)


@pytest.mark.parametrize(
    "payload",
    list(invalid_payloads().values()),
    ids=list(invalid_payloads().keys()),
)
def test_decode_rejects_invalid_payloads(payload):
    with pytest.raises(ValueError, match="FMF 文件无效"):
        FmfCodec().decode(payload)


def test_encode_rejects_scenario_that_cannot_normalize():
    codec = FmfCodec()
    with pytest.raises(ValueError, match="场景必须包含两支球队"):
        codec.encode({"schema": 4, "teams": []})
    with pytest.raises(ValueError, match="场景必须是对象"):
        codec.encode([])


def test_encode_rejects_values_json_cannot_represent():
    codec = FmfCodec()
    for value in (float("nan"), float("inf"), object()):
        scenario_value = normalized(23)
        scenario_value["note"] = value
        with pytest.raises(ValueError, match=ENCODE_ERROR):
            codec.encode(scenario_value)


def _frame(payload: object) -> bytes:
    document = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return FMF_MAGIC + len(document).to_bytes(FMF_LENGTH_BYTES, "big") + document


def _attributes_mapping_payload() -> dict:
    payload = scenario(23)
    for team in payload["teams"]:
        for player in team["players"]:
            player["attributes"] = {f"key{index}": 10 for index in range(20)}
    return payload


def _deeply_nested_payload() -> dict:
    payload = scenario(23)
    cursor = payload
    for _ in range(2000):
        child: dict = {}
        cursor["deep"] = child
        cursor = child
    return payload


@pytest.mark.parametrize("build", [_attributes_mapping_payload, _deeply_nested_payload])
def test_decode_wraps_domain_failures_as_decode_error(build):
    codec = FmfCodec()
    with pytest.raises(ValueError, match=DECODE_ERROR):
        codec.decode(_frame(build()))


@pytest.mark.parametrize("build", [_attributes_mapping_payload, _deeply_nested_payload])
def test_encode_wraps_domain_failures_as_encode_error(build):
    codec = FmfCodec()
    with pytest.raises(ValueError, match=ENCODE_ERROR):
        codec.encode(build())


def test_decode_rejects_non_finite_numbers():
    codec = FmfCodec()
    framed = codec.encode(scenario(23))
    document = framed[HEADER_SIZE:].decode("utf-8")
    document = "{" + '"extra":1e999,' + document[1:]
    body = document.encode("utf-8")
    frame = FMF_MAGIC + len(body).to_bytes(FMF_LENGTH_BYTES, "big") + body
    with pytest.raises(ValueError, match=DECODE_ERROR):
        codec.decode(frame)
