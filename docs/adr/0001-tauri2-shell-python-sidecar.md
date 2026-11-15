# ADR-0001 Tauri 2 桌面壳与 Python sidecar

- 状态：已接受
- 日期：2026-11-12
- 决策者：仓库维护者

## 背景

现有应用由 C# Launcher 启动 Python HTTP 服务，再打开 Edge/Chrome 应用窗口。技术栈陈旧，桌面生命周期、进程监督、文件对话框和安全握手分散在 C# 与 Python 之间。仓库维护者选定 Tauri 2 + Rust + TypeScript + Python sidecar。

## 决策

- Tauri 2 + Rust 负责窗口、单实例、文件对话框、sidecar 监督与系统集成；托盘与自动更新在 Phase 4 接入。
- React 19 + TypeScript + Vite 运行在 WebView2 中，负责全部界面。
- Python 3.12 sidecar 是领域、引擎编排、SQLite、CLI 与 MCP 的唯一所有者。
- Rust 不直接读写 SQLite，不持有足球领域逻辑，也不代理业务 API。
- React 只通过带 Bearer token 的 loopback HTTP 直接访问 sidecar。

## 接入契约

- Rust 生成 32 字节随机 token，通过 `FM27LAB_TOKEN` 环境变量传给 sidecar。
- sidecar 绑定 `127.0.0.1:0`，启动完成后向 stdout 输出 `{"event":"ready","port":N}`，并原子写入 `<data>/agent/endpoint.json`，权限收紧到当前用户。
- Rust 读取 ready 行并轮询 `GET /api/health`；失败或进程退出时按指数退避重启，最多 3 次。
- React 通过 Tauri command `get_connection` 获取 `{url, token, api}`；`api` 为 `fm27lab/v2`；token 不进入 localStorage、日志或 URL。
- 生产模式 CORS 只允许 `tauri://localhost` 与 `http://tauri.localhost`；开发模式额外允许 `http://localhost:1420`；不使用 cookie。
- `/api/events` 使用 fetch 流式 SSE，携带 Authorization 与 Last-Event-ID；不使用 EventSource 或 URL token；CORS preflight 允许这两个请求头。
- 无桌面模式由 `fm27lab serve` 自行生成 token 并写 endpoint.json；CLI/MCP 读取 endpoint，`--launch` 可启动 sidecar。
- 正常退出调用 `POST /api/shutdown`，等待 10 秒后终止；sidecar 删除 endpoint.json。
- 启动后轮询 `/api/health`；失败或退出时按 500/1000/2000ms 退避重启，最多 3 次；每次重启清空旧连接并发送 Tauri event。
- 安装包通过 `bundle.resources` 将 PyInstaller onedir sidecar 复制到 `resource/sidecar/`；缺少 sidecar 时构建失败。
- CLI 与 MCP 读取 endpoint.json，用同一 token 访问 loopback；MCP stdio 不暴露 HTTP 鉴权细节。

## 后果

- 最终用户不需要 Node、Rust 或 Python；安装包包含 sidecar 与 WebView2 依赖。
- 开发与 CI 需要 Rust、Node/pnpm 和 Python 3.12 工具链。
- Windows 构建与真机验证成为发布门槛；Linux 只能验证 Python、前端与 Rust 核心逻辑。
- token 生命周期、sidecar 崩溃恢复与端口写入必须被测试覆盖。

## 备选

- 继续 C# Launcher + Python HTTP：被维护者否决。
- Electron：运行时更重，且仍需 Python sidecar。
- Rust 代理全部 API：会形成第二个 API owner，增加契约漂移。
- 纯 Rust 重写：需要重写 fmsave 与原生编排，风险与周期不可接受。
