from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src-tauri" / "icons"


def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            diagonal = abs(x - y) < max(2, size // 12)
            band = size * 0.32 < x < size * 0.72 and size * 0.2 < y < size * 0.8
            if diagonal:
                color = (62, 207, 142, 255)
            elif band:
                color = (139, 61, 255, 255)
            else:
                color = (18, 16, 24, 255)
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico(size: int) -> bytes:
    image = png(size)
    width = 0 if size >= 256 else size
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(image), 22)
    return header + entry + image


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "32x32.png").write_bytes(png(32))
    (ROOT / "128x128.png").write_bytes(png(128))
    (ROOT / "128x128@2x.png").write_bytes(png(256))
    (ROOT / "icon.ico").write_bytes(ico(256))
    print("icons written to", ROOT)


if __name__ == "__main__":
    main()
