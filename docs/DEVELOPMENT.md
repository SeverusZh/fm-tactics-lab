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

The sidecar writes `data/agent/endpoint.json` on startup and removes it on shutdown. `fm27lab serve` runs without a UI and `fm27lab mcp` exposes the same service over stdio for MCP clients. Do not commit that file or any `.db` database.

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

The Windows CI job runs these steps for the installer:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web run build
python scripts/build_sidecar.py
cargo build --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
npm install --global @tauri-apps/cli@^2
tauri build --bundles nsis
```

`tauri dev` starts the Vite server and the desktop window; the shell launches the sidecar from `FM27LAB_SIDECAR` or from `python -m fm27lab serve` in a development checkout. The release build packages `web/dist` and the PyInstaller sidecar from `sidecar-dist`, and writes the NSIS installer to `src-tauri/target/release/bundle/nsis/`. The resource mapping must use the directory form so the onedir `_internal/` payload keeps its layout; the CI job asserts the staged `_internal` directory, then extracts the installer with 7-Zip and asserts `sidecar/_internal`, the Python runtime and the migrations.

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

## Source edition

The source edition runs the Python HTTP service from `src` in a browser. It is separate from the Tauri desktop build and requires the private engine assets below.

### Requirements

- Windows x64, full CPython 3.12 x64, and MSVC C++17 with the Windows SDK.
- A local FM27 installation; the adapter reference build is `27.0.0+2493426`.
- A verified v1108.5 EXE from this repository's Releases, used to supply the matching initial inputs.

Install the save reader and its compression dependency from requirements.txt in the build environment.

### Prepare local inputs

Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts/prepare_private.py --release-exe "D:\Downloads\FM27-Tactics-Lab-v1108.5.exe"
```

The script checks the original EXE and embedded payload SHA256, then reads only the named input assets into ignored `private/` directories. It does not execute the EXE. An existing matching asset directory can alternatively be supplied with `--assets-root` and `--catalog`.

### Build the native adapter

In an **x64 Native Tools Command Prompt for Visual Studio**:

```bat
.venv\Scripts\python.exe scripts\build_native.py --reference-dll "D:\Games\Football Manager 27\fm_Data\Plugins\x86_64\game_plugin.dll"
```

The public repository contains range metadata and digests. The script reconstructs comparison bytes from the exact reference DLL on your machine, verifies every range, then compiles the checked-in C++ host. Generated function bytes remain in ignored local outputs.

### Run from source

```powershell
.venv\Scripts\python.exe scripts/run.py --game-root "D:\Games\Football Manager 27"
```

Open the printed loopback URL after startup. Press `Ctrl+C` to stop the source edition.

### Validate and export source

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/export_source.py
```

The exporter uses an explicit source allowlist, checks for workstation paths and common credential formats, and writes file digests inside the archive. It excludes game DLLs, runtime data, input snapshots and generated comparison bytes.

The v1103.2, v1106 and v1108.5 EXE releases are separate assets authorized for distribution by the maintainer. Their embedded initial inputs and comparison data are outside the MIT grant for tool code. See [third-party notices](../THIRD_PARTY_NOTICES.md).
