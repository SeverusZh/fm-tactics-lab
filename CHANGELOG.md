# Changelog

## Unreleased

- Add a local AI agent interface: /api/agent/v1 endpoints, fm27lab CLI, stdio MCP sidecar, file-backed drafts, endpoint discovery with token authentication, headless launcher mode, and cancellable save import and opponent scans.

## v1108.5 — 2026-11-08

- Import career saves, edit match squads and run home and away matches against selectable same-league opponents.
- Preview both tactical phases using presets matched to the head coach's saved preferences.
- Preserve position settings when swapping players, correct Chinese transition labels and add experiment management.
- Add optional manual tactical effectiveness settings for both sides.

## v1106 — 2026-11-06

- Add actual interface screenshots to both player guides.
- Serve `engine-settings.js` from the static route allowlist so engine diagnostics and manual path selection initialize correctly. The v1103.2 release is retained. New desktop builds display v1106 and self-test the engine settings endpoint.

## v1103.2 — Public release

- Publish FM Tactics Lab under MIT with Chinese and English player documentation.
- Release the original `FM27战术推演_v1103.2.exe`, unchanged.
- Publish the corresponding desktop application payload and native adapter sources.
- Include double-phase tactics, player input editing, set pieces, batch comparison, original match statistics and full/quick collection modes.
- Include graded engine compatibility and manual game-path selection.
- Keep career-save versus modules in later development versions.
- Add standalone source preparation, build and export scripts. Local initial inputs can be read from the verified release EXE.
