"""Compile the checked-in adapter using an x64 MSVC developer shell."""
import argparse
from pathlib import Path
import shutil
import subprocess

from generate_profile import adapter_paths, generate

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dll', required=True, type=Path)
    parser.add_argument('--platform', choices=('steam', 'epic'), default='steam')
    args = parser.parse_args()
    if not shutil.which('cl'):
        raise SystemExit('Run in an x64 Native Tools Command Prompt for Visual Studio (cl.exe required).')
    prefix, engine = adapter_paths(args.platform)
    generate(args.reference_dll, args.platform)
    out = ROOT / 'build' / (prefix + 'native')
    out.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / 'native').iterdir():
        if path.suffix in {'.h', '.cpp', '.manifest'}:
            shutil.copy2(path, out / path.name)
    shutil.copy2(ROOT / 'private' / (prefix + 'native') / 'engine_compat_profile.h', out / 'engine_compat_profile.h')
    subprocess.run(['cl', '/nologo', '/O2', '/EHsc', '/std:c++17', 'desktop_host.cpp',
                    '/Fe:FM27Simulator.exe', '/Fo:desktop_host.obj', '/link', '/INCREMENTAL:NO',
                    '/MANIFEST:EMBED', '/MANIFESTINPUT:host.manifest', 'user32.lib'], cwd=out, check=True)
    dest = engine / 'fm27_native'
    shutil.copy2(out / 'FM27Simulator.exe', dest / 'FM27Simulator.exe')
    shutil.copy2(ROOT / 'native' / (prefix + 'adapter_version.json'), dest / 'adapter_version.json')
    print('Built', dest / 'FM27Simulator.exe')


if __name__ == '__main__':
    main()
