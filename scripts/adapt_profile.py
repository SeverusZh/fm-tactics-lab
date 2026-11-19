"""Relocate the native adapter contract to a locally installed game build.

The public profile metadata carries masked window digests and operand descriptors
for the reference build.  This tool locates those windows in the installed image,
transfers call and data references, and writes a runtime profile for the native
host.  It never needs the reference DLL; every produced profile is bound to the
installed image hash and is rejected by the host when the image changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
DEFAULT_REFERENCE = ROOT / "private" / "engine" / "fm27_native" / "engine_compat_profile.json"
DEFAULT_METADATA = NATIVE / "profile_metadata.json"
CODE_LIMIT = 0x4BDD000
BRANCHES = {
    "call", "jmp", "je", "jne", "jz", "jnz", "jg", "jge", "jl", "jle", "ja", "jae",
    "jb", "jbe", "js", "jns", "jo", "jno", "jp", "jnp", "loop", "loope", "loopne",
}
OPERAND_REL = 0
OPERAND_RIP = 1
OPERAND_ABS = 2


@dataclass(frozen=True)
class Section:
    name: str
    rva: int
    virtual_size: int
    raw_size: int
    raw_offset: int
    flags: int

    @property
    def end(self) -> int:
        return self.rva + max(self.virtual_size, self.raw_size)


@dataclass
class PeImage:
    raw: bytes
    image_base: int
    image_size: int
    sections: list[Section]
    functions: list[tuple[int, int]]

    def offset(self, rva: int) -> int | None:
        for section in self.sections:
            if section.rva <= rva < section.rva + section.raw_size:
                return section.raw_offset + rva - section.rva
        return None

    def rva(self, offset: int) -> int | None:
        for section in self.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                return section.rva + offset - section.raw_offset
        return None

    def read(self, rva: int, size: int) -> bytes | None:
        offset = self.offset(rva)
        if offset is None or offset + size > len(self.raw):
            return None
        return self.raw[offset:offset + size]

    def section(self, rva: int) -> Section | None:
        for section in self.sections:
            if section.rva <= rva < section.end:
                return section
        return None

    def contains(self, rva: int) -> bool:
        return 0x1000 <= rva < self.image_size and self.section(rva) is not None

    def function(self, rva: int) -> tuple[int, int] | None:
        for start, end in self.functions:
            if start <= rva < end:
                return start, end
        return None


def parse_pe(raw: bytes) -> PeImage:
    if len(raw) < 0x100 or raw[:2] != b"MZ":
        raise ValueError("not a PE image")
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    if raw[pe:pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature")
    machine, count = struct.unpack_from("<HH", raw, pe + 4)
    optional_size = struct.unpack_from("<H", raw, pe + 20)[0]
    if machine != 0x8664 or count > 96:
        raise ValueError("expected x64 PE image")
    optional = pe + 24
    image_base = struct.unpack_from("<Q", raw, optional + 24)[0]
    image_size = struct.unpack_from("<I", raw, optional + 56)[0]
    data_dirs = [struct.unpack_from("<II", raw, optional + 112 + 8 * index) for index in range(16)]
    sections = []
    table = optional + optional_size
    for index in range(count):
        base = table + 40 * index
        name = raw[base:base + 8].rstrip(b"\0").decode("ascii", "replace")
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", raw, base + 8)
        flags = struct.unpack_from("<I", raw, base + 36)[0]
        sections.append(Section(name, rva, virtual_size, raw_size, raw_offset, flags))
    image = PeImage(raw, image_base, image_size, sections, [])
    exception_rva, exception_size = data_dirs[3]
    if exception_rva and exception_size and exception_size % 12 == 0:
        offset = image.offset(exception_rva)
        if offset is not None and offset + exception_size <= len(raw):
            for index in range(exception_size // 12):
                begin, end, _unwind = struct.unpack_from("<III", raw, offset + 12 * index)
                if image.contains(begin) and end > begin:
                    image.functions.append((begin, end))
    image.functions.sort()
    return image


def sha256_prefix(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def signed32(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=True)


def disassemble(data: bytes, rva: int) -> list[tuple[int, bytes, str]]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
        handle.write(data)
        path = handle.name
    try:
        output = subprocess.run(
            ["objdump", "-D", "-b", "binary", "-m", "i386:x86-64", "-M", "intel", "--insn-width=16", f"--adjust-vma={rva}", path],
            capture_output=True, text=True, check=True,
        ).stdout
    finally:
        Path(path).unlink(missing_ok=True)
    instructions = []
    for line in output.splitlines():
        match = re.match(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$", line)
        if match:
            instructions.append((int(match.group(1), 16), bytes.fromhex(match.group(2)), match.group(3).strip()))
    return instructions


def descriptors(instructions: list[tuple[int, bytes, str]], base: int) -> list[list[int]]:
    result = []
    for address, body, text in instructions:
        length = len(body)
        end = address + length
        start = address - base
        mnemonic = text.split()[0] if text else ""
        if mnemonic in BRANCHES:
            operand = text[len(mnemonic):].strip()
            if re.match(r"^(0x)?[0-9a-f]+$", operand):
                size = 1 if (body[0] == 0xEB or 0x70 <= body[0] <= 0x7F or mnemonic.startswith("loop")) else 4
                target = int(operand, 16)
                result.append([start + length - size, size, OPERAND_REL, end - base, target])
        if "rip+" in text or "rip-" in text:
            match = re.search(r"rip([+-])0x([0-9a-f]+)", text)
            if match:
                displacement = int(match.group(2), 16) * (1 if match.group(1) == "+" else -1)
                displacement &= 0xFFFFFFFF
                if displacement >= 0x80000000:
                    displacement -= 0x100000000
                position = body.rfind(struct.pack("<i", displacement))
                offset = start + (position if position >= 0 else length - 4)
                target = end + displacement
            else:
                offset = start + length - 4
                target = end + signed32(body[-4:])
            result.append([offset, 4, OPERAND_RIP, end - base, target])
        if mnemonic == "movabs":
            match = re.search(r"0x([0-9a-f]{9,})", text)
            if match:
                value = int.from_bytes(body[-8:], "little")
                if 0x180001000 <= value < 0x180000000 + 0x20000000:
                    offset = start + length - 8
                    result.append([offset, 8, OPERAND_ABS, end - base, value])
    return result


def masked_windows(data: bytes, ops: list[list[int]]) -> list[list[object]]:
    mask = bytearray(b"\x01" * len(data))
    for offset, size, *_rest in ops:
        for index in range(offset, offset + size):
            mask[index] = 0
    runs = []
    index = 0
    while index < len(mask):
        if mask[index]:
            end = index
            while end < len(mask) and mask[end]:
                end += 1
            runs.append((index, end))
            index = end
        else:
            index += 1
    windows = []
    for length in (16, 8):
        candidates = [(start, end) for start, end in runs if end - start >= length]
        if not candidates:
            continue
        picks = sorted({candidates[0], candidates[len(candidates) // 2], candidates[-1]})
        for start, end in picks:
            offset = start
            while offset + length <= end and len(windows) < 6:
                windows.append([offset, length, sha256_prefix(data[offset:offset + length])])
                offset += length
        if windows:
            break
    return windows


def build_signatures(metadata: dict, reference: dict) -> dict:
    old_ranges = {row["rva"]: row for row in reference["ranges"]}
    rows = []
    for row in metadata["ranges"]:
        reference_row = old_ranges.get(row["rva"])
        if reference_row is None or "hex" not in reference_row:
            continue
        data = bytes.fromhex(reference_row["hex"])
        if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            continue
        item = {"rva": row["rva"], "size": row["size"], "kind": "data"}
        if row["rva"] < CODE_LIMIT and row["size"] > 8 and not (row["size"] == 5 and data[0] == 0xE9):
            instructions = disassemble(data, row["rva"])
            covered = 0
            aligned = bool(instructions)
            for address, body, _text in instructions:
                if address != row["rva"] + covered:
                    aligned = False
                    break
                covered += len(body)
            if aligned and covered == len(data):
                ops = descriptors(instructions, row["rva"])
                windows = masked_windows(data, ops)
                if windows:
                    item = {
                        "rva": row["rva"],
                        "size": row["size"],
                        "kind": "code",
                        "windows": windows,
                        "ops": ops,
                    }
        if row["size"] == 5 and data[0] == 0xE9:
            item = {"rva": row["rva"], "size": row["size"], "kind": "stub"}
        rows.append(item)
    existing = {row["rva"] for row in rows}
    for anchor in extract_at_anchors():
        if anchor not in existing:
            rows.append({"rva": anchor, "size": 8, "kind": "data"})
    rows.sort(key=lambda row: row["rva"])
    used = sum(1 for row in rows if row["kind"] == "code")
    return {
        "schema": 1,
        "reference_id": metadata["id"],
        "reference_sha256": metadata["reference_sha256"],
        "source_reference_id": reference.get("id"),
        "source_reference_sha256": reference.get("reference_sha256"),
        "mixed_reference": reference.get("reference_sha256") != metadata["reference_sha256"],
        "reference_image_base": 0x180000000,
        "used_code_ranges": used,
        "ranges": rows,
    }


def extract_at_anchors() -> list[int]:
    anchors = set()
    sources = [path for path in (NATIVE / "").iterdir() if path.suffix in {".h", ".cpp"}]
    for path in sources:
        text = path.read_text(encoding="utf8")
        anchors.update(int(value, 16) for value in re.findall(r"\bat\(0x([0-9a-fA-F]+)\)", text))
        anchors.update(int(value, 16) for value in re.findall(r"(?<![A-Za-z0-9_])(?:module|base)\s*\+\s*0x([0-9a-fA-F]+)", text))
    return sorted(value for value in anchors if value < 0xF0000000)


def locate(image: PeImage, signatures: dict) -> dict[int, int]:
    mapped: dict[int, int] = {}
    for item in signatures["ranges"]:
        if item.get("kind") != "code" or not item.get("windows"):
            continue
        size = item["size"]
        windows = item["windows"]
        required = min(2, len(windows))
        best: tuple[int, int] | None = None
        runner_up: tuple[int, int] | None = None
        for start, end in image.functions:
            candidate_size = end - start
            if candidate_size * 2 + 64 < size or size * 2 + 64 < candidate_size:
                continue
            matches = 0
            for offset, length, digest in windows:
                data = image.read(start + offset, length)
                if data is not None and sha256_prefix(data) == digest:
                    matches += 1
            if matches < required:
                continue
            score = matches * 1_000_000 - abs(candidate_size - size)
            if best is None or score > best[0]:
                runner_up = best
                best = (score, start)
            elif runner_up is None or score > runner_up[0]:
                runner_up = (score, start)
        if best is None:
            continue
        if runner_up is not None and best[0] - runner_up[0] < 100_000:
            continue
        if len(windows) == 1 and abs((image.function(best[1]) or (best[1], best[1]))[1] - best[1] - size) > 8:
            continue
        mapped[item["rva"]] = best[1]
    return mapped


def propagate(image: PeImage, signatures: dict, mapped: dict[int, int]) -> dict[int, int]:
    items = {item["rva"]: item for item in signatures["ranges"]}
    anchors = set(items)
    reference_base = int(signatures.get("reference_image_base", 0x180000000))
    targets: dict[int, int] = {}
    for _iteration in range(6):
        added = 0
        for old_rva, new_rva in list(mapped.items()):
            item = items.get(old_rva)
            if item is None:
                continue
            for offset, size, kind, end_offset, old_target in item.get("ops", []):
                body = image.read(new_rva + offset, size)
                if body is None:
                    continue
                if kind in (OPERAND_REL, OPERAND_RIP):
                    new_target = new_rva + end_offset + signed32(body)
                    old_target_rva = old_target
                else:
                    new_target = int.from_bytes(body, "little") - image.image_base
                    old_target_rva = old_target - reference_base
                if image.contains(old_target_rva) and image.contains(new_target):
                    existing = targets.get(old_target_rva)
                    if existing is None:
                        targets[old_target_rva] = new_target
                    elif existing != new_target:
                        targets[old_target_rva] = 0
        for old_rva in sorted(anchors):
            if old_rva in mapped:
                continue
            if targets.get(old_rva):
                mapped[old_rva] = targets[old_rva]
                added += 1
                continue
            for start, new_start in list(mapped.items()):
                item = items.get(start)
                if item is not None and start <= old_rva < start + item["size"]:
                    mapped[old_rva] = new_start + (old_rva - start)
                    added += 1
                    break
        if not added:
            break
    return mapped


def render_profile(image: PeImage, mapped_at: dict[int, int], missing: list[int], partial: bool, reference_id: str) -> str:
    lines = [
        "fm27-adapter-profile 1",
        f"reference {reference_id}",
        f"image {hashlib.sha256(image.raw).hexdigest()}",
        f"partial {1 if partial else 0}",
        f"missing {len(missing)}",
        f"activation {0}",
    ]
    for old_rva, new_rva in sorted(mapped_at.items()):
        lines.append(f"map {old_rva:x} {new_rva:x}")
    return "\n".join(lines) + "\n"


def adapt(dll: Path, metadata_path: Path, reference_path: Path | None, allow_partial: bool, out: Path) -> dict:
    raw = dll.read_bytes()
    image = parse_pe(raw)
    metadata = json.loads(metadata_path.read_text(encoding="utf8"))
    signatures = metadata.get("signatures")
    if signatures and (signatures.get("reference_id") != metadata.get("id") or signatures.get("reference_sha256") != metadata.get("reference_sha256")):
        raise SystemExit("profile metadata signatures do not match its reference identity")
    if not signatures:
        if reference_path is None or not reference_path.is_file():
            raise SystemExit("profile metadata has no signatures and no reference profile was supplied")
        signatures = build_signatures(metadata, json.loads(reference_path.read_text(encoding="utf8")))
    mapped = locate(image, signatures)
    mapped = propagate(image, signatures, mapped)
    anchors = extract_at_anchors()
    items = {item["rva"]: item for item in signatures["ranges"]}
    mapped_at: dict[int, int] = {}
    missing: list[int] = []
    for anchor in anchors:
        if anchor in mapped:
            item = items.get(anchor)
            if item is not None and item.get("kind") == "code" and image.function(mapped[anchor]) is None:
                missing.append(anchor)
                continue
            mapped_at[anchor] = mapped[anchor]
            continue
        contained = False
        for old_rva, new_rva in mapped.items():
            item = items.get(old_rva)
            if item is not None and old_rva <= anchor < old_rva + item["size"]:
                mapped_at[anchor] = new_rva + (anchor - old_rva)
                contained = True
                break
        if not contained:
            missing.append(anchor)
    report = {
        "image_sha256": hashlib.sha256(raw).hexdigest(),
        "reference_id": signatures.get("reference_id"),
        "at_anchors": len(anchors),
        "mapped_anchors": len(mapped_at),
        "missing_anchors": [f"0x{value:x}" for value in missing],
        "located_ranges": len(mapped),
        "ranges": len(signatures["ranges"]),
        "pdata_functions": len(image.functions),
        "pdata_missing": not image.functions,
        "complete": not missing,
        "partial_profile": bool(missing) and allow_partial,
    }
    report_path = out if out.suffix == ".json" else out.with_suffix(out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    if out.suffix != ".json" and image.functions and (not missing or allow_partial):
        out.write_text(render_profile(image, mapped_at, missing, bool(missing) and allow_partial, signatures["reference_id"]), encoding="utf8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--write-signatures", action="store_true")
    parser.add_argument("--allow-mixed-reference", action="store_true")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf8"))
    if args.write_signatures:
        if not args.reference.is_file():
            raise SystemExit("reference profile is required to write signatures")
        signatures = build_signatures(metadata, json.loads(args.reference.read_text(encoding="utf8")))
        if signatures["mixed_reference"] and not args.allow_mixed_reference:
            raise SystemExit("reference image hash differs from metadata; pass --allow-mixed-reference after checking range digests")
        if signatures["used_code_ranges"] * 2 < len(metadata["ranges"]):
            raise SystemExit("reference profile covers too few ranges to publish signatures")
        metadata["signatures"] = signatures
        temporary = args.metadata.with_suffix(args.metadata.suffix + ".tmp")
        temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf8")
        temporary.replace(args.metadata)
        print(json.dumps({"signatures": len(signatures["ranges"]), "used_code_ranges": signatures["used_code_ranges"], "mixed_reference": signatures["mixed_reference"]}))
        return 0
    report = adapt(args.dll, args.metadata, args.reference, args.allow_partial, args.out)
    print(json.dumps(report, indent=2))
    return 0 if report["complete"] or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
