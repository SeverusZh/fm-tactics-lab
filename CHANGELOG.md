# Changelog

## Unreleased

- Add a local AI agent interface: /api/agent/v1 endpoints, fm27lab CLI, stdio MCP sidecar, file-backed drafts, endpoint discovery with token authentication, headless launcher mode, and cancellable save import and opponent scans.
- Improve the agent surface: compact JSON tool text, richer draft/job/results payloads, batch draft edits, draft clone, legal option lookup, inline scenario file paths, cross-job paired comparisons, queued free-run submissions with queue positions, and shorter job wait defaults.
- Unify run submission: the web UI and Agent interface share one start_run path; /api/run and /api/run-episodes keep the UI 409 behaviour while Agent submissions enter a real FIFO queue that executes one batch at a time in creation order; cancelling a queued run lands status cancelled immediately and resume uses the same serial gate.
- Add random away tactic pool support to the Agent layer: draft summaries and inline/draft/job/fmf sources preserve away_tactic_pool; one task draws each seed once so A/B variants face the same opponent tactic; results_summary reports per-entry draw counts, results_matches exposes the drawn tactic, CSV gains tactic_pool_entry_index and tactic_pool_entry_name, and results_compare returns comparable=false instead of pairing tasks whose draws differ.
- Fix the merged status contract: lab_status tolerates engine_compatibility with a string native profile, and MCP reloads endpoint.json and retries once after token rotation or an app restart; run submissions carry an idempotency key so the retry does not create duplicate jobs.
- Bump the server and agent contract version to 1109.3; extend the offline server queue tests, the pool mock and the Agent/MCP regression suite (210 tests).

## v1109.3 · 2026-11-09

- Allow random away tactic pools with experimental tactical execution.
- Isolate every execution match and verify native ability contribution, actual roster identity, CA, and manual component scores.
- Recheck execution receipts against the original drawn inputs when resuming.
- Preserve current squads and automatic CA/role ability calculation across pool expansion.
- Validation: 28 accepted native matches with three opponent presets, same-seed A/B, actual cancel/restart/resume, independent replays, CA and role-suitability changes, and the combined UI flow; zero unexpected failures. Automated checks: 72 passed, one Windows symlink-permission skip. These checks establish functional input handling, not tactical superiority.

## v1109.2 · 2026-11-09

- Follow the Windows display language in the interface and system tray, with Simplified Chinese and English support.
- Merge the weighted away tactic pool and same-league preset library from PR #2.
- Count one shared A/B opponent draw per seed and preserve replayed draws when resuming.
- Select active or upcoming complete league schedules first, with a 90-day limit for preseason and postseason tables.
- Integrate the v1109.1 save-header, named set-piece, split tactical-effectiveness and bounded large-save fixes.
- Retain separate disk budgets for save import, preparation and batch simulation, with the actual data path in errors.


## 未发布

- 新增真实AI战术批量生成：读取每队现任主教练、当前阵容和你自己的主教练，用本机原版引擎做 0 tick 对局准备并回读完整双阶段战术；每个对手生成对手主场/对手客场两套（列表显示为「球队主场战术/球队客场战术」）并直接替换第1/2套，支持进度条、并行生成与缓存增量补齐，可导出或导入客队战术池。
- 客队战术池统一属性核对：开启统一属性时，每名首发在战术位置的熟练度固定为满 20，其余属性统一为可配置面板值（默认 15），并在展开后核对。
- 重新设计存档战术导出：可从存档中任意已载入联赛导出对手战术，每位主教练按主/次偏好阵型各生成一套原装预设，文件按「俱乐部-教练-第x套战术」命名并平铺写入导出目录。
- 联赛与国家名称改为读取本机 FM27 游戏数据库（lang_db.dat），并按存档 ID 交叉校验；读取失败时回退到联赛编号。
- 客队战术池导入不再去重，支持重复加入同一套战术；池上限调整为 128 套。
- 重新设计「存档战术」与「客队战术池」页面：联赛选择、球队/教练/两套战术表格、导出与导入主流程，移除旧页面冗余控件。
- 存档战术页的联赛与国家名称跟随界面语言显示中文或英文（读取 FM27 游戏数据库的中文名称表）；同一联赛只列出一条，自动选择进行中或最近的赛程。
- 联赛教练偏好改为直接读取一线队教练分配，不再依赖仅对部分存档可用的球队表；一线队主教练空缺的球队明确标记为不可用。
- 新增存档战术页面：识别存档后按当前联赛浏览除玩家以外的教练偏好预设战术，可导出到本机文件夹或一键导入客队战术池。
- 客队战术池改为侧边栏独立页面，支持导入本机 FMF 或从存档页面导入联赛对手预设；底栏快速模式旁新增随机模式开关，按权重逐场抽取客队战术。
- 统一客队球员属性只统一能力属性，首发按抽中战术的对应位置获得最高位置熟练度，避免此前整队位置熟练度统一为 15 后明显变弱。
- 修复赛季结束后读取存档时无法识别当前联赛、导致存档战术页面提示教练偏好读取失败的问题。

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
