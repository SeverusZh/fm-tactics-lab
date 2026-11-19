from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native"
sys.path.insert(0, str(ROOT / "scripts"))

from export_source import source_files  # noqa: E402
from generate_profile import adapter_paths  # noqa: E402
from profile_header import header  # noqa: E402

STEAM_SHA256 = "8c6971ce0b1c8afe6529ea3f46205a5175aea988a97d7421a980da42e23fe340"
EPIC_SHA256 = "ebf6fcf57f554dc7178fb2afa4e1fd4d6e6dcb693f65a1a11216abb8d00c8396"
DIGEST_KEYS = {"rva", "size", "sha256", "purpose"}


def metadata(name: str) -> dict:
    return json.loads((NATIVE / name).read_text(encoding="utf8"))


def test_steam_adapter_version_matches_profile_and_execution_guard():
    adapter = metadata("adapter_version.json")
    profile = metadata("profile_metadata.json")
    assert adapter["version"] == "27.0.1+2503222"
    assert adapter["reference_dll_sha256"] == STEAM_SHA256
    assert profile["reference_sha256"] == adapter["reference_dll_sha256"]
    assert profile["id"] == "fm27_desktop_8c6971ce_adapter_v1"
    assert profile["activation_flag_rva"] == 0x613E244
    assert adapter["native_worker_protocol"] == 2
    ranges = profile["ranges"]
    assert ranges
    for item in ranges:
        assert {"rva", "size", "sha256"} <= set(item) <= DIGEST_KEYS
        assert len(item["sha256"]) == 64
    execution = (NATIVE / "native_execution_experiment.h").read_text(encoding="utf8")
    guard = re.search(r'strcmp\(native_image_sha256,\s*"([0-9a-f]{64})"\)', execution)
    assert guard is not None, "execution hook must guard the exact reference build"
    assert guard.group(1) == profile["reference_sha256"]


def test_steam_host_resolves_activation_before_the_flag_fallback():
    host = (NATIVE / "desktop_host.cpp").read_text(encoding="utf8")
    assert "0x1718f818" not in host
    assert "0x1718f818" not in (NATIVE / "profile_metadata.json").read_text(encoding="utf8")
    assert 'GetProcAddress(module,"WaitForActivation")' in host
    assert "native_activation_wait_returned" in host
    assert "adapter_activation_rva" in host
    assert "adapter_profile.activation_rva" in host
    assert "activation_flag_unmapped" in host
    assert "adapter_profile_partial_requires_diagnostic" in host
    assert "--find-activation" in host
    profile = (NATIVE / "fm27_adapter_profile.h").read_text(encoding="utf8")
    assert "FM27_ADAPTER_PROFILE" in profile
    assert "adapter_hex" in profile
    assert "map_conflict" in profile


def test_epic_adapter_and_profile_publish_digests_only():
    adapter = metadata("epic_adapter_version.json")
    profile = metadata("epic_profile_metadata.json")
    assert adapter["version"] == "27.0.1+epic"
    assert adapter["reference_dll_sha256"] == EPIC_SHA256
    assert profile["reference_sha256"] == adapter["reference_dll_sha256"]
    assert profile["id"] == "fm27_desktop_ebf6fcf5_adapter_v1"
    assert isinstance(profile.get("activation_flag_rva"), int)
    assert profile["activation_flag_rva"] >= 0
    assert profile["activation_flag_rva"] == 101189652
    ranges = profile["ranges"]
    assert ranges
    for item in ranges:
        assert {"rva", "size", "sha256"} <= set(item) <= DIGEST_KEYS
        assert len(item["sha256"]) == 64
    raw = (NATIVE / "epic_profile_metadata.json").read_text(encoding="utf8")
    assert '"hex"' not in raw
    compat = (NATIVE / "fm27_engine_compat.h").read_text(encoding="utf8")
    assert re.search(r"^#ifdef FM27_COMPAT_DIGEST_RANGES$", compat, re.MULTILINE)
    assert "BCRYPT_SHA256_ALGORITHM" in compat
    assert "critical_range_digest" in compat
    host = (NATIVE / "desktop_host.cpp").read_text(encoding="utf8")
    assert re.search(r"^#ifdef FM27_COMPAT_DIGEST_RANGES$", host, re.MULTILINE)
    assert "epic_build_fingerprint_mismatch" in host


def rendered_steam_profile() -> dict:
    profile = metadata("profile_metadata.json")
    return {**profile, "ranges": [{**item, "hex": "90" * item["size"]} for item in profile["ranges"]]}


def test_profile_header_renders_steam_bytes_and_epic_digests():
    steam = metadata("profile_metadata.json")
    steam_header = header(rendered_steam_profile())
    assert "struct CompatRange {unsigned rva,size;const unsigned char* bytes;};" in steam_header
    assert "static const unsigned char compat_bytes_0[]={" in steam_header
    rendered_ranges = steam_header.split("compat_ranges[]={", 1)[1].split("};", 1)[0]
    assert rendered_ranges.count("compat_bytes_") == len(steam["ranges"])
    assert "FM27_COMPAT_DIGEST_RANGES" not in steam_header
    assert "#define FM27_COMPAT_ACTIVATION_FLAG compat_activation_flag" in steam_header
    assert f"compat_activation_flag={steam['activation_flag_rva']}u;" in steam_header
    epic = metadata("epic_profile_metadata.json")
    epic_header = header(epic, digest_ranges=True)
    assert re.search(r"^#define FM27_COMPAT_DIGEST_RANGES$", epic_header, re.MULTILINE)
    assert "struct CompatRange {unsigned rva,size;const char* sha256;};" in epic_header
    assert f"compat_activation_flag={epic['activation_flag_rva']}u;" in epic_header
    assert "compat_bytes_" not in epic_header
    assert json.dumps(epic["ranges"][0]["sha256"]) in epic_header
    assert len(re.findall(r"\{[0-9]+,", epic_header.split("compat_ranges[]={", 1)[1].split("};", 1)[0])) == len(epic["ranges"])


def test_platform_paths_cover_epic_build_and_export():
    assert adapter_paths("steam") == ("", ROOT / "private" / "engine")
    assert adapter_paths("epic") == ("epic_", ROOT / "private" / "epic-engine")
    build = (ROOT / "scripts" / "build_native.py").read_text(encoding="utf8")
    assert "'--platform'" in build
    assert "choices=('steam', 'epic')" in build
    assert "adapter_paths(" in build
    assert (ROOT / "scripts" / "rebase_profile.py").is_file()
    exported = {path.relative_to(ROOT).as_posix() for path in source_files()}
    assert {"native/epic_adapter_version.json", "native/epic_profile_metadata.json"} <= exported
