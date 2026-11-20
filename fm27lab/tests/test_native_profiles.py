from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native"
sys.path.insert(0, str(ROOT / "scripts"))

from compile_native_stub import write as write_stub  # noqa: E402
from export_source import source_files  # noqa: E402
from generate_profile import adapter_paths  # noqa: E402
from profile_header import header  # noqa: E402
from static_profile import LAYOUT_KEYS, load_metadata, render, rva_map  # noqa: E402

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
    assert STEAM_SHA256 in execution
    assert "execution_image=adapter_profile.image_sha256.c_str();" in execution
    assert "native_layout::tactic_version()" in execution
    assert "native_layout::execution_sample_stack()" in execution
    assert "epic_27_1_execution_unverified" in execution


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
    assert {
        "native/steam_27_1_profile.json",
        "native/steam_27_1_profile.txt",
        "native/epic_27_1_profile.json",
        "native/epic_27_1_profile.txt",
        "native/steam_27_1_rvas.h",
        "native/native_layout.h",
    } <= exported


def test_27_1_runtime_profiles_are_complete_and_bound_to_the_compiled_reference():
    mappings = rva_map()
    assert len(mappings) == 105
    assert len(set(source for source, _target in mappings)) == len(mappings)
    assert len(set(target for _source, target in mappings)) == len(mappings)
    for platform, reference, image, activation in (
        ("steam", "fm27_desktop_8c6971ce_adapter_v1", "d12202dd01c3911d4c4e55e778f37b2251ffb10f9cf8cecc3b9ec08ece622c6b", 398482872),
        ("epic", "fm27_desktop_ebf6fcf5_adapter_v1", "f39d5d97aeb62f579cac0255d43bba29e34bc56d984eadea579805cfa275d0f1", 390611544),
    ):
        metadata = load_metadata(platform)
        assert metadata["reference"] == reference
        assert metadata["image"] == image
        assert metadata["activation"] == activation
        assert set(metadata["layout"]) == set(LAYOUT_KEYS)
        rendered = render(metadata, mappings)
        assert rendered.startswith("fm27-adapter-profile 1\n")
        assert f"image {image}\n" in rendered
        assert f"reference {reference}\n" in rendered
        assert rendered.count("layout_") == len(LAYOUT_KEYS)
        assert rendered.count("\nmap ") == len(mappings)
        assert (NATIVE / f"{platform}_27_1_profile.txt").read_text(encoding="utf8") == rendered


def test_27_1_profiles_keep_the_reference_layout_for_steam_and_epic():
    steam = load_metadata("steam")
    epic = load_metadata("epic")
    assert steam["layout"] == epic["layout"]
    assert steam["layout"]["steam_27_1"] == 1
    assert steam["layout"]["tactic_version"] == 0x1B010000
    assert steam["layout"]["execution_sample_stack"] == 0x108
    assert steam["image"] != epic["image"]
    assert steam["reference"] != epic["reference"]


def test_host_uses_runtime_layout_and_falls_back_to_the_compiled_reference():
    host = (NATIVE / "desktop_host.cpp").read_text(encoding="utf8")
    assert "#include \"native_layout.h\"" in host
    assert "#include \"fm27_adapter_profile.h\"" in host
    assert "adapter_profile.active" in host
    assert "adapter_profile_fallback" in host
    assert "image_sha256_mismatch" in host
    assert "FM27_STEAM_27_1" not in host
    assert "match_importance" not in host
    assert "native_match_rules_version" in host
    assert "native_layout::steam_27_1()" in host
    assert "native_layout::tactic_version()" in host
    assert "current_pi_policy_version()" in host
    at_start = host.index("static void* at(uintptr_t rva){")
    at_end = host.index("static int audit_policies(){", at_start)
    at_body = host[at_start:at_end]
    assert "adapter_profile.active" in at_body
    assert "adapter_profile.loaded" not in at_body
    assert "adapter_profile.active=true;" in host
    assert "manager+native_layout::manager(0x1908)" in host
    profile_branch = host.index("if(adapter_profile.active&&adapter_profile.activation_rva){")
    compiled_branch = host.index("}else if(!adapter_profile.active&&!exported_wait){", profile_branch)
    export_branch = host.index("}else if(exported_wait){", compiled_branch)
    assert profile_branch < compiled_branch < export_branch
    assert 'GetProcAddress(module,"WaitForActivation")' in host


def test_runtime_layout_defaults_keep_the_reference_build_and_apply_27_1_deltas():
    layout = (NATIVE / "native_layout.h").read_text(encoding="utf8")
    assert "adapter_profile.active" in layout
    assert "steam_27_1()" not in layout.split("inline uintptr_t rva", 1)[1].split("}", 1)[0]
    assert "layout_steam_27_1" in layout
    assert "layout_manager" in layout
    assert "layout_player_input" in layout
    assert "layout_player_runtime" in layout
    assert "layout_player_statistics" in layout
    assert "layout_tactic_version" in layout
    assert "layout_execution_sample_stack" in layout
    profile = (NATIVE / "fm27_adapter_profile.h").read_text(encoding="utf8")
    assert "bool active" in profile
    assert "layout_steam_27_1" in profile
    assert '"layout_manager"' in profile
    assert '"layout_steam_27_1"' in profile
    assert 'adapter_profile.error = "layout";' in profile


def test_27_1_headers_use_the_runtime_layout_at_the_known_sites():
    tactic_import = (NATIVE / "native_tactic_import.h").read_text(encoding="utf8")
    assert "auto plan=manager+native_layout::manager(0x1818);" in tactic_import
    assert "plan[0x105]" in tactic_import
    assert "plan[0xe0+j]" in tactic_import
    assert "plan[0x79c+j]" in tactic_import
    events = (NATIVE / "native_match_events.h").read_text(encoding="utf8")
    assert "native_layout::rva(0x4764c1d)" in events
    assert "native_layout::player_statistics(0x8b)" in events
    generation = (NATIVE / "native_source_generation.h").read_text(encoding="utf8")
    assert "native_layout::manager(0x2fc8)" in generation
    assert "native_layout::player_runtime(0x1880)" in generation
    fmf = (NATIVE / "native_fmf_probe.h").read_text(encoding="utf8")
    assert "native_layout::steam_27_1()" in fmf
    assert "desktop_fmf_stream_revision==61" in fmf
    build = (ROOT / "scripts" / "build_native.py").read_text(encoding="utf8")
    assert "steam_27_1_profile.txt" in build
    assert "epic_27_1_profile.txt" in build
    assert "adapter_profile.txt" in build


def test_27_1_map_covers_every_literal_host_anchor():
    mapped = {source for source, _target in rva_map()}
    used: set[int] = set()
    for path in NATIVE.glob("*"):
        if path.suffix not in {".h", ".cpp"}:
            continue
        for match in re.finditer(r"\bat\((0x[0-9a-fA-F]+)", path.read_text(encoding="utf8")):
            used.add(int(match.group(1), 16))
    assert used - {0xF0000000, 0xF0000001} <= mapped


def test_native_stub_profiles_compile_both_storefront_contracts(tmp_path):
    steam = write_stub(tmp_path / "steam").read_text(encoding="ascii")
    epic = write_stub(tmp_path / "epic", digest_ranges=True).read_text(encoding="ascii")
    for text in (steam, epic):
        assert "compat_profile_id" in text
        assert "compat_ranges[]=" in text
        assert "compat_sections[]=" in text
        assert "compat_data[]=" in text
        assert "compat_imports[]=" in text
        assert "compat_activation_flag=0u;" in text
    assert "FM27_COMPAT_DIGEST_RANGES" not in steam
    assert "FM27_COMPAT_DIGEST_RANGES" in epic
    assert "epic_reference_sha256" in epic
    assert "compat_bytes_0" in steam
    assert "compat_bytes_0" not in epic
