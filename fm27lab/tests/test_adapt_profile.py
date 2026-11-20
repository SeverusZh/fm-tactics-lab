from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native"
sys.path.insert(0, str(ROOT / "scripts"))

import adapt_profile  # noqa: E402


def synthetic_image(raw: bytes) -> adapt_profile.PeImage:
    section = adapt_profile.Section(".idata", 0x1000, len(raw), len(raw), 0, 0x60000020)
    return adapt_profile.PeImage(raw, 0x180000000, 0x4000, [section], [])


def test_extract_at_anchors_reads_native_calls_and_skips_size_bounds():
    anchors = adapt_profile.extract_at_anchors()
    assert 0x4D30 in anchors
    assert 0x4BA21D0 in anchors
    assert 0x17CB9000 not in anchors
    assert all(value < 0xF0000000 for value in anchors)


def test_locate_matches_a_relocated_window_and_rejects_other_functions():
    pattern = bytes.fromhex("5541574156415541545657534881ec88000000")
    raw = bytearray(0x400)
    raw[0x20:0x20 + len(pattern)] = pattern
    raw[0x120:0x120 + len(pattern)] = bytes(len(pattern))
    image = synthetic_image(bytes(raw))
    image.functions = [(0x1000, 0x1100), (0x1100, 0x1200)]
    signatures = {
        "ranges": [{
            "rva": 0x4D30,
            "size": 0x100,
            "kind": "code",
            "windows": [[0x20, len(pattern), adapt_profile.sha256_prefix(pattern)]],
        }]
    }
    assert adapt_profile.locate(image, signatures) == {0x4D30: 0x1000}


def test_locate_rejects_equal_candidates_instead_of_guessing():
    pattern = bytes.fromhex("5541574156415541545657534881ec88000000")
    raw = bytearray(0x400)
    raw[0x20:0x20 + len(pattern)] = pattern
    raw[0x120:0x120 + len(pattern)] = pattern
    image = synthetic_image(bytes(raw))
    image.functions = [(0x1000, 0x1100), (0x1100, 0x1200)]
    signatures = {
        "ranges": [{
            "rva": 0x4D30,
            "size": 0x100,
            "kind": "code",
            "windows": [[0x20, len(pattern), adapt_profile.sha256_prefix(pattern)]],
        }]
    }
    assert adapt_profile.locate(image, signatures) == {}


def test_propagate_maps_a_direct_call_target():
    raw = bytearray(0x400)
    raw[0:5] = b"\xe8\xfb\x00\x00\x00"
    image = synthetic_image(bytes(raw))
    image.functions = [(0x1000, 0x1100), (0x1100, 0x1200)]
    signatures = {
        "ranges": [
            {"rva": 0x1000, "size": 0x10, "kind": "code", "ops": [[1, 4, adapt_profile.OPERAND_REL, 5, 0x1100]]},
            {"rva": 0x1100, "size": 8, "kind": "data"},
        ]
    }
    mapped = adapt_profile.propagate(image, signatures, {0x1000: 0x1000})
    assert mapped[0x1100] == 0x1100


def minimal_pe(pattern: bytes) -> bytes:
    raw = bytearray(0x600)
    raw[0:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 0x80)
    raw[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", raw, 0x84, 0x8664, 2)
    struct.pack_into("<H", raw, 0x94, 0xF0)
    optional = 0x98
    struct.pack_into("<H", raw, optional, 0x20B)
    struct.pack_into("<Q", raw, optional + 24, 0x180000000)
    struct.pack_into("<I", raw, optional + 56, 0x3000)
    struct.pack_into("<I", raw, optional + 60, 0x200)
    struct.pack_into("<II", raw, optional + 112 + 3 * 8, 0x1200, 12)
    table = optional + 0xF0
    for index, fields in enumerate([
        (0x200, 0x1000, 0x200, 0x200, 0x60000020),
        (0x100, 0x1200, 0x100, 0x400, 0x40000040),
    ]):
        base = table + 40 * index
        struct.pack_into("<IIII", raw, base + 8, *fields[:4])
        struct.pack_into("<I", raw, base + 36, fields[4])
    raw[0x200 + 0x20:0x200 + 0x20 + len(pattern)] = pattern
    struct.pack_into("<III", raw, 0x400, 0x1000, 0x1100, 0)
    return bytes(raw)


def test_adapt_writes_a_complete_profile_for_a_matching_image(tmp_path, monkeypatch):
    pattern = bytes.fromhex("5541574156415541545657534881ec88000000")
    dll = tmp_path / "game_plugin.dll"
    dll.write_bytes(minimal_pe(pattern))
    metadata = {
        "id": "fm27_desktop_test_adapter_v1",
        "reference_sha256": "0" * 64,
        "signatures": {
            "schema": 1,
            "reference_id": "fm27_desktop_test_adapter_v1",
            "reference_sha256": "0" * 64,
            "reference_image_base": 0x180000000,
            "ranges": [{
                "rva": 0x4D30,
                "size": 0x100,
                "kind": "code",
                "windows": [[0x20, len(pattern), adapt_profile.sha256_prefix(pattern)]],
                "ops": [],
            }],
        },
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf8")
    monkeypatch.setattr(adapt_profile, "extract_at_anchors", lambda: [0x4D30])
    profile_path = tmp_path / "adapter_profile.txt"
    report = adapt_profile.adapt(dll, metadata_path, None, False, profile_path)
    assert report["complete"] is True
    text = profile_path.read_text(encoding="utf8")
    assert "reference fm27_desktop_test_adapter_v1" in text
    assert "map 4d30 1000" in text
    assert (tmp_path / "adapter_profile.txt.report.json").is_file()


def test_adapt_does_not_emit_a_profile_without_pdata(tmp_path, monkeypatch):
    pattern = bytes.fromhex("5541574156415541545657534881ec88000000")
    raw = bytearray(minimal_pe(pattern))
    struct.pack_into("<II", raw, 0x98 + 112 + 3 * 8, 0, 0)
    dll = tmp_path / "game_plugin.dll"
    dll.write_bytes(bytes(raw))
    metadata = {
        "id": "fm27_desktop_test_adapter_v1",
        "reference_sha256": "0" * 64,
        "signatures": {
            "schema": 1,
            "reference_id": "fm27_desktop_test_adapter_v1",
            "reference_sha256": "0" * 64,
            "reference_image_base": 0x180000000,
            "ranges": [],
        },
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf8")
    monkeypatch.setattr(adapt_profile, "extract_at_anchors", lambda: [0x4D30])
    profile_path = tmp_path / "adapter_profile.txt"
    report = adapt_profile.adapt(dll, metadata_path, None, True, profile_path)
    assert report["pdata_missing"] is True
    assert report["complete"] is False
    assert not profile_path.exists()


def test_write_signatures_requires_explicit_mixed_reference(tmp_path, monkeypatch):
    metadata = {"id": "fm27_desktop_test_adapter_v1", "reference_sha256": "0" * 64, "ranges": [{"rva": 1}]}
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf8")
    reference = tmp_path / "reference.json"
    reference.write_text("{}", encoding="utf8")
    monkeypatch.setattr(
        adapt_profile,
        "build_signatures",
        lambda _metadata, _reference: {
            "schema": 1,
            "reference_id": "fm27_desktop_test_adapter_v1",
            "reference_sha256": "0" * 64,
            "source_reference_id": "other",
            "source_reference_sha256": "1" * 64,
            "mixed_reference": True,
            "reference_image_base": 0x180000000,
            "used_code_ranges": 1,
            "ranges": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["adapt_profile.py", "--dll", "unused", "--metadata", str(metadata_path), "--reference", str(reference), "--write-signatures", "--out", str(tmp_path / "out.txt")],
    )
    with pytest.raises(SystemExit):
        adapt_profile.main()


def test_write_signatures_replaces_metadata_atomically(tmp_path, monkeypatch):
    metadata = {"id": "fm27_desktop_test_adapter_v1", "reference_sha256": "0" * 64, "ranges": [{"rva": 1}]}
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf8")
    reference = tmp_path / "reference.json"
    reference.write_text("{}", encoding="utf8")
    monkeypatch.setattr(
        adapt_profile,
        "build_signatures",
        lambda _metadata, _reference: {
            "schema": 1,
            "reference_id": "fm27_desktop_test_adapter_v1",
            "reference_sha256": "0" * 64,
            "source_reference_id": "other",
            "source_reference_sha256": "1" * 64,
            "mixed_reference": True,
            "reference_image_base": 0x180000000,
            "used_code_ranges": 1,
            "ranges": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["adapt_profile.py", "--dll", "unused", "--metadata", str(metadata_path), "--reference", str(reference), "--write-signatures", "--allow-mixed-reference", "--out", str(tmp_path / "out.txt")],
    )
    assert adapt_profile.main() == 0
    written = json.loads(metadata_path.read_text(encoding="utf8"))
    assert written["signatures"]["mixed_reference"] is True
    assert not metadata_path.with_suffix(".json.tmp").exists()


def test_render_profile_binds_the_installed_image_and_emits_exact_maps():
    raw = bytes(range(256))
    image = synthetic_image(raw)
    text = adapt_profile.render_profile(image, {0x4D30: 0x4F90}, [], False, "fm27_desktop_test_adapter_v1")
    lines = text.splitlines()
    assert lines[0] == "fm27-adapter-profile 1"
    assert lines[1] == "reference fm27_desktop_test_adapter_v1"
    assert lines[2] == f"image {hashlib.sha256(raw).hexdigest()}"
    assert "partial 0" in lines
    assert "missing 0" in lines
    assert "map 4d30 4f90" in lines


def test_profile_metadata_carries_derived_signatures_without_raw_bytes():
    metadata = json.loads((NATIVE / "profile_metadata.json").read_text(encoding="utf8"))
    signatures = metadata["signatures"]
    assert signatures["schema"] == 1
    assert signatures["reference_id"] == metadata["id"]
    assert signatures["reference_sha256"] == metadata["reference_sha256"]
    rows = signatures["ranges"]
    assert rows
    assert any(row["kind"] == "code" and row.get("windows") for row in rows)
    for row in rows:
        assert "hex" not in row
        for window in row.get("windows", []):
            assert len(window) == 3
            assert isinstance(window[2], str) and len(window[2]) == 16
        for operand in row.get("ops", []):
            assert len(operand) == 5
            assert operand[2] in {adapt_profile.OPERAND_REL, adapt_profile.OPERAND_RIP, adapt_profile.OPERAND_ABS}


def test_native_host_loads_runtime_profile_and_fails_closed():
    host = (NATIVE / "desktop_host.cpp").read_text(encoding="utf8")
    profile = (NATIVE / "fm27_adapter_profile.h").read_text(encoding="utf8")
    assert '#include "fm27_adapter_profile.h"' in host
    assert "adapter_profile.rva_map.find" in host
    assert "adapter_anchor_unmapped" in host
    assert "adapter_profile_fallback" in host
    assert "image_sha256_mismatch" in host
    assert "adapter_profile_reference_mismatch" in host
    assert "adapter_profile_incomplete" in host
    assert "adapter_profile_target_out_of_image" in host
    assert "adapter_profile_partial_requires_diagnostic" in host
    assert "diagnostic_mode" in host
    assert "image_at(descriptor+16)" in host
    assert "image_at(nt->OptionalHeader" in host
    assert "--probe-engine" in host
    assert "FM27_ADAPTER_PROFILE" in profile
    assert "map_conflict" in profile
