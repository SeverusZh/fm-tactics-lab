# FM Tactics Lab Agent 快速启动

本文面向“在本机运行 FM Tactics Lab，并让 AI Agent 通过 CLI 或 MCP 调用”的通用部署。适用于 Windows x64，FM27 已安装，且本机已准备好工具运行时或源码构建环境。

## 1. 能做什么

- 查询引擎兼容状态与批次限制。
- 从默认场景、FM27 存档、FMF 战术文件或已有实验创建草案。
- 语义化修改双阶段战术、角色、职责、定位球之外的战术层设置。
- 提交自由推演或存档对战批次，按种子运行并对比；自由模式支持随机客队战术池与 A/B 共享抽签。
- 等待、取消、续跑、分页读取结果与导出 CSV；排队中的批次可立即取消。
- 通过 MCP 暴露同一套能力给任意支持 stdio 的 Agent 客户端。

## 2. 前置条件

- Windows x64，Python 3.12；桌面版可使用自带运行时。
- 本机已安装可正常启动的 FM27；Steam 已登录。
- 已准备工具运行时：
  - 源码版：按 docs/DEVELOPMENT.md 准备 private 资产并构建 FM27Simulator.exe。
  - 打包版：使用包含 Agent 接入层的新构建；旧版发布包不包含该层。
- 引擎工作区必须位于 Windows 本地磁盘；不要把引擎资产放在 WSL 的 UNC 路径，原生宿主读取 match.pkm 会失败。

## 3. 启动应用

### 3.1 源码版

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts/prepare_private.py --release-exe "<官方发布 EXE>"
.venv\Scripts\python.exe scripts/build_native.py --reference-dll "<game-root>\fm_Data\Plugins\x86_64\game_plugin.dll"
.venv\Scripts\python.exe scripts/run.py --game-root "<game-root>"
```

源码版的数据目录默认为仓库下 data，引擎工作区默认为 private/engine。启动后服务监听 127.0.0.1 的可用端口。

### 3.2 打包版

启动桌面 EXE，按提示选择包含 fm_Data 与 shared 的游戏根目录。数据目录默认为 %LOCALAPPDATA%\FM27TacticsDesktop。

### 3.3 无头模式

打包版可加 --headless 参数，不显示托盘与浏览器，服务常驻直到收到 shutdown 或进程结束：

```bat
"<工具 EXE>" --headless --game-root "<game-root>" --data-dir "<dataDir>"
```

## 4. 发现文件与入口

服务启动后生成：

```text
<dataDir>\agent\endpoint.json
<dataDir>\agent\fm27lab.cmd
<dataDir>\agent\mcp.json
```

endpoint.json 包含：

- url：本机回环地址与端口
- token：本次启动的访问令牌，重启后轮换
- data_dir、engine_root、game_root
- 版本、能力位与批次限制

所有 Agent 接口只监听回环地址。除 health、status、desktop-presence 与静态页面外，其余接口需要 Bearer token 或同源 Cookie。

## 5. CLI

在 Windows 上运行生成的 fm27lab.cmd：

```bat
"%LOCALAPPDATA%\FM27TacticsDesktop\agent\fm27lab.cmd" status --json
"%LOCALAPPDATA%\FM27TacticsDesktop\agent\fm27lab.cmd" draft create --from default --name baseline
"%LOCALAPPDATA%\FM27TacticsDesktop\agent\fm27lab.cmd" draft edit <draft_id> --op mentality --team B --value 5
"%LOCALAPPDATA%\FM27TacticsDesktop\agent\fm27lab.cmd" run --draft <draft_id> --seeds 1-10 --workers 2 --wait --json
"%LOCALAPPDATA%\FM27TacticsDesktop\agent\fm27lab.cmd" results summary <job_id> --json
```

常用命令组：

| 命令 | 用途 |
| --- | --- |
| status | 清单、引擎与活动任务 |
| engine select | 设置游戏根并预检 |
| draft create/list/show/edit/validate/delete | 草案工作区 |
| run | 自由推演批次，可带 baseline 对照 |
| job list/get/wait/action/logs/export | 任务管理 |
| results summary/matches/match/csv | 结果读取；随机模式含每套客队战术抽中次数与逐场抽签列 |
| career import/status/team/opponents/preview/cancel/run | 存档对战 |
| fmf import/export、setpiece export | 战术文件往返 |

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 2 | 用法错误 |
| 3 | 应用未运行或发现文件缺失 |
| 4 | 鉴权失败 |
| 5 | 引擎不可用或不兼容 |
| 6 | 校验失败 |
| 7 | 引擎忙或状态冲突 |
| 8 | 资源不存在 |
| 9 | 任务失败、取消或中断 |
| 10 | 内部错误 |

## 6. MCP 接入

服务端生成 <dataDir>\agent\mcp.json。把其中配置复制到支持 stdio 的 MCP 客户端，或手动配置：

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "<dataDir>\\agent\\fm27lab.cmd",
      "args": ["mcp"]
    }
  }
}
```

说明：

- 命令必须是 Windows 本机绝对路径；fm27lab.cmd 会使用应用所在运行时启动 sidecar。
- 先启动应用，再启动 MCP 客户端；应用未运行时工具返回 app_unavailable。
- 客户端与服务必须能访问同一个 127.0.0.1 回环实例。跨 WSL 或跨机器时，需要自行提供端口转发或 Windows 侧启动包装。
- 也可直接使用 Python 入口：

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "<python.exe>",
      "args": ["-m", "fm27_agent", "mcp"],
      "env": {"FM27LAB_DATA": "<dataDir>"}
    }
  }
}
```

能力面：

- 28 个工具：状态、引擎、草案、存档、运行、任务、结果与战术文件。
- 3 个静态资源与 5 个资源模板：manifest、catalog、status、draft、job、save。
- 3 个 prompt：单变量战术实验、基线对比、多对手扫描。
- 支持进度通知、取消与结构化错误。

## 7. 典型工作流

自由模式对比：

```text
lab_status
draft_create source=default name=baseline
draft_create source=default name=changed
draft_edit changed op=team_instruction ...
draft_validate changed
experiment_run draft_id=changed baseline_draft_id=baseline seeds={start:101,count:10} workers=2 event_details=false
job_wait
results_summary
```

随机客队战术池对比：

```text
draft_create source=inline scenario_path="<含 away_tactic_pool 的场景文件>"
draft_validate
experiment_run draft_id=<池草案> baseline_draft_id=<池草案> seeds={start:101,count:20} event_details=false
job_wait
results_summary
```

同一任务的 A/B 共享一次抽签；summary 的 tactic_pool.draws 给出每套客队战术的抽中次数。跨任务 results_compare 会核对抽签，抽中不同战术时返回 comparable=false。

存档对战：

```text
career_import save_path="<存档路径>" wait=true
career_status
career_team save_id club_uid
draft_create source=save save_id club_uid tactic_index
draft_validate
career_opponents save_id club_uid wait=true
career_preview save_id club_uid key draft_id
career_run save_id club_uid draft_id opponents=[key] count=2 first_seed=1 workers=1
job_wait
results_summary
```

## 8. 数据、日志与安全

- 提交：自由模式与多候选批次进入同一 FIFO 队列，按创建顺序串行执行；UI 路径忙时返回 409，Agent 路径返回 queued 与 queue_position。
- 实验：<dataDir>\runs
- 存档缓存：<dataDir>\save_library
- 导出：<dataDir>\agent\exports
- 日志：应用日志目录与 <dataDir>\logs
- endpoint.json 含 token，应保留在用户目录；服务重启后 token 轮换。
- 服务只监听回环地址；不要将端口转发到公网。
- 存档导入为只读；原始 .fm 不会被修改。

## 9. 排查

| 现象 | 处理 |
| --- | --- |
| app_unavailable | 确认应用已启动、endpoint.json 存在，且 FM27LAB_DATA 指向正确目录 |
| 401 unauthorized | 应用重启后 token 已轮换；MCP 会自动重读 endpoint.json 并重试一次，直接调用 HTTP 时需手动重读 |
| 403 forbidden_host | 只能用 127.0.0.1 或 localhost 访问 |
| 409 engine_busy | 控制面操作与活动任务冲突；UI 的自由模式提交在忙时返回 409，Agent 提交会排队并返回 queue_position，等待或取消当前批次 |
| 引擎不可用或不兼容 | 在引擎设置中选择包含 fm_Data 与 shared 的游戏根目录 |
| 原生会话退出 104 | 确认引擎资产位于 Windows 本地路径，游戏资源完整 |
| 存档读取失败 | 确认存档为受支持的 FM27 构建；查看 save_library 日志 |

## 10. 已知限制

- 同一时刻只允许一个批次任务，按创建顺序串行执行。
- 随机客队战术池只支持自由推演；定位球片段与存档对战不支持。
- 定位球片段实验、实验执行力与原生 AI 生成对手只作为场景字段提交，暂无独立 MCP 工具。
- 仅本机回环访问。
- 不同 FM27 构建需要匹配的适配器；升级后重新执行兼容预检。