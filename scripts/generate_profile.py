"""Recreate private comparison bytes from the exact supported local game DLL."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct

from profile_header import header

ROOT = Path(__file__).resolve().parents[1]


def pe_sections(raw):
    if raw[:2] != b'MZ':
        raise ValueError('Not a PE file')
    offset = struct.unpack_from('<I', raw, 0x3c)[0]
    if raw[offset:offset + 4] != b'PE\0\0':
        raise ValueError('Invalid PE signature')
    machine, count = struct.unpack_from('<HH', raw, offset + 4)
    optional_size = struct.unpack_from('<H', raw, offset + 20)[0]
    if machine != 0x8664 or count > 96:
        raise ValueError('Expected x64 PE image')
    result = []
    start = offset + 24 + optional_size
    for index in range(count):
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from(
            '<IIII', raw, start + index * 40 + 8)
        result.append((rva, raw_size, raw_offset))
    return result


def read_rva(raw, sections, rva, size):
    for start, length, offset in sections:
        if start <= rva and rva + size <= start + length:
            value = raw[offset + rva - start:offset + rva - start + size]
            if len(value) == size:
                return value
    raise ValueError(f'Unmapped or truncated range: {rva:#x}, {size}')


def restore_profile(metadata, raw):
    if hashlib.sha256(raw).hexdigest() != metadata['reference_sha256']:
        raise ValueError('Reference DLL SHA256 mismatch; refusing to bless a different build')
    sections = pe_sections(raw)
    profile = copy.deepcopy(metadata)
    for item in profile['ranges']:
        value = read_rva(raw, sections, item['rva'], item['size'])
        if hashlib.sha256(value).hexdigest() != item.pop('sha256'):
            raise ValueError(f'Range checksum mismatch: {item["rva"]:#x}')
        item.pop('size')
        item['hex'] = value.hex()
    return profile


def adapter_paths(platform):
    prefix = 'epic_' if platform == 'epic' else ''
    engine = ROOT / 'private' / ('epic-engine' if platform == 'epic' else 'engine')
    return prefix, engine


def generate(dll, platform='steam'):
    prefix, engine = adapter_paths(platform)
    metadata = json.loads((ROOT / 'native' / (prefix + 'profile_metadata.json')).read_text(encoding='utf8'))
    profile = restore_profile(metadata, Path(dll).read_bytes())
    if platform == 'epic':
        profile = metadata
    native = ROOT / 'private' / (prefix + 'native')
    engine = engine / 'fm27_native'
    native.mkdir(parents=True, exist_ok=True)
    engine.mkdir(parents=True, exist_ok=True)
    (native / 'engine_compat_profile.h').write_text(header(profile, digest_ranges=platform == 'epic'), encoding='ascii')
    (engine / 'engine_compat_profile.json').write_text(json.dumps(profile, indent=2), encoding='utf8')
    print('Generated private compatibility contract from the verified local reference DLL.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dll', required=True, type=Path)
    parser.add_argument('--platform', choices=('steam', 'epic'), default='steam')
    args = parser.parse_args()
    generate(args.reference_dll, args.platform)
