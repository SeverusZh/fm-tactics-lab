"""Render the runtime adapter profile for the known FM27 27.1.x builds."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
RVA_HEADER = NATIVE / "steam_27_1_rvas.h"
PROFILES = {
    "steam_27_1": {
        "platform": "steam",
        "metadata": NATIVE / "steam_27_1_profile.json",
        "header": RVA_HEADER,
        "output": NATIVE / "steam_27_1_profile.txt",
    },
    "steam_27_1_1": {
        "platform": "steam",
        "metadata": NATIVE / "steam_27_1_1_profile.json",
        "header": NATIVE / "steam_27_1_1_rvas.h",
        "output": NATIVE / "steam_27_1_1_profile.txt",
    },
    "epic_27_1": {
        "platform": "epic",
        "metadata": NATIVE / "epic_27_1_profile.json",
        "header": RVA_HEADER,
        "output": NATIVE / "epic_27_1_profile.txt",
    },
}
PLATFORMS = {"steam": "steam_27_1", "epic": "epic_27_1", "steam_27_1_1": "steam_27_1_1"}
LAYOUT_KEYS = (
    "steam_27_1",
    "manager",
    "player_input",
    "player_runtime",
    "player_statistics",
    "tactic_version",
    "execution_sample_stack",
)
_CASE = re.compile(r"case\s+(0x[0-9a-fA-F]+):\s*return\s+(0x[0-9a-fA-F]+);")


def rva_map(path: Path) -> list[tuple[int, int]]:
    pairs = [(int(source, 16), int(target, 16)) for source, target in _CASE.findall(path.read_text(encoding="utf8"))]
    if not pairs:
        raise ValueError("no 27.1 RVA mappings")
    if len({source for source, _target in pairs}) != len(pairs):
        raise ValueError("duplicate 27.1 RVA source")
    if len({target for _source, target in pairs}) != len(pairs):
        raise ValueError("duplicate 27.1 RVA target")
    return pairs


def load_profile(platform: str) -> tuple[dict, list[tuple[int, int]]]:
    entry = PROFILES[PLATFORMS[platform]]
    return json.loads(entry["metadata"].read_text(encoding="utf8")), rva_map(entry["header"])


def render(metadata: dict, mappings: list[tuple[int, int]]) -> str:
    image = metadata.get("image")
    reference = metadata.get("reference")
    activation = metadata.get("activation")
    layout = metadata.get("layout")
    if not isinstance(image, str) or len(image) != 64:
        raise ValueError("profile image must be a sha256")
    if not isinstance(reference, str) or not reference:
        raise ValueError("profile reference is required")
    if type(activation) is not int or activation < 0:
        raise ValueError("profile activation is required")
    if not isinstance(layout, dict) or set(layout) != set(LAYOUT_KEYS):
        raise ValueError("profile layout keys are incomplete")
    for key in LAYOUT_KEYS:
        if type(layout[key]) is not int or layout[key] < 0:
            raise ValueError(f"profile layout {key} is invalid")
    lines = [
        "fm27-adapter-profile 1",
        f"image {image}",
        f"reference {reference}",
        f"activation 0x{activation:x}",
        f"partial {metadata.get('partial', 0)}",
        f"missing {metadata.get('missing', 0)}",
    ]
    lines.extend(f"layout_{key} 0x{layout[key]:x}" for key in LAYOUT_KEYS)
    lines.extend(f"map 0x{source:x} 0x{target:x}" for source, target in mappings)
    return "\n".join(lines) + "\n"


def write(platform: str, output: Path) -> str:
    text = render(*load_profile(platform))
    output.write_text(text, encoding="utf8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=tuple(PLATFORMS), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or PROFILES[PLATFORMS[args.platform]]["output"]
    write(args.platform, output)
    print(output)


if __name__ == "__main__":
    main()
