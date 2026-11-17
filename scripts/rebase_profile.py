"""Carry the adapter contract (native/profile_metadata.json) to a new game_plugin.dll build.

Use when a game patch leaves the engine code the host calls in place but rebuilds the protected section
(.00cfg), as the 27.0.1 hotfix of 12 November did. The script reads only the new DLL:

- PE layout, sections, TLS and import bindings are re-read from the new DLL.
- A range whose bytes are unchanged keeps its digest. A changed range outside .00cfg (e.g. a 5-byte jmp
  stub into .00cfg) is listed and re-hashed only if it is a stub; anything else stops the script.
- Ranges inside .00cfg are dropped: the protected section is re-generated per build, and the host never
  calls into it directly (only through the .ecode stubs, which stay at the same RVAs).
- The activation word the host waits on lives in .00cfg, so it must be given (--activation-flag), or left
  unset until it has been located with FM27Simulator.exe --find-activation.

  python scripts/rebase_profile.py --dll "...\\fm_Data\\Plugins\\x86_64\\game_plugin.dll" --version 27.0.1+hotfix1112
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = '.00cfg'


class Pe:
    def __init__(self, raw):
        self.raw = raw
        pe = struct.unpack_from('<I', raw, 0x3c)[0]
        if raw[:2] != b'MZ' or raw[pe:pe + 4] != b'PE\0\0' or struct.unpack_from('<H', raw, pe + 4)[0] != 0x8664:
            raise ValueError('Expected an x64 PE image')
        count, opt_size = struct.unpack_from('<H', raw, pe + 6)[0], struct.unpack_from('<H', raw, pe + 20)[0]
        opt = pe + 24
        self.image_base = struct.unpack_from('<Q', raw, opt + 24)[0]
        self.entrypoint = struct.unpack_from('<I', raw, opt + 16)[0]
        self.size_of_image = struct.unpack_from('<I', raw, opt + 56)[0]
        self.size_of_headers = struct.unpack_from('<I', raw, opt + 60)[0]
        self.dirs = [struct.unpack_from('<II', raw, opt + 112 + 8 * i) for i in range(16)]
        self.sections = []
        for i in range(count):
            o = opt + opt_size + 40 * i
            name = raw[o:o + 8].rstrip(b'\0').decode('ascii', 'replace')
            vsize, rva, rsize, roff = struct.unpack_from('<IIII', raw, o + 8)
            flags = struct.unpack_from('<I', raw, o + 36)[0]
            self.sections.append((name, rva, vsize, rsize, roff, flags))

    def section(self, rva):
        for s in self.sections:
            if s[1] <= rva < s[1] + max(s[2], s[3]):
                return s
        return None

    def read(self, rva, n):
        if rva < self.size_of_headers:
            return self.raw[rva:rva + n]
        for name, start, vsize, rsize, roff, flags in self.sections:
            if start <= rva and rva + n <= start + rsize:
                return self.raw[roff + rva - start:roff + rva - start + n]
        raise ValueError(f'Unmapped range {rva:#x}+{n}')

    def cstr(self, rva):
        out = bytearray()
        while True:
            c = self.read(rva + len(out), 1)
            if c == b'\0':
                return out.decode('ascii')
            out += c

    def imports(self):
        found = {}
        rva = self.dirs[1][0]
        while True:
            oft, _, _, name, ft = struct.unpack('<IIIII', self.read(rva, 20))
            if not name and not ft:
                return found
            dll = self.cstr(name).lower()
            src, j = oft or ft, 0
            while True:
                value = struct.unpack('<Q', self.read(src + 8 * j, 8))[0]
                if not value:
                    break
                fn = '#' + str(value & 0xffff) if value & (1 << 63) else self.cstr((value & 0x7fffffff) + 2)
                found.setdefault((dll, fn), []).append(ft + 8 * j)
                j += 1
            rva += 20

    def tls(self):
        start, end, index, callbacks, zero = struct.unpack('<QQQQI', self.read(self.dirs[9][0], 36))
        values = {'raw_rva': start - self.image_base, 'raw_size': end - start,
                  'index_rva': index - self.image_base, 'zero_fill': zero}
        out, i = [], 0
        while True:
            cb = struct.unpack('<Q', self.read(callbacks - self.image_base + 8 * i, 8))[0]
            if not cb:
                return values, out
            out.append(cb - self.image_base)
            i += 1


def rebase(old, raw, version, flag):
    pe = Pe(raw)
    sha = hashlib.sha256(raw).hexdigest()
    new = dict(old)
    new['id'] = f'fm27_desktop_{sha[:8]}_adapter_v1'
    new['reference_sha256'] = sha
    new['image_base'] = pe.image_base
    new['entrypoint_rva'] = pe.entrypoint
    new['minimum_image_size'] = pe.size_of_image
    new['sections'] = [{'rva': s[1], 'memory_flags': s[5] & 0xe0000000} for s in pe.sections]
    new['tls'], new['tls_callbacks'] = pe.tls()

    table, imports, moved = pe.imports(), [], 0
    for item in old['imports']:
        rvas = table.get((item['dll'], item['name']))
        if not rvas:
            continue
        rva = item['rva'] if item['rva'] in rvas else rvas[0]
        moved += rva != item['rva']
        imports.append({'dll': item['dll'], 'name': item['name'], 'rva': rva})
    new['imports'] = imports

    ranges, report = [], {'unchanged': 0, 'stub_rehashed': [], 'dropped_protected': []}
    for item in old['ranges']:
        sec = pe.section(item['rva'])
        if sec and sec[0] == PROTECTED:
            report['dropped_protected'].append(hex(item['rva']))
            continue
        data = pe.read(item['rva'], item['size'])
        digest = hashlib.sha256(data).hexdigest()
        if digest == item['sha256']:
            report['unchanged'] += 1
        elif item['size'] == 5 and data[0] == 0xe9:
            target = item['rva'] + 5 + struct.unpack('<i', data[1:])[0]
            if pe.section(target)[0] != PROTECTED:
                raise ValueError(f'Stub {item["rva"]:#x} now jumps outside {PROTECTED}')
            report['stub_rehashed'].append(f'{item["rva"]:#x} -> {target:#x}')
        else:
            raise ValueError(f'Range changed outside {PROTECTED}: {item["rva"]:#x} ({item["purpose"]}); needs remapping')
        ranges.append({**item, 'sha256': digest})
    new['ranges'] = ranges

    for item in old['data_addresses']:
        if not pe.section(item['rva']) or pe.section(item['rva'])[0] == PROTECTED:
            raise ValueError(f'Data address {item["rva"]:#x} is in {PROTECTED} or unmapped')
    if flag is not None:
        sec = pe.section(flag)
        if not sec or sec[0] != PROTECTED or flag % 4:
            raise ValueError(f'Activation flag {flag:#x} must be a 4-aligned address in {PROTECTED}')
    new['activation_flag_rva'] = flag
    new['version'] = version
    report['imports_rebound'] = moved
    return new, report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dll', required=True, type=Path)
    parser.add_argument('--version', required=True, help='Label for adapter_version.json, e.g. 27.0.1+hotfix1112')
    parser.add_argument('--activation-flag', type=lambda v: int(v, 0), help='RVA of the activation word in .00cfg')
    parser.add_argument('--metadata', type=Path, default=ROOT / 'native/profile_metadata.json')
    args = parser.parse_args()
    old = json.loads(args.metadata.read_text(encoding='utf8'))
    old.setdefault('activation_flag_rva', 0x1718f818 if old['reference_sha256'].startswith('f79b0a34') else None)
    new, report = rebase(old, args.dll.read_bytes(), args.version, args.activation_flag)
    version = new.pop('version')
    args.metadata.write_text(json.dumps(new, indent=2) + '\n', encoding='utf8')
    prefix = 'epic_' if args.metadata.name == 'epic_profile_metadata.json' else ''
    adapter_path = ROOT / 'native' / (prefix + 'adapter_version.json')
    adapter = json.loads(adapter_path.read_text(encoding='utf8'))
    adapter.update(version=version, reference_dll_sha256=new['reference_sha256'])
    adapter_path.write_text(json.dumps(adapter, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'profile': new['id'], 'activation_flag_rva': new['activation_flag_rva'], **report}, indent=1))


if __name__ == '__main__':
    main()
