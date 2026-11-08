# FM Tactics Lab Agent 快速启动

状态：本机已安装并注册到 DSH
适用范围：Windows + WSL 的 DSH 环境

## 1. 已安装内容

运行时目录：

```text
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime
```

| 路径 | 内容 |
| --- | --- |
| engine | v1108.5 原生引擎工作区，含 FM27Simulator.exe 与 match.pkm |
| source | Agent 服务端、fm27lab 包、CLI、MCP sidecar 与 fmsave vendor |
| data | 实验、存档库、导出与 agent/endpoint.json |
| logs | 服务端 stdout 与 stderr 日志 |
| runtime-env.cmd | 路径、端口、游戏根目录与 Python 环境 |
| start-agent.cmd | 启动后台服务 |
| stop-agent.ps1 | 优雅停止服务 |
| fm27lab.cmd | CLI 入口 |
| fm27lab-mcp.cmd | MCP sidecar 入口，带自动启动 |

DSH 中已注册的 MCP 名称：fm27lab。注册命令为 Windows cmd.exe 调用 fm27lab-mcp.cmd。当前为 live，工具数 26。

## 2. 启动与停止

通常不需要手动启动。DSH 首次调用 fm27lab 工具时，fm27lab-mcp.cmd 会：

1. 检查 data/agent/endpoint.json 是否对应健康服务。
2. 如未运行，用 Windows 本地引擎与 Python 在 18770 端口后台启动服务。
3. 等待发现文件就绪，再启动 MCP sidecar。

手动启动：

```bat
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\start-agent.cmd
```

查看状态：

```bat
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd status --json
```

停止：

```powershell
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\stop-agent.ps1"
```

服务只监听 127.0.0.1:18770；端口变化时只需修改 start-agent.cmd。

## 3. 在 DSH 中使用

直接描述任务即可，例如：

- 先检查引擎状态，再创建默认草案，把客队心态调到 5，跑 10 场对比。
- 从 F:\fm\fm27\games 下的存档导入球队，选一个对手跑主客场 2 场。
- 把当前草案导出为 FMF。

推荐调用顺序：

```text
lab_status
draft_create / draft_edit / draft_validate
experiment_run 或 career_run
job_wait
results_summary / results_matches / results_csv
```

应用未启动时工具会返回 app_unavailable；再次调用会重试，或先运行 start-agent.cmd。

资源：fm27://manifest、fm27://catalog、fm27://status，以及 draft、job、save 模板。
Prompt：test_tactic_change、compare_baseline_vs_current、opponent_sweep。

## 4. 命令行

Windows 下直接运行：

```bat
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd status --json
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd draft create --from default --name test
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd draft edit <draft_id> --op mentality --team B --value 5
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd run --draft <draft_id> --seeds 1-10 --workers 2 --wait --json
%LOCALAPPDATA%\FM27TacticsDesktop\agent-runtime\fm27lab.cmd results summary <job_id> --json
```

WSL 下通过 cmd.exe 调用：

```bash
cmd.exe /c 'C:\<Windows 用户目录>\AppData\Local\FM27TacticsDesktop\agent-runtime\fm27lab.cmd status --json'
```

存档对战示例：

```bat
fm27lab.cmd career import --save "F:\fm\fm27\games\auto save (v03).fm" --wait
fm27lab.cmd career status --save-id <save_id>
fm27lab.cmd career team --save-id <save_id> --club <club_uid>
fm27lab.cmd draft create --from save --save-id <save_id> --club <club_uid> --tactic 0
fm27lab.cmd career opponents --save-id <save_id> --club <club_uid> --wait
fm27lab.cmd career preview --save-id <save_id> --club <club_uid> --key coach:587 --draft <draft_id>
fm27lab.cmd career run --save-id <save_id> --club <club_uid> --draft <draft_id> --opponents coach:587 --count 2 --first-seed 1 --workers 1 --wait
```

## 5. 数据与日志

- 实验结果：data\runs
- 存档缓存：data\save_library
- 导出文件：data\agent\exports
- 发现文件：data\agent\endpoint.json，token 每次启动轮换
- 服务日志：logs\server.out.log 与 logs\server.err.log

## 6. 引擎与游戏路径

游戏根目录写在 runtime-env.cmd 中，当前为：

```text
D:\Program Files (x86)\Steam\steamapps\common\Football Manager 27
```

移动游戏或换机器时修改该行并重启服务。引擎工作区必须位于 Windows 本地磁盘；不要把 engine 放到 WSL 的 UNC 路径，否则原生宿主读取 match.pkm 会退出 104。

## 7. 更新与卸载

更新 Agent 代码：

1. 停止服务。
2. 用仓库 src 覆盖 runtime\source，保留 source\vendor。
3. 如引擎变化，覆盖 runtime\engine。
4. 重新启动；DSH 注册无需变化。

卸载：

1. 在 DSH 的 MCP 设置中移除 fm27lab。
2. 运行 stop-agent.ps1。
3. 删除 agent-runtime 目录。

## 8. 排查

| 现象 | 处理 |
| --- | --- |
| app_unavailable | 运行 start-agent.cmd；检查 endpoint.json 与 logs |
| 401 unauthorized | 应用重启后 token 会轮换；重试或重启 MCP sidecar |
| 403 forbidden_host | 调用方 Host 不是 127.0.0.1 或 localhost |
| 409 engine_busy | 等待或取消当前任务后再提交 |
| 端口 18770 被占用 | 停止旧服务，或修改 start-agent.cmd 中的端口 |
| 原生会话退出 104 | 确认 engine 位于 Windows 本地路径，FM27 已安装且 Steam 已登录 |
| 存档读取失败 | 确认存档为 FM27 构建 27.0.0+2493426 可读；查看 save_library 日志 |

## 9. 已知限制

- 同一时刻只允许一个批次任务。
- 首期不提供定位球片段实验、实验执行力与原生 AI 生成对手。
- 仅本机 loopback，不支持远程访问。
- headless EXE 打包未验证；当前运行时直接启动 Python 服务端。