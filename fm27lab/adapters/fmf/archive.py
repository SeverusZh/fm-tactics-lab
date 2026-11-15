"""原生 FMF v8 战术归档的打包与回读。

游戏只接受 FMF v8 归档：固定文件头、目录区与数据区都用无压缩的 Zstandard 原始
块帧封存。TAC 计划由游戏宿主序列化后传入，本模块只负责容器字节与目录一致性。
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Final

ARCHIVE_HEADER: Final = bytes.fromhex("0201666d662e080000")
TAC_CONTENT_HEADER: Final = bytes.fromhex("03016361742e2200")
AOM_HEADER: Final = bytes.fromhex("03016d6f612e0400")
ZSTD_MAGIC: Final = bytes.fromhex("28b52ffd")
TACTIC_EXTENSION: Final = ".tac"
DETAILS_NAME: Final = "details"
DETAILS_EXTENSION: Final = ".aom"
DETAILS_HANDLER: Final = "TACTICS_TYPE_HANDLER"
DETAILS_EDITOR: Final = "FM27 tactics editor"
DETAILS_AUTHOR: Final = "FM27 Tactics"
DETAILS_SUFFIX: Final = bytes.fromhex("020001000281490d03010010")
FOLDER_NAME: Final = "_data"
ZSTD_BLOCK_BYTES: Final = 65536
ROOT_SIZE: Final = 17
ARCHIVE_REVISION: Final = 3
MAX_DIRECTORY_STRING: Final = 4096
ENTRY_SIZE: Final = 40
IDENTIFIER_BYTES: Final = 10

MUST_BYTES_ERROR = "战术归档必须是字节串"
TOO_SHORT_ERROR = "战术归档过短"
INVALID_HEADER_ERROR = "战术归档文件头无效"
INVALID_HEAD_FIELDS_ERROR = "战术归档头字段无效"
LENGTH_OUT_OF_RANGE_ERROR = "战术归档长度越界"
MISSING_ZSTD_ERROR = "战术归档缺少 Zstandard 数据"
FRAME_HEADER_ERROR = "Zstandard 帧头不完整"
FRAME_RESERVED_ERROR = "Zstandard 帧头保留位无效"
FRAME_DICTIONARY_ERROR = "Zstandard 帧不支持字典"
BLOCK_HEADER_ESCAPED_ERROR = "Zstandard 块头越过归档边界"
RAW_BLOCK_ESCAPED_ERROR = "Zstandard 原始块越过归档边界"
REPEAT_BLOCK_ESCAPED_ERROR = "Zstandard 重复块越过归档边界"
FRAME_LENGTH_MISMATCH_ERROR = "Zstandard 帧内容长度与声明不符"
CHECKSUM_ESCAPED_ERROR = "Zstandard 校验和越过归档边界"
UNSUPPORTED_BLOCK_ERROR = "战术归档使用了未受支持的 Zstandard 压缩块"
DIRECTORY_DAMAGED_ERROR = "战术归档目录已损坏"
DATA_BLOCK_ESCAPED_ERROR = "战术数据块越过归档边界"
FILES_INVALID_ERROR = "战术归档文件数量或块边界无效"
MISSING_DIRECTORY_HEADER_ERROR = "战术归档缺少目录头"
TRAILING_LENGTH_ERROR = "战术归档尾部长度无效"
ROOT_INVALID_ERROR = "战术归档根目录无效"
DIRECTORY_COUNT_ERROR = "战术归档目录数量无效"
FILE_TYPE_ERROR = "战术归档文件类型无效"
DIRECTORY_MISMATCH_ERROR = "战术归档目录与内容不一致"
CONTENT_NOT_TACTIC_ERROR = "内嵌内容不是 TAC 战术计划"
PLAN_BYTES_ERROR = "战术计划必须是字节串"
TITLE_TYPE_ERROR = "战术标题必须是字符串"
IDENTIFIER_SIZE_ERROR = "战术标识必须是 10 字节"


class ArchiveError(ValueError):
    """战术归档无法打包或回读。"""


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    extension: str
    offset: int
    stored: int
    raw: int
    created: int
    modified: int


@dataclass(frozen=True, slots=True)
class TacticsArchive:
    title: str
    plan: bytes
    details: bytes
    files: tuple[ArchiveEntry, ...]


def tactics_archive(
    plan: bytes,
    title: str,
    *,
    created: int | None = None,
    identifier: bytes | None = None,
) -> bytes:
    if not isinstance(plan, (bytes, bytearray, memoryview)):
        raise TypeError(PLAN_BYTES_ERROR)
    if not isinstance(title, str):
        raise TypeError(TITLE_TYPE_ERROR)
    raw_plan = bytes(plan)
    stamp = int(time.time()) if created is None else int(created)
    token = os.urandom(IDENTIFIER_BYTES) if identifier is None else bytes(identifier)
    if len(token) != IDENTIFIER_BYTES:
        raise ValueError(IDENTIFIER_SIZE_ERROR)
    files = (
        (title, TACTIC_EXTENSION, TAC_CONTENT_HEADER + raw_plan),
        (DETAILS_NAME, DETAILS_EXTENSION, _details_payload(title, token)),
    )
    chunks = tuple(_zstd_raw_frame(item[2]) for item in files)

    def entry(index: int, offset: int) -> bytes:
        name, extension, raw = files[index]
        return (
            _archive_string(name)
            + _archive_string(extension)
            + struct.pack("<QQQqq", offset, len(chunks[index]), len(raw), stamp, stamp)
        )

    toc = (
        _archive_string(title)
        + struct.pack("<I", 1)
        + entry(0, 0)
        + struct.pack("<I", 1)
        + _archive_string(FOLDER_NAME)
        + struct.pack("<I", 1)
        + entry(1, len(chunks[0]))
        + struct.pack("<I", 0)
    )
    payload = b"".join(chunks)
    head = ARCHIVE_HEADER + struct.pack("<QQB", ROOT_SIZE + len(payload), ROOT_SIZE, ARCHIVE_REVISION)
    return head + payload + ARCHIVE_HEADER + _zstd_raw_frame(toc)


def read_tactics_archive(payload: bytes) -> TacticsArchive:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ArchiveError(MUST_BYTES_ERROR)
    value = bytes(payload)
    minimum = len(ARCHIVE_HEADER) + ROOT_SIZE + len(ARCHIVE_HEADER) + 3
    if len(value) < minimum:
        raise ArchiveError(TOO_SHORT_ERROR)
    if not value.startswith(ARCHIVE_HEADER):
        raise ArchiveError(INVALID_HEADER_ERROR)
    total, root_size, revision = struct.unpack_from("<QQB", value, len(ARCHIVE_HEADER))
    if root_size != ROOT_SIZE or revision != ARCHIVE_REVISION or total < ROOT_SIZE:
        raise ArchiveError(INVALID_HEAD_FIELDS_ERROR)
    start = len(ARCHIVE_HEADER) + ROOT_SIZE
    end = start + total - ROOT_SIZE
    if end + len(ARCHIVE_HEADER) > len(value):
        raise ArchiveError(LENGTH_OUT_OF_RANGE_ERROR)
    chunks: list[bytes] = []
    frames: list[int] = []
    position = start
    while position < end:
        before = position
        chunk, position = _zstd_frame(value, position)
        if position > end:
            raise ArchiveError(DATA_BLOCK_ESCAPED_ERROR)
        chunks.append(chunk)
        frames.append(position - before)
    if position != end or len(chunks) != 2:
        raise ArchiveError(FILES_INVALID_ERROR)
    if value[end : end + len(ARCHIVE_HEADER)] != ARCHIVE_HEADER:
        raise ArchiveError(MISSING_DIRECTORY_HEADER_ERROR)
    toc, toc_end = _zstd_frame(value, end + len(ARCHIVE_HEADER))
    if toc_end != len(value):
        raise ArchiveError(TRAILING_LENGTH_ERROR)
    title, position = _directory_string(toc, 0)
    root_count, position = _directory_count(toc, position)
    if root_count != 1:
        raise ArchiveError(ROOT_INVALID_ERROR)
    tactic, position = _directory_entry(toc, position)
    folder_count, position = _directory_count(toc, position)
    if folder_count != 1:
        raise ArchiveError(DIRECTORY_COUNT_ERROR)
    folder, position = _directory_string(toc, position)
    file_count, position = _directory_count(toc, position)
    details, position = _directory_entry(toc, position)
    terminator, position = _directory_count(toc, position)
    if terminator or position != len(toc):
        raise ArchiveError(TRAILING_LENGTH_ERROR)
    if file_count != 1 or folder != FOLDER_NAME.encode("utf8"):
        raise ArchiveError(FILE_TYPE_ERROR)
    if tactic.extension != TACTIC_EXTENSION or details.extension != DETAILS_EXTENSION:
        raise ArchiveError(FILE_TYPE_ERROR)
    if (
        tactic.name != _decode_text(title)
        or tactic.offset
        or details.offset != frames[0]
        or tactic.stored != frames[0]
        or details.stored != frames[1]
        or tactic.raw != len(chunks[0])
        or details.raw != len(chunks[1])
    ):
        raise ArchiveError(DIRECTORY_MISMATCH_ERROR)
    content = chunks[0]
    if not content.startswith(TAC_CONTENT_HEADER):
        raise ArchiveError(CONTENT_NOT_TACTIC_ERROR)
    return TacticsArchive(
        title=_decode_text(title),
        plan=content[len(TAC_CONTENT_HEADER) :],
        details=chunks[1],
        files=(tactic, details),
    )


def _details_payload(title: str, token: bytes) -> bytes:
    return (
        AOM_HEADER
        + _archive_string(DETAILS_HANDLER)
        + _archive_string(title)
        + _archive_string(DETAILS_EDITOR)
        + bytes(6)
        + bytes([255]) * 16
        + _archive_string(DETAILS_AUTHOR)
        + DETAILS_SUFFIX
        + token
    )


def _archive_string(value: str) -> bytes:
    raw = value.encode("utf8")
    return struct.pack("<I", len(raw)) + raw


def _zstd_raw_frame(value: bytes) -> bytes:
    frame = bytearray(ZSTD_MAGIC + b"\xa0" + struct.pack("<I", len(value)))
    for offset in range(0, max(1, len(value)), ZSTD_BLOCK_BYTES):
        block = value[offset : offset + ZSTD_BLOCK_BYTES]
        last = offset + len(block) >= len(value)
        frame += ((len(block) << 3) | int(last)).to_bytes(3, "little") + block
    return bytes(frame)


def _zstd_frame(value: bytes, start: int) -> tuple[bytes, int]:
    if value[start : start + 4] != ZSTD_MAGIC:
        raise ArchiveError(MISSING_ZSTD_ERROR)
    position = start + 4
    if position >= len(value):
        raise ArchiveError(FRAME_HEADER_ERROR)
    descriptor = value[position]
    position += 1
    if descriptor & 8:
        raise ArchiveError(FRAME_RESERVED_ERROR)
    if descriptor & 3:
        raise ArchiveError(FRAME_DICTIONARY_ERROR)
    single_segment = (descriptor >> 5) & 1
    flag = (descriptor >> 6) & 3
    checksum = 4 if descriptor & 4 else 0
    if not single_segment:
        position += 1
    size_bytes = 1 if flag == 0 and single_segment else (0, 2, 4, 8)[flag]
    if position + size_bytes > len(value):
        raise ArchiveError(FRAME_HEADER_ERROR)
    declared = int.from_bytes(value[position : position + size_bytes], "little") if size_bytes else None
    position += size_bytes
    result = bytearray()
    while True:
        if position + 3 > len(value):
            raise ArchiveError(BLOCK_HEADER_ESCAPED_ERROR)
        header = int.from_bytes(value[position : position + 3], "little")
        position += 3
        last = header & 1
        kind = (header >> 1) & 3
        size = header >> 3
        if kind == 0:
            if position + size > len(value):
                raise ArchiveError(RAW_BLOCK_ESCAPED_ERROR)
            if declared is not None and len(result) + size > declared:
                raise ArchiveError(FRAME_LENGTH_MISMATCH_ERROR)
            result += value[position : position + size]
            position += size
        elif kind == 1:
            if position >= len(value):
                raise ArchiveError(REPEAT_BLOCK_ESCAPED_ERROR)
            if declared is not None and len(result) + size > declared:
                raise ArchiveError(FRAME_LENGTH_MISMATCH_ERROR)
            result += value[position : position + 1] * size
            position += 1
        else:
            raise ArchiveError(UNSUPPORTED_BLOCK_ERROR)
        if last:
            break
    if declared is not None and len(result) != declared:
        raise ArchiveError(FRAME_LENGTH_MISMATCH_ERROR)
    if position + checksum > len(value):
        raise ArchiveError(CHECKSUM_ESCAPED_ERROR)
    return bytes(result), position + checksum


def _directory_string(value: bytes, position: int) -> tuple[bytes, int]:
    if position + 4 > len(value):
        raise ArchiveError(DIRECTORY_DAMAGED_ERROR)
    size = struct.unpack_from("<I", value, position)[0]
    position += 4
    if size > MAX_DIRECTORY_STRING or position + size > len(value):
        raise ArchiveError(DIRECTORY_DAMAGED_ERROR)
    return value[position : position + size], position + size


def _directory_count(value: bytes, position: int) -> tuple[int, int]:
    if position + 4 > len(value):
        raise ArchiveError(DIRECTORY_DAMAGED_ERROR)
    return struct.unpack_from("<I", value, position)[0], position + 4


def _directory_entry(value: bytes, position: int) -> tuple[ArchiveEntry, int]:
    name, position = _directory_string(value, position)
    extension, position = _directory_string(value, position)
    if position + ENTRY_SIZE > len(value):
        raise ArchiveError(DIRECTORY_DAMAGED_ERROR)
    offset, stored, raw, created, modified = struct.unpack_from("<QQQqq", value, position)
    entry = ArchiveEntry(
        name=_decode_text(name),
        extension=_decode_text(extension),
        offset=offset,
        stored=stored,
        raw=raw,
        created=created,
        modified=modified,
    )
    return entry, position + ENTRY_SIZE


def _decode_text(value: bytes) -> str:
    try:
        return value.decode("utf8")
    except UnicodeDecodeError as error:
        raise ArchiveError(DIRECTORY_DAMAGED_ERROR) from error
