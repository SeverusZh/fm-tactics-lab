"""存档战术库读取：从存档 tactics_man 板块解析已存战术，并按名字与存档战术表配对。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fm27lab.adapters.save_fmsave.reader import (
    SAVE_CHANGED_ERROR,
    SAVE_INVALID_ERROR,
    _field,
    _load_fmsave,
    _reader_error,
)

TACTICS_SECTION = "tactics_man"
USER_TACTIC_SIGNATURE = bytes.fromhex("2244001b00010002")
PRESET_TACTIC_SIGNATURE = bytes.fromhex("2244001b00010001")
SIGNATURE_LEAD = bytes.fromhex("2244001b00")
SIGNATURE_BYTES = 8
TACTICS_UNSUPPORTED_ERROR = "当前游戏版本的存档战术暂不支持解析"

__all__ = [
    "PRESET_TACTIC_SIGNATURE",
    "SIGNATURE_BYTES",
    "SIGNATURE_LEAD",
    "StoredTactic",
    "TACTICS_SECTION",
    "TACTICS_UNSUPPORTED_ERROR",
    "TacticsSource",
    "USER_TACTIC_SIGNATURE",
    "load_tactics_source",
    "read_tactic_stream",
    "read_tactics",
]


@dataclass(frozen=True, slots=True)
class StoredTactic:
    """存档战术表的一行，附带原始战术流是否已定位。"""

    index: int
    name: str
    style: str
    mentality: int | None
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    has_stream: bool


@dataclass(frozen=True, slots=True)
class TacticsSource:
    """一次存档读取得到的战术板块原始数据。"""

    section: bytes
    layout: Any
    rows: tuple[Any, ...]
    file_name: str


@dataclass(frozen=True, slots=True)
class _Block:
    start: int
    end: int
    name: str


def load_tactics_source(path: Path) -> TacticsSource:
    """打开存档，读取战术板块、布局与战术表。"""
    target = Path(path)
    fmsave = _load_fmsave()
    before = _file_signature(target)
    try:
        with fmsave.open(target) as save:
            section = save._read_section(TACTICS_SECTION)
            info = save.info
            layout = _tactics_layout(info)
            rows = tuple(save.tactics())
    except ValueError:
        raise
    except Exception as error:
        raise _reader_error(fmsave, error) from error
    if _file_signature(target) != before:
        raise ValueError(SAVE_CHANGED_ERROR)
    return TacticsSource(section=section, layout=layout, rows=rows, file_name=target.name)


def read_tactics(
    path: Path,
    *,
    loader: Callable[[Path], TacticsSource] = load_tactics_source,
    read_record: Callable[..., Any] | None = None,
) -> tuple[StoredTactic, ...]:
    """列出存档内的战术，按存档战术表顺序排列。"""
    source = loader(Path(path))
    if not source.rows:
        return ()
    blocks = _blocks(source.section, source.layout, _record_reader(read_record), source.file_name)
    if not blocks:
        raise ValueError(TACTICS_UNSUPPORTED_ERROR)
    return tuple(
        _stored(index, row, block)
        for index, (row, block) in enumerate(_pairs(source.rows, blocks))
    )


def read_tactic_stream(
    path: Path,
    index: int,
    *,
    loader: Callable[[Path], TacticsSource] = load_tactics_source,
    read_record: Callable[..., Any] | None = None,
) -> bytes | None:
    """返回指定位置战术的原始战术流切片；无法定位时返回 None。"""
    source = loader(Path(path))
    if not source.rows or not 0 <= index < len(source.rows):
        return None
    blocks = _blocks(source.section, source.layout, _record_reader(read_record), source.file_name)
    pairs = _pairs(source.rows, blocks)
    block = pairs[index][1]
    if block is None:
        return None
    return source.section[block.start : block.end]


def _record_reader(read_record: Callable[..., Any] | None) -> Callable[..., Any]:
    return read_record if read_record is not None else _fmsave_read_record


def _fmsave_read_record(
    section: bytes,
    signature_at: int,
    record_end: int,
    layout: Any,
    file_name: str,
) -> Any:
    from fmsave.readers.tactics import _read_tactic_record

    return _read_tactic_record(section, signature_at, record_end, layout, file_name)


def _tactics_layout(info: Any) -> Any:
    from fmsave.readers.tactics import find_tactics_layout

    schemas = getattr(info, "section_schemas", None)
    schema = schemas.get(TACTICS_SECTION) if isinstance(schemas, Mapping) else None
    return find_tactics_layout(schema, getattr(info, "build", ""))


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as error:
        raise ValueError(f"{SAVE_INVALID_ERROR}：{error}") from error
    return (stat.st_size, stat.st_mtime_ns)


def _blocks(
    section: bytes,
    layout: Any,
    read_record: Callable[..., Any],
    file_name: str,
) -> tuple[_Block, ...]:
    signatures = _known_signatures(layout)
    if signatures:
        blocks = _scan(section, signatures, layout, read_record, file_name)
        if blocks:
            return blocks
    for signature in _variant_signatures(section):
        blocks = _scan(section, (signature,), layout, read_record, file_name)
        if blocks:
            return blocks
    return ()


def _known_signatures(layout: Any) -> tuple[bytes, ...]:
    values = (
        getattr(layout, "user_signature", None),
        getattr(layout, "alternate_signature", None),
        getattr(layout, "preset_signature", None),
        USER_TACTIC_SIGNATURE,
        PRESET_TACTIC_SIGNATURE,
    )
    signatures: list[bytes] = []
    for value in values:
        if isinstance(value, (bytes, bytearray)) and len(value) == SIGNATURE_BYTES:
            item = bytes(value)
            if item not in signatures:
                signatures.append(item)
    return tuple(signatures)


def _variant_signatures(section: bytes) -> tuple[bytes, ...]:
    """按已知前缀扫描存档，得到候选战术流签名。"""
    candidates: list[bytes] = []
    position = section.find(SIGNATURE_LEAD)
    while position >= 0:
        candidate = section[position : position + SIGNATURE_BYTES]
        if len(candidate) == SIGNATURE_BYTES and candidate not in candidates:
            candidates.append(candidate)
        position = section.find(SIGNATURE_LEAD, position + 1)
    return tuple(candidates)


def _scan(
    section: bytes,
    signatures: tuple[bytes, ...],
    layout: Any,
    read_record: Callable[..., Any],
    file_name: str,
) -> tuple[_Block, ...]:
    matches: dict[int, bytes] = {}
    for signature in signatures:
        position = section.find(signature)
        while position >= 0:
            matches[position] = signature
            position = section.find(signature, position + 1)
    starts = sorted(matches)
    blocks: list[_Block] = []
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(section)
        if end <= start:
            continue
        record = _read_record(read_record, section, start, end, layout, matches[start], file_name)
        if record is None:
            continue
        if _field(record, "walk_complete") is not True or _field(record, "oop_index_permutation") is not True:
            continue
        name = _text(_field(record, "name"))
        if not name:
            continue
        blocks.append(_Block(start=start, end=end, name=name))
    return tuple(blocks)


def _read_record(
    read_record: Callable[..., Any],
    section: bytes,
    start: int,
    end: int,
    layout: Any,
    signature: bytes,
    file_name: str,
) -> Any | None:
    try:
        return read_record(section, start, end, _patched(layout, signature), file_name)
    except Exception:
        return None


def _patched(layout: Any, signature: bytes) -> Any:
    try:
        return replace(
            layout,
            user_signature=signature,
            alternate_signature=signature,
            preset_signature=signature,
        )
    except TypeError:
        return layout


def _pairs(rows: tuple[Any, ...], blocks: tuple[_Block, ...]) -> list[tuple[Any, _Block | None]]:
    """按战术表顺序消费同名战术块，避免同名战术互相错配。"""
    pairs: list[tuple[Any, _Block | None]] = []
    cursor = 0
    for row in rows:
        name = _text(_field(row, "name"))
        block = None
        for position in range(cursor, len(blocks)):
            if blocks[position].name == name:
                block = blocks[position]
                cursor = position + 1
                break
        pairs.append((row, block))
    return pairs


def _stored(index: int, row: Any, block: _Block | None) -> StoredTactic:
    return StoredTactic(
        index=index,
        name=_text(_field(row, "name")),
        style=_text(_field(row, "style_name")),
        mentality=_coded_int(_field(row, "mentality")),
        club_uid=_optional_int(_field(row, "club_uid")),
        club_name=_optional_text(_field(row, "club_name")),
        team_slot=_optional_int(_field(row, "team_slot")),
        has_stream=block is not None,
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _coded_int(value: object) -> int | None:
    raw = getattr(value, "raw", value)
    return _optional_int(raw)
