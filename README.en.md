# FM Tactics Lab

> **This repository is independently maintained by SeverusZh.** It is a fork of [lqf0624/fm-tactics-lab](https://github.com/lqf0624/fm-tactics-lab). I refactor and release on my own schedule, may submit feature PRs upstream when appropriate, and do not guarantee tracking upstream updates. Upstream releases remain maintained by the upstream owner.

[简体中文](README.md) | **English**

**Test your tactics locally with the original FM27 match engine.**

FM Tactics Lab v2 is a Tauri 2 desktop app with a Python sidecar: the shell starts a local sidecar, a React 19 frontend calls it over loopback HTTP, and the sidecar drives your local FM27 engine through batches of complete matches. Manage a 23-player squad, two-phase tactics and player attributes, compare setups with the away tactic pool or same-seed A/B runs, and keep results in local SQLite. The same service is available to automation through a CLI and MCP.

Use it to answer:

- Which formation suits a given group of players?
- How do pressing, defensive line or role changes affect attack and defence?
- Does an advantage hold across seeds, opponents and home or away fixtures?

## Architecture

```text
Desktop shell Tauri 2 + React 19 ─┐
CLI                              ─┼── loopback HTTP + Bearer token ──> Python sidecar (fm27lab)
MCP client                       ─┘                                          │
                                                                             ├─ SQLite results
                                                                             └─ native engine workspace
```

- The sidecar only listens on loopback. After binding, it writes the url, port, token, pid, data_dir and engine_root to `<data_dir>/agent/endpoint.json` and removes the file on exit. Business `/api` requests require a Bearer token except `/api/health` and `/api/version`; `/api/docs` and `/api/openapi.json` are public documentation routes.
- The engine is constructed lazily. Without an available `catalog.json`, the runtime catalog returns `available=false` and experiment submission returns `400 validation_failed`; when engine execution raises, `POST /api/experiments/start` returns `503 engine_unavailable`. An engine workspace contains `fm27_native/FM27Simulator.exe` and `catalog.json`.
- Experiment pipeline: a draft and an optional baseline draft are materialized under `<data_dir>/agent/experiments/<job_id>/`, executed in parallel by the native engine thread pool, and stored in SQLite. The match count is seeds times variants, capped at 10000 matches and 10000 seeds.

## What works today

- Domain model: two-phase tactics with 11 players in each phase, a 23-player squad, 69 player attributes including 15 position attributes, and an away tactic pool with random or rotation draws and uniform or real-roster players.
- Experiment execution: same-seed A/B comparison, 1–256 workers, a resource pre-check that rejects submissions by default when less than 2 GiB of memory or insufficient disk is available, with an explicit override, and 14 metrics per job.
- Result analysis: per-match records, CSV export, home-side aggregation; job comparison over 1–32 candidates and 1–20000 resamples with paired deltas and bootstrap confidence intervals.
- Interfaces: 52 capabilities in 11 groups; OpenAPI lists 64 operations; the CLI has 55 leaf commands; MCP exposes 49 tools, 4 read-only resources and 2 prompts.
- Desktop: eight pages for tactics, players, saved-tactic library, experiments, results, jobs, settings and help; experiments and results are submitted and viewed from their own pages.

## Quick start

### Requirements

- Desktop build and run: Windows x64, Python 3.12 x64, Node 22+, pnpm 11, Rust stable, MSVC C++17 with the Windows SDK, and WebView2.
- Python, frontend and Rust core tests run on Linux.
- A local FM27 installation; the adapter reference build is `27.0.1+2494687`.
- An engine workspace containing `fm27_native/FM27Simulator.exe` and `catalog.json`; the catalog may sit at the workspace root or under `fm27_native/`.

### Install dependencies

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pnpm --dir web install
npm install --global @tauri-apps/cli@^2
```

### Start the sidecar

```powershell
python -m fm27lab serve --data-dir data --engine-root <engine workspace> --dev
```

The sidecar listens on loopback and takes its port from `--port`; the examples below use 18765. On Windows the default data directory is `%LOCALAPPDATA%\FM27TacticsDesktop`; `--data-dir` or `FM27LAB_DATA` overrides it.

### Desktop dev shell

```powershell
$env:FM27LAB_PYTHON="$PWD\.venv\Scripts\python.exe"
$env:FM27_ENGINE_ROOT="<absolute engine workspace path>"
tauri dev
```

- Run from the repository root; Tauri locates `src-tauri` by itself.
- A debug build starts `python -m fm27lab serve` from the shell; without `FM27LAB_PYTHON`, the python on PATH is used.
- The shell uses the app-local data directory, not the repository `data/`. Setting `FM27LAB_SIDECAR` makes the shell launch an existing sidecar executable instead.

### Browser frontend

```powershell
python -m fm27lab serve --data-dir data --engine-root <engine workspace> --dev --port 18765
$env:VITE_API_URL="http://127.0.0.1:18765"
$env:VITE_API_TOKEN=(Get-Content data\agent\endpoint.json | ConvertFrom-Json).token
pnpm --dir web dev
```

Vite listens on port 1420. In development, a browser without the Tauri shell uses `VITE_API_URL` and `VITE_API_TOKEN` to reach the sidecar.

### MCP setup

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "python",
      "args": ["-m", "fm27lab", "mcp"],
      "env": { "FM27LAB_DATA": "<absolute sidecar data_dir>" }
    }
  }
}
```

- Start the sidecar first; the MCP subcommand checks `/api/health` before connecting.
- `FM27LAB_DATA` must match the sidecar `--data-dir`.
- Put the global `--data-dir` before the subcommand, for example `python -m fm27lab --data-dir data mcp`.

### Build the desktop installer

```powershell
python scripts/build_sidecar.py
tauri build --bundles nsis
```

`tauri build` runs `pnpm --dir web build` and `scripts/build_sidecar.py` first, then writes the installer to `src-tauri/target/release/bundle/nsis/`.

### Source edition browser UI

Windows x64 only; it needs CPython 3.12 and MSVC. Prepare the private assets and compile the native adapter as described in the Source edition section of the [build guide](docs/DEVELOPMENT.md).

```powershell
.venv\Scripts\python.exe scripts/run.py --game-root "D:\Games\Football Manager 27"
```

The launcher prints a loopback address; press Ctrl+C to stop.

### Tests

```powershell
python -m pytest
pnpm --dir web test
cargo test --manifest-path rust/Cargo.toml -p fm27lab-core
```

## Repository layout

```text
fm27lab/    Python sidecar: domain, application, interfaces and adapters
web/        React 19 and Vite frontend
src-tauri/  Tauri 2 desktop shell
rust/       Rust core library
native/     Native adapter sources
src/        Source edition browser UI entry
scripts/    Build, packaging and source export scripts
docs/       Development, interface, verification and fidelity docs
```

## Version status

The current branch is `refactor/v2-modular`, the source version `2.0.0.dev0` (the frontend package version is `2.0.0-dev`), and the API version `fm27lab/v2`. No v2 installer has been released yet; remaining release items are tracked in [TODO](TODO.md). For stable versions, use the upstream Releases.

The new version starts with an empty SQLite database and does not migrate older experiment data; view or resume older jobs in the previous version. The supported platform is Windows x64, the adapter reference build is `27.0.1+2494687`, and the game engine and resources come from your local installation.

## Documentation

- [Design](DESIGN.md)
- [Build and development](docs/DEVELOPMENT.md)
- [Agent quick start](docs/AGENT_QUICKSTART.md)
- [Agent integration interface](docs/AGENT_INTEGRATION.md)
- [Agent verification](docs/AGENT_VERIFICATION.md)
- [Security boundaries](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Simulation fidelity](docs/SIMULATION_FIDELITY.md)
- [Contributing](CONTRIBUTING.md)

## License

Tool code is licensed under MIT. Save reading depends on `fmsave 0.12.4` and compressed data on `backports.zstd 1.8.0`. Third-party components and font licenses are listed in [Third-party notices](THIRD_PARTY_NOTICES.md).
