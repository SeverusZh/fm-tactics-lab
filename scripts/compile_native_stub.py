"""Generate a stub compatibility contract for a native-host compile check."""

from __future__ import annotations

import argparse
from pathlib import Path

from profile_header import header

STUB_PROFILE = {
    "id": "ci_native_stub",
    "reference_sha256": "0" * 64,
    "image_base": 0x140000000,
    "entrypoint_rva": 0x1000,
    "minimum_image_size": 0x2000,
    "sections": [{"rva": 0x1000, "memory_flags": 0}],
    "ranges": [{"rva": 0x1000, "size": 1, "hex": "00", "sha256": "0" * 64}],
    "data_addresses": [{"rva": 0x1000, "size": 1}],
    "imports": [{"dll": "kernel32.dll", "name": "GetTickCount64", "rva": 0x1000}],
    "tls": {"start": 0, "end": 0, "index": 0, "zero_fill": 0},
    "tls_callbacks": [0],
    "activation_flag_rva": 0,
}


def write(directory: str | Path, *, digest_ranges: bool = False) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / "engine_compat_profile.h"
    path.write_text(header(STUB_PROFILE, digest_ranges=digest_ranges), encoding="ascii")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--digest-ranges", action="store_true")
    args = parser.parse_args()
    print(write(args.output, digest_ranges=args.digest_ranges))


if __name__ == "__main__":
    main()
