"""Validate and export the public source allowlist, excluding all local build data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {'README.md', 'README.en.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md',
       'CHANGELOG.md', 'DESIGN.md', 'TODO.md', 'pyproject.toml', 'requirements.txt',
       '.gitignore', '.gitattributes'}
TYPES = {'src': {'.py', '.js', '.css', '.html'},
         'fm27lab': {'.py', '.sql', '.md'},
         'web': {'.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.json', '.svg', '.png', '.ico', '.yaml', '.yml'},
         'rust': {'.rs', '.toml', '.lock', '.md'},
         '.github': {'.yml', '.yaml', '.md'},
         'src-tauri': {'.rs', '.toml', '.json', '.md', '.sql', '.lock', '.png', '.ico', '.svg'},
         'scripts': {'.py'}, 'tests': {'.py', '.cjs'}, 'docs': {'.md'},
         'native': {'.cpp', '.h', '.manifest'}}
SKIP_PARTS = {'__pycache__', 'node_modules', 'target', 'dist', 'build', '.venv',
              '.toolchain', '.pytest_cache', '.ruff_cache', '.pnpm-store'}
NATIVE_JSON = {'native/profile_metadata.json', 'native/adapter_version.json'}
SCREENSHOTS = {'docs/screenshots/tactics.png', 'docs/screenshots/players.png',
               'docs/screenshots/results.png', 'docs/screenshots/save-tactics.png',
               'docs/screenshots/save-tactics-progress.png', 'docs/screenshots/away-pool.png'}
FORBIDDEN = {'engine_compat_profile.h', 'engine_compat_profile.json'}
BINARY_SUFFIXES = {'.png': b'\x89PNG\r\n\x1a\n', '.ico': b'\x00\x00\x01\x00'}


def source_files(root=ROOT):
    root = Path(root)
    result = [root / name for name in TOP]
    result.extend(root / name for name in NATIVE_JSON)
    result.extend(root / name for name in SCREENSHOTS)
    for directory, suffixes in TYPES.items():
        result.extend(path for path in (root / directory).rglob('*')
                      if path.is_file() and path.suffix in suffixes
                      and not (set(path.relative_to(root).parts) & SKIP_PARTS)
                      and path.name not in FORBIDDEN)
    return sorted(set(result))


def validate_binary_asset(path):
    expected = BINARY_SUFFIXES.get(Path(path).suffix.lower())
    if expected is None:
        return False
    if not Path(path).read_bytes().startswith(expected):
        raise ValueError('Unexpected binary asset signature: ' + str(path))
    return True


def validate(root=ROOT):
    root = Path(root)
    paths = source_files(root)
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or symlinked public source: ' + str(path))
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Source escapes release directory: ' + str(path))
        if validate_binary_asset(path):
            continue
        text = path.read_text(encoding='utf-8-sig')
        # Public sources must not contain workstation paths or game code dumps.
        if re.search(r'[A-Za-z]:[\\/]+Users[\\/]|F:[\\/]+FmEngine', text, re.I):
            raise ValueError('Workstation path found: ' + str(path.relative_to(root)))
        if re.search(r'(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----', text):
            raise ValueError('Potential credential found: ' + str(path.relative_to(root)))
        if re.search(r'[0-9a-fA-F]{512,}', text):
            raise ValueError('Unexpected long hexadecimal dump: ' + str(path.relative_to(root)))
    profile = json.loads((root / 'native/profile_metadata.json').read_text(encoding='utf8'))
    if any('hex' in row for row in profile['ranges']):
        raise ValueError('Original game function bytes must not be published')
    return paths


def export(output, root=ROOT):
    root, output = Path(root), Path(output).resolve()
    paths = validate(root)
    if output in [path.resolve() for path in paths]:
        raise ValueError('Output would overwrite public source')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'fm-tactics-lab/' + path.relative_to(root).as_posix())
        archive.writestr('fm-tactics-lab/SOURCE_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'archive': str(output), 'files': len(paths),
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/fm-tactics-lab-v2.0.0-source.zip')
    export(parser.parse_args().output)
