# Development

## v2 development stack

The v2 refactor uses Tauri 2 + Rust for the desktop shell, Python 3.12 for the sidecar, and React 19 + TypeScript + Vite for the interface. The native FM27 adapter remains C++17.

### Requirements

- Windows x64 for the desktop build; Linux is supported for Python, frontend and Rust core tests.
- Python 3.12 x64, Node 22+, pnpm 11, Rust stable and MSVC C++17 with the Windows SDK.
- WebView2 on the target machine.
- A local FM27 installation; the adapter reference build is `27.0.1+2494687`.

### Python sidecar

```bash
python -m pip install -e ".[dev]"
python -m fm27lab serve --data-dir data --engine-root <engine-workspace> --dev --port 18765
python -m pytest
python -m unittest discover -s tests
```

The sidecar writes `data/agent/endpoint.json` on startup and removes it on shutdown. Do not commit that file or any `.db` database.

### Frontend

```bash
pnpm --dir web install
pnpm --dir web dev
pnpm --dir web run typecheck
pnpm --dir web test
pnpm --dir web run build
```

The Vite dev server runs on `http://localhost:1420`. In a browser without Tauri, set `VITE_API_URL` and `VITE_API_TOKEN` to a running sidecar.

### Tauri shell

```bash
cargo install tauri-cli --version "^2"
cargo tauri dev
cargo tauri build
```

Tauri runs `pnpm --dir ../web dev` in development and packages `web/dist` in release. The Python sidecar and native host must be packaged before a release build; the current branch has not yet produced a Tauri installer.

### Rust core

```bash
cargo test --manifest-path rust/Cargo.toml -p fm27lab-core
cargo check --manifest-path src-tauri/Cargo.toml
```

The Tauri shell requires WebKitGTK on Linux and is compiled on Windows CI instead.

### Source export

```bash
python scripts/export_source.py --output dist/fm-tactics-lab-v2.0.0-source.zip
```

The exporter uses an explicit allowlist and rejects workstation paths and credentials. `SOURCE_MANIFEST.json` must be regenerated after adding public files.

## Legacy v1111 build

The following instructions describe the previous C# launcher and Python HTTP service. They are retained only while the legacy app is being retired.

## Requirements

- Windows x64, full CPython 3.12 x64, and MSVC C++17 with the Windows SDK.
- A local FM27 installation; the adapter reference build is `27.0.0+2493426`.
- A verified v1108.5 EXE from this repository's Releases, used to supply the matching initial inputs.

Install the save reader and its compression dependency from requirements.txt in the build environment.

## Prepare local inputs

Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts/prepare_private.py --release-exe "D:\Downloads\FM27-Tactics-Lab-v1108.5.exe"
```

The script checks the original EXE and embedded payload SHA256, then reads only the named input assets into ignored `private/` directories. It does not execute the EXE. An existing matching asset directory can alternatively be supplied with `--assets-root` and `--catalog`.

## Build the native adapter

In an **x64 Native Tools Command Prompt for Visual Studio**:

```bat
.venv\Scripts\python.exe scripts\build_native.py --reference-dll "D:\Games\Football Manager 27\fm_Data\Plugins\x86_64\game_plugin.dll"
```

The public repository contains range metadata and digests. The script reconstructs comparison bytes from the exact reference DLL on your machine, verifies every range, then compiles the checked-in C++ host. Generated function bytes remain in ignored local outputs.

## Run from source

```powershell
.venv\Scripts\python.exe scripts/run.py --game-root "D:\Games\Football Manager 27"
```

Open the printed loopback URL after startup. Press `Ctrl+C` to stop the source edition.

## Build a local desktop EXE

```powershell
.venv\Scripts\python.exe scripts/build_exe.py --python-home "D:\Python312"
```

Supply a full CPython 3.12 x64 distribution containing `Lib`, `DLLs`, `python312.dll`, the runtime libraries and `LICENSE.txt`. The script uses the .NET Framework C# compiler; `--csc` can override its location. Output: `dist/FM27-Tactics-Lab-v1108.5.exe`.

The build script packages the save reader from the active Python environment. The release EXE and a local build can have different hashes.

## Validate and export source

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/export_source.py
```

The exporter uses an explicit source allowlist, checks for workstation paths and common credential formats, and writes file digests inside the archive. It excludes game DLLs, runtime data, input snapshots and generated comparison bytes.

The EXE release is a separate asset authorized for distribution by the maintainer. Its embedded initial inputs and comparison data are outside the MIT grant for tool code. See [third-party notices](../THIRD_PARTY_NOTICES.md).
