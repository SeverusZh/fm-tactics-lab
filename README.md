# FM 战术实验室 · FM Tactics Lab

> **本仓库由 SeverusZh 独立维护。** 这是 [lqf0624/fm-tactics-lab](https://github.com/lqf0624/fm-tactics-lab) 的 fork。我会按自己的节奏重构与发布；视情况向上游提交功能 PR，但不保证跟进上游更新。上游版本与发布包仍由上游维护者维护。

**简体中文** | [English](README.en.md)

**用原版比赛引擎，在本机批量测试你的战术。**

FM Tactics Lab v2 是 Tauri 2 桌面应用加 Python sidecar：桌面壳启动本地 sidecar，React 19 前端通过回环 HTTP 调用它，sidecar 驱动本地安装的 FM27 引擎批量运行完整比赛。可以管理 23 人名单、双阶段战术与球员属性，用客队战术池或同种子 A/B 比较不同设置，结果写入本地 SQLite。同一套服务还提供 CLI 与 MCP 两个自动化入口。

它适合解决这些问题：

- 同一批球员，哪套阵型更合适？
- 调整逼抢、防线或角色后，攻防表现怎样变化？
- 优势能否在多组种子、不同对手和主客场下保持？

## 架构

```text
桌面壳 Tauri 2 + React 19 ─┐
CLI                       ─┼── 回环 HTTP + Bearer token ──> Python sidecar (fm27lab)
MCP 客户端                ─┘                                      │
                                                                  ├─ SQLite 结果库
                                                                  └─ 原生引擎工作区
```

- sidecar 只监听回环地址，启动后把 url、port、token、pid、data_dir 与 engine_root 写入 `<data_dir>/agent/endpoint.json`，退出时删除；业务 `/api` 请求除 `/api/health` 与 `/api/version` 外都需要 Bearer token，`/api/docs` 与 `/api/openapi.json` 为公开文档路由。
- 引擎按需构造：没有可用的 `catalog.json` 时运行时目录返回 `available=false`，提交实验返回 `400 validation_failed`；引擎执行抛错时 `POST /api/experiments/start` 返回 `503 engine_unavailable`。引擎工作区需包含 `fm27_native/FM27Simulator.exe` 与 `catalog.json`。
- 实验链路：草案与可选基线草案先物化到 `<data_dir>/agent/experiments/<job_id>/`，再由原生引擎线程池并行执行，结果写入 SQLite。场次为种子数乘变体数，上限 10000 场、10000 个种子。

## 已实现能力

- 领域模型：双阶段战术（有球与无球各 11 人）、23 人名单、69 项球员属性（含 15 项位置属性）、客队战术池（随机或轮战，统一属性或真实名单）。
- 实验执行：同种子 A/B 对照；并行 1–256 路；提交前做资源预检，可用内存低于 2 GiB 或磁盘不足时默认拒绝，可显式覆盖；每个任务的结果包含 14 项指标。
- 结果分析：逐场记录、CSV 导出、按主队视角聚合指标；任务对比支持 1–32 个候选、1–20000 次重抽样，输出配对差值与 bootstrap 置信区间。
- 接口：52 个能力（11 组）；OpenAPI 列出 56 个操作；CLI 有 55 个叶子命令；MCP 提供 49 个工具、4 个只读资源与 2 个提示词。
- 桌面：战术板、球员属性、存档战术库、实验、实验结果、任务管理、设置共 7 个页面。底部运行栏尚未接入提交，实验从「实验」页提交。

## 快速开始

### 环境要求

- 桌面构建与运行：Windows x64，Python 3.12 x64、Node 22+、pnpm 11、Rust stable、MSVC C++17 与 Windows SDK、WebView2。
- Python、前端与 Rust core 测试可以在 Linux 运行。
- 本地安装 FM27，适配参考构建 `27.0.1+2494687`。
- 引擎工作区包含 `fm27_native/FM27Simulator.exe` 与 `catalog.json`，后者可以位于工作区根或 `fm27_native/` 下。

### 安装依赖

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pnpm --dir web install
npm install --global @tauri-apps/cli@^2
```

### 启动 sidecar

```powershell
python -m fm27lab serve --data-dir data --engine-root <引擎工作区> --dev
```

sidecar 监听回环地址，端口用 `--port` 指定；下文示例使用 18765。Windows 上默认数据目录为 `%LOCALAPPDATA%\FM27TacticsDesktop`，也可以用 `--data-dir` 或 `FM27LAB_DATA` 指定。

### 桌面开发壳

```powershell
$env:FM27LAB_PYTHON="$PWD\.venv\Scripts\python.exe"
$env:FM27_ENGINE_ROOT="<引擎工作区绝对路径>"
tauri dev
```

- 在仓库根运行；Tauri 自动定位 `src-tauri`。
- 调试构建由壳启动 `python -m fm27lab serve`；未设置 `FM27LAB_PYTHON` 时使用 PATH 中的 python。
- 壳使用应用本地数据目录，不是仓库 `data/`；设置 `FM27LAB_SIDECAR` 可以让壳启动已有的 sidecar 可执行文件。

### 浏览器前端

```powershell
python -m fm27lab serve --data-dir data --engine-root <引擎工作区> --dev --port 18765
$env:VITE_API_URL="http://127.0.0.1:18765"
$env:VITE_API_TOKEN=(Get-Content data\agent\endpoint.json | ConvertFrom-Json).token
pnpm --dir web dev
```

Vite 监听 1420 端口。浏览器没有 Tauri 外壳，开发模式下用 `VITE_API_URL` 与 `VITE_API_TOKEN` 连接 sidecar。

### MCP 接入

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "python",
      "args": ["-m", "fm27lab", "mcp"],
      "env": { "FM27LAB_DATA": "<sidecar data_dir 的绝对路径>" }
    }
  }
}
```

- 先启动 sidecar；MCP 子命令启动前会检查 `/api/health`。
- `FM27LAB_DATA` 必须与 sidecar 的 `--data-dir` 一致。
- 全局 `--data-dir` 位于子命令之前，例如 `python -m fm27lab --data-dir data mcp`。

### 打包桌面安装包

```powershell
python scripts/build_sidecar.py
tauri build --bundles nsis
```

`tauri build` 会先执行 `pnpm --dir web build` 与 `scripts/build_sidecar.py`，安装包输出到 `src-tauri/target/release/bundle/nsis/`。

### 源码版浏览器界面

仅支持 Windows x64，需要 CPython 3.12 与 MSVC。先按 [构建文档](docs/DEVELOPMENT.md) 的 Source edition 一节准备 private 资产并编译原生适配器。

```powershell
.venv\Scripts\python.exe scripts/run.py --game-root "D:\Games\Football Manager 27"
```

启动后打印回环地址，按 Ctrl+C 停止。

### 测试

```powershell
python -m pytest
pnpm --dir web test
cargo test --manifest-path rust/Cargo.toml -p fm27lab-core
```

## 目录结构

```text
fm27lab/    Python sidecar：领域、应用、接口与适配器
web/        React 19 与 Vite 前端
src-tauri/  Tauri 2 桌面壳
rust/       Rust core 库
native/     原生适配器源码
src/        源码版浏览器界面入口
scripts/    构建、打包与源码导出脚本
docs/       开发、接口、验证与一致性文档
```

## 版本状态

当前分支为 `refactor/v2-modular`，源码版本 `2.0.0.dev0`（前端包版本 `2.0.0-dev`），接口版本 `fm27lab/v2`。v2 安装包尚未发布，发布前收尾项见 [TODO](TODO.md)；稳定版本请使用上游 Releases。

新版本从空 SQLite 数据库开始，不迁移旧实验数据；旧任务请在上一版本中查看或续跑。运行平台为 Windows x64，适配参考构建 `27.0.1+2494687`，游戏引擎与资源由本地安装提供。

## 文档

- [设计说明](DESIGN.md)
- [构建与开发](docs/DEVELOPMENT.md)
- [Agent 快速上手](docs/AGENT_QUICKSTART.md)
- [Agent 集成接口](docs/AGENT_INTEGRATION.md)
- [Agent 验证流程](docs/AGENT_VERIFICATION.md)
- [安全边界](docs/SECURITY.md)
- [故障诊断](docs/TROUBLESHOOTING.md)
- [一致性说明](docs/SIMULATION_FIDELITY.md)
- [贡献说明](CONTRIBUTING.md)

## 许可

工具代码采用 MIT 许可证。存档读取依赖 `fmsave 0.12.4`，压缩数据依赖 `backports.zstd 1.8.0`。第三方组件与字体许可见 [第三方说明](THIRD_PARTY_NOTICES.md)。
