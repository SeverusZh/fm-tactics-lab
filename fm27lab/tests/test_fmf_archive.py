"""FMF v8 战术归档的结构与回读测试。"""

from __future__ import annotations

import struct

import pytest

from fm27lab.adapters.fmf.archive import (
    AOM_HEADER,
    ARCHIVE_HEADER,
    ARCHIVE_REVISION,
    CONTENT_NOT_TACTIC_ERROR,
    DETAILS_EXTENSION,
    DETAILS_NAME,
    DIRECTORY_COUNT_ERROR,
    DIRECTORY_MISMATCH_ERROR,
    FILE_TYPE_ERROR,
    FRAME_DICTIONARY_ERROR,
    FRAME_LENGTH_MISMATCH_ERROR,
    IDENTIFIER_SIZE_ERROR,
    INVALID_HEADER_ERROR,
    LENGTH_OUT_OF_RANGE_ERROR,
    MISSING_ZSTD_ERROR,
    ROOT_INVALID_ERROR,
    ROOT_SIZE,
    TAC_CONTENT_HEADER,
    TACTIC_EXTENSION,
    TOO_SHORT_ERROR,
    TRAILING_LENGTH_ERROR,
    UNSUPPORTED_BLOCK_ERROR,
    ZSTD_BLOCK_BYTES,
    ZSTD_MAGIC,
    ArchiveError,
    read_tactics_archive,
    tactics_archive,
)

GOLDEN_PLAN = b"ABCD"
GOLDEN_ARCHIVE = bytes.fromhex(
    "0201666d662e080000ad0000000000000011000000000000000328b52ffda00c00000061000003016361742e22004142"
    "434428b52ffda078000000c1030003016d6f612e040014000000544143544943535f545950455f48414e444c45520100"
    "00005413000000464d3237207461637469637320656469746f72000000000000ffffffffffffffffffffffffffffffff"
    "0c000000464d32372054616374696373020001000281490d03010010000102030405060708090201666d662e08000028"
    "b52ffda08e0000007104000100000054010000000100000054040000002e746163000000000000000018000000000000"
    "000c000000000000000100000000000000010000000000000001000000050000005f6461746101000000070000006465"
    "7461696c73040000002e616f6d1800000000000000840000000000000078000000000000000100000000000000010000"
    "000000000000000000"
)


TOC_HEADER_BYTES = len(ZSTD_MAGIC) + 5
TOC_PAYLOAD_OFFSET = TOC_HEADER_BYTES + 3


def frame_length(raw: int) -> int:
    blocks = max(1, -(-raw // ZSTD_BLOCK_BYTES))
    return TOC_HEADER_BYTES + raw + 3 * blocks


def payload_start() -> int:
    return len(ARCHIVE_HEADER) + ROOT_SIZE


def frame_end(archive: bytes, start: int) -> int:
    declared = int.from_bytes(archive[start + 5 : start + 9], "little")
    position = start + TOC_HEADER_BYTES
    for _ in range(max(1, -(-declared // ZSTD_BLOCK_BYTES))):
        header = int.from_bytes(archive[position : position + 3], "little")
        position += 3 + (header >> 3)
    return position


def directory_frame_start(archive: bytes) -> int:
    total = struct.unpack_from("<Q", archive, len(ARCHIVE_HEADER))[0]
    return payload_start() + total - ROOT_SIZE + len(ARCHIVE_HEADER)


def directory_payload(archive: bytes) -> bytes:
    start = directory_frame_start(archive)
    declared = int.from_bytes(archive[start + 5 : start + 9], "little")
    payload = archive[start + TOC_PAYLOAD_OFFSET : start + TOC_PAYLOAD_OFFSET + declared]
    assert len(payload) == declared
    return payload


def read_string(payload: bytes, position: int) -> tuple[bytes, int]:
    size = struct.unpack_from("<I", payload, position)[0]
    return payload[position + 4 : position + 4 + size], position + 4 + size


def parse_directory(payload: bytes) -> dict:
    position = 0
    title, position = read_string(payload, position)
    root_count_position = position
    root_count = struct.unpack_from("<I", payload, position)[0]
    position += 4
    name, position = read_string(payload, position)
    extension, position = read_string(payload, position)
    tactic_entry = position
    position += 40
    folder_count_position = position
    folder_count = struct.unpack_from("<I", payload, position)[0]
    position += 4
    folder, position = read_string(payload, position)
    file_count_position = position
    file_count = struct.unpack_from("<I", payload, position)[0]
    position += 4
    details_name, position = read_string(payload, position)
    details_extension_position = position
    details_extension, position = read_string(payload, position)
    details_entry = position
    position += 40
    terminator_position = position
    terminator = struct.unpack_from("<I", payload, position)[0]
    position += 4
    return {
        "title": title,
        "name": name,
        "extension": extension,
        "tactic_entry": tactic_entry,
        "stored_position": tactic_entry + 8,
        "folder": folder,
        "folder_count_position": folder_count_position,
        "file_count_position": file_count_position,
        "root_count_position": root_count_position,
        "details_extension_position": details_extension_position,
        "details_extension": details_extension,
        "details_name": details_name,
        "details_entry": details_entry,
        "terminator_position": terminator_position,
        "terminator": terminator,
        "length": position,
        "root_count": root_count,
        "folder_count": folder_count,
        "file_count": file_count,
    }


def mutate(archive: bytes, position: int, data: bytes) -> bytes:
    return archive[:position] + data + archive[position + len(data) :]


def mutate_directory(archive: bytes, field: str, data: bytes) -> bytes:
    payload = directory_payload(archive)
    offset = parse_directory(payload)[field]
    return mutate(archive, directory_frame_start(archive) + TOC_PAYLOAD_OFFSET + offset, data)


def sample_archive(plan: bytes = b"plan", title: str = "战术") -> bytes:
    return tactics_archive(plan, title, created=0, identifier=bytes(10))


def test_archive_matches_versioned_layout_for_fixed_identifier() -> None:
    archive = tactics_archive(GOLDEN_PLAN, "T", created=1, identifier=bytes(range(10)))
    assert archive == GOLDEN_ARCHIVE


def test_archive_header_declares_payload_and_revision() -> None:
    plan = bytes(range(256)) * 3
    archive = tactics_archive(plan, "主场战术")
    assert archive[: len(ARCHIVE_HEADER)] == ARCHIVE_HEADER
    total, root_size, revision = struct.unpack_from("<QQB", archive, len(ARCHIVE_HEADER))
    assert root_size == ROOT_SIZE
    assert revision == ARCHIVE_REVISION
    first = payload_start()
    second = frame_end(archive, first)
    third = frame_end(archive, second)
    assert total == third - first + ROOT_SIZE
    assert archive[third : third + len(ARCHIVE_HEADER)] == ARCHIVE_HEADER
    assert second - first == frame_length(len(TAC_CONTENT_HEADER) + len(plan))
    assert read_tactics_archive(archive).plan == plan


@pytest.mark.parametrize(
    "size",
    [0, 1, 4096, ZSTD_BLOCK_BYTES - 1, ZSTD_BLOCK_BYTES, ZSTD_BLOCK_BYTES + 1, 200_000],
)
def test_archive_round_trip_returns_plan_and_title(size: int) -> None:
    plan = bytes([size % 251]) * size
    archive = read_tactics_archive(tactics_archive(plan, "主场战术", identifier=bytes(range(10))))
    assert archive.title == "主场战术"
    assert archive.plan == plan
    tactic, details = archive.files
    assert tactic.name == "主场战术"
    assert tactic.extension == TACTIC_EXTENSION
    assert details.name == DETAILS_NAME
    assert details.extension == DETAILS_EXTENSION
    assert tactic.offset == 0
    assert details.offset == tactic.stored
    assert tactic.raw == len(TAC_CONTENT_HEADER) + size
    assert tactic.stored == frame_length(tactic.raw)
    assert archive.details.startswith(AOM_HEADER)
    assert archive.details.endswith(bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))


def test_archive_entries_share_creation_timestamp() -> None:
    archive = read_tactics_archive(tactics_archive(b"plan", "战术", created=1234567))
    tactic, details = archive.files
    assert tactic.created == tactic.modified == 1234567
    assert details.created == details.modified == 1234567


def test_archive_splits_large_payloads_into_multiple_zstd_blocks() -> None:
    plan = b"x" * (ZSTD_BLOCK_BYTES * 2 + 7)
    archive = tactics_archive(plan, "大计划")
    first = payload_start()
    assert frame_end(archive, first) - first == frame_length(len(TAC_CONTENT_HEADER) + len(plan))
    assert read_tactics_archive(archive).plan == plan


def test_archive_accepts_bytearray_plan_and_rejects_non_bytes() -> None:
    assert read_tactics_archive(tactics_archive(bytearray(b"abc"), "t")).plan == b"abc"
    with pytest.raises(TypeError):
        tactics_archive("abc", "t")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        tactics_archive(b"abc", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=IDENTIFIER_SIZE_ERROR):
        tactics_archive(b"abc", "t", identifier=b"short")
    with pytest.raises(ArchiveError, match="战术归档必须是字节串"):
        read_tactics_archive("not-bytes")  # type: ignore[arg-type]


def test_archive_rejects_short_and_misaligned_input() -> None:
    valid = sample_archive()
    with pytest.raises(ArchiveError, match=TOO_SHORT_ERROR):
        read_tactics_archive(valid[:20])
    with pytest.raises(ArchiveError, match=INVALID_HEADER_ERROR):
        read_tactics_archive(b"\x00" + valid[1:])
    with pytest.raises(ArchiveError, match=LENGTH_OUT_OF_RANGE_ERROR):
        read_tactics_archive(mutate(valid, len(ARCHIVE_HEADER), struct.pack("<Q", 10**9)))
    with pytest.raises(ArchiveError, match="战术归档头字段无效"):
        read_tactics_archive(mutate(valid, len(ARCHIVE_HEADER) + 8, b"\x02"))


def test_archive_rejects_corrupted_directory() -> None:
    archive = sample_archive()
    start = directory_frame_start(archive)
    with pytest.raises(ArchiveError, match=MISSING_ZSTD_ERROR):
        read_tactics_archive(mutate(archive, start, b"\x00"))
    with pytest.raises(ArchiveError, match=TRAILING_LENGTH_ERROR):
        read_tactics_archive(mutate(archive, len(archive) - 4, b"\x01\x00\x00\x00"))
    with pytest.raises(ArchiveError, match=ROOT_INVALID_ERROR):
        read_tactics_archive(mutate_directory(archive, "root_count_position", struct.pack("<I", 0)))
    with pytest.raises(ArchiveError, match=DIRECTORY_COUNT_ERROR):
        read_tactics_archive(mutate_directory(archive, "folder_count_position", struct.pack("<I", 0)))
    with pytest.raises(ArchiveError, match=FILE_TYPE_ERROR):
        read_tactics_archive(mutate_directory(archive, "file_count_position", struct.pack("<I", 2)))
    with pytest.raises(ArchiveError, match=FILE_TYPE_ERROR):
        read_tactics_archive(mutate_directory(archive, "details_extension_position", b"\x04\x00\x00\x00x"))
    with pytest.raises(ArchiveError, match=DIRECTORY_MISMATCH_ERROR):
        read_tactics_archive(mutate_directory(archive, "stored_position", struct.pack("<Q", 1)))


def test_archive_rejects_corrupted_payload_frames() -> None:
    archive = sample_archive()
    start = payload_start()
    with pytest.raises(ArchiveError, match=FRAME_DICTIONARY_ERROR):
        read_tactics_archive(mutate(archive, start + 4, b"\xa1"))
    block = start + TOC_HEADER_BYTES
    header = int.from_bytes(archive[block : block + 3], "little")
    unsupported = ((header >> 3) << 3) | (2 << 1) | (header & 1)
    with pytest.raises(ArchiveError, match=UNSUPPORTED_BLOCK_ERROR):
        read_tactics_archive(mutate(archive, block, unsupported.to_bytes(3, "little")))
    declared = start + 5
    bigger = int.from_bytes(archive[declared : declared + 4], "little") + 1
    with pytest.raises(ArchiveError, match=FRAME_LENGTH_MISMATCH_ERROR):
        read_tactics_archive(mutate(archive, declared, struct.pack("<I", bigger)))
    content = start + TOC_HEADER_BYTES + 3
    with pytest.raises(ArchiveError, match=CONTENT_NOT_TACTIC_ERROR):
        read_tactics_archive(mutate(archive, content, b"\x00"))
    with pytest.raises(ArchiveError, match="战术数据块越过归档边界"):
        total = struct.unpack_from("<Q", archive, len(ARCHIVE_HEADER))[0]
        read_tactics_archive(mutate(archive, len(ARCHIVE_HEADER), struct.pack("<Q", total - 1)))


def test_archive_rejects_missing_directory_header() -> None:
    archive = sample_archive()
    total = struct.unpack_from("<Q", archive, len(ARCHIVE_HEADER))[0]
    end = payload_start() + total - ROOT_SIZE
    with pytest.raises(ArchiveError, match="战术归档缺少目录头"):
        read_tactics_archive(mutate(archive, end, b"\x00"))


def test_frame_length_helper_covers_edge_cases() -> None:
    assert frame_length(0) == 12
    assert frame_length(1) == 13
    assert frame_length(ZSTD_BLOCK_BYTES) == 12 + ZSTD_BLOCK_BYTES
    assert frame_length(ZSTD_BLOCK_BYTES + 1) == 12 + ZSTD_BLOCK_BYTES + 1 + 3