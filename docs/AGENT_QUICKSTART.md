# FM Tactics Lab Agent 快速启动

适用版本 2.0.0.dev0，API 版本 fm27lab/v2。本文只描述当前仓库实现：Tauri 2 桌面壳加 Python sidecar 进程（包名 fm27lab），CLI 与 MCP 通过回环 HTTP 和 endpoint.json 接入。v1 启动器时代做法已删除，不再有打包 EXE、--headless 启动、自动生成的 fm27lab.cmd 或 mcp.json、必填的 game_root。

## 1. 版本与当前边界

| 项 | 当前实现 | 代码位置 |
| --- | --- | --- |
| 版本号 | 2.0.0.dev0 | fm27lab/__init__.py:3 |
| API 版本 | fm27lab/v2 | fm27lab/__init__.py:4 |
| 运行形态 | Tauri 2 壳加 Python sidecar | src-tauri/tauri.conf.json、fm27lab/sidecar.py |
| 进程入口 | fm27lab serve、fm27lab-sidecar | fm27lab/cli.py:66、pyproject.toml |
| 发现文件 | data_dir/agent/endpoint.json | fm27lab/config.py:92-93 |
| 能力总数 | 51 个 Capability | fm27lab/registry.py:104 |
| MCP 工具 | 49 个 | fm27lab/interfaces/mcp/tools.py:613-620 |

当前开发构建的边界必须了解：

- 引擎按配置解析：注入 EnginePort 优先，其次 settings.engine_root 非空时装配惰性原生宿主，最后才用 MissingEngine 占位；未配置 engine_root 时 POST /api/experiments/start 返回 503 engine_unavailable，消息为“原生引擎未配置”（fm27lab/interfaces/http/app.py:102、126-149、fm27lab/adapters/engine_native/lazy.py:22-71）。engine_root 由 serve 的 --engine-root 或环境变量 FM27_ENGINE_ROOT 提供，配置后首次实验启动才构造宿主。
- 提交实验有两条引擎目录相关错误，均为 400 validation_failed：engine_root 未设置时报“引擎目录未配置，无法生成比赛配置”；engine_root 已设置但找不到 catalog.json 时报“未找到引擎目录文件，无法生成比赛配置”（fm27lab/application/experiment_material.py:30-31、214-226）。
- 所有访问只走本机回环地址，不支持远程连接。

## 2. 启动 sidecar

CLI 和 MCP 都不自动拉起 sidecar，它们只读取 endpoint.json 并连接已在运行的实例。sidecar 由桌面壳启动，或手工执行 serve 启动。

### 2.1 桌面应用

桌面壳启动时选择 sidecar 可执行文件并注入运行环境（src-tauri/src/lib.rs:49-82、218-245）：

- 发布构建使用 resource_dir()/sidecar/fm27lab-sidecar 或 fm27lab-sidecar.exe。
- 调试构建优先使用环境变量 FM27LAB_SIDECAR，其次用 FM27LAB_PYTHON 或 python.exe、python3 执行 -m fm27lab serve，工作目录为项目根。
- 注入 FM27LAB_DATA 为应用本地数据目录，FM27LAB_TOKEN 为随机令牌，FM27_ENGINE_ROOT 为外部环境变量或 data_dir/engine，FM27LAB_PORT 固定为 0，PYTHONUTF8 为 1，调试构建追加 FM27LAB_DEV=1。
- sidecar 的 stderr 写入 data_dir/logs/sidecar-<pid>.stderr.log；启动等待 30 秒，就绪判定来自 stdout 的 ready 行与 GET /api/health 的 200 响应（src-tauri/src/lib.rs:24-27、96-117、285-298）。
- 退出时发送 POST /api/shutdown 并等待 10 秒，超时后杀进程，最后删除 data_dir/agent/endpoint.json 与 .json.tmp（src-tauri/src/lib.rs:119-155、433-463）。

### 2.2 手工启动

在仓库根目录，使用虚拟环境中的解释器：

```bash
.venv/bin/python -m fm27lab serve --data-dir ./data --engine-root <引擎工作区> --port 18765
```

安装包后也可以直接使用控制台脚本 fm27lab serve。serve 的选项（fm27lab/cli.py:66-87）：

| 选项 | 说明 |
| --- | --- |
| --data-dir PATH | 数据目录；缺省读 FM27LAB_DATA 或平台默认路径 |
| --engine-root PATH | 引擎工作区；缺省读 FM27_ENGINE_ROOT，None 时不生成比赛配置 |
| --host TEXT | 回环主机，默认 127.0.0.1 |
| --port INT | 端口，0 表示由系统分配空闲端口 |
| --token TEXT | Bearer 令牌，省略时自动生成 |
| --dev / --no-dev | 是否放行 Vite 开发来源 http://localhost:1420 |

启动成功后 stdout 输出一行就绪事件，随后 endpoint.json 可被客户端读取（fm27lab/sidecar.py:69-95）：

```json
{"event":"ready","port":18765,"pid":12345}
```

### 2.3 环境变量与数据目录

fm27lab/config.py:69-85 读取以下环境变量：

| 变量 | 作用 |
| --- | --- |
| FM27LAB_DATA | 数据目录 |
| FM27_ENGINE_ROOT | 引擎工作区 |
| FM27LAB_TOKEN | Bearer 令牌 |
| FM27LAB_PORT | 端口 |
| FM27LAB_HOST | 回环主机 |
| FM27LAB_DEV | 值为 1 时视为开发模式，放行 Vite 来源 |

默认数据目录为 Windows 下的 %LOCALAPPDATA%\FM27TacticsDesktop，其他平台为 ~/.fm27lab（fm27lab/config.py:14-18）。Settings.create 会先展开并把数据目录解析为绝对路径，拒绝空值、字面量「.」以及等于当前工作目录的路径；同时要求令牌非空且为 ASCII、主机为回环地址、端口在 0 到 65535 之间（fm27lab/config.py:29-56）。桌面壳启动时数据目录以壳注入的 FM27LAB_DATA 为准，具体路径可读取 endpoint.json 的 data_dir 字段确认。

## 3. 发现文件

sidecar 绑定端口后写入 data_dir/agent/endpoint.json（fm27lab/config.py:92-93、fm27lab/sidecar.py:33-66）。字段共 9 个：

| 字段 | 含义 |
| --- | --- |
| schema | 发现文件结构版本，当前为 1 |
| api | API 版本，fm27lab/v2 |
| url | 回环根地址 http://127.0.0.1:<port> |
| port | 实际监听端口 |
| token | Bearer 令牌 |
| pid | sidecar 进程号 |
| data_dir | 数据目录绝对路径 |
| engine_root | 引擎工作区绝对路径，未配置时为 null |
| created_at | 本地时区 ISO 时间 |

示例：

```json
{
  "schema": 1,
  "api": "fm27lab/v2",
  "url": "http://127.0.0.1:18765",
  "port": 18765,
  "token": "<令牌；缺省生成为 64 位小写十六进制>",
  "pid": 12345,
  "data_dir": "/home/user/.fm27lab",
  "engine_root": null,
  "created_at": "2026-11-14T07:30:00+08:00"
}
```

写入规则：先写 .json.tmp 并设置 0600 权限，再用 os.replace 原子替换；Windows 上通过 icacls 移除继承并只授权当前用户；进程退出时删除发现文件（fm27lab/sidecar.py:33-66）。

客户端读取规则见 fm27lab/client.py:101-148：url 必须是 http 协议、主机为 127.0.0.1 或 localhost、不含用户信息、路径为根；token 必须非空且为 ASCII。错误码包括 endpoint_missing、endpoint_unreadable、endpoint_invalid、unreachable、http_error、unexpected_redirect、invalid_request、invalid_response。

不要期待自动生成 fm27lab.cmd 或 mcp.json：v2 启动链路不写这两个文件，src/fm27_agent_contract.py:195-220 的写入函数属于 legacy 服务器，桌面壳与 fm27lab 均不调用。

## 4. CLI

### 4.1 入口与全局选项

入口为控制台脚本 fm27lab 或 python -m fm27lab（fm27lab/__main__.py）。全局只有一个选项 --data-dir，且必须写在子命令之前（fm27lab/cli.py:47-57）。数据目录解析顺序为 --data-dir、FM27LAB_DATA、平台默认路径。

### 4.2 命令一览

| 命令组 | 子命令与主要选项 |
| --- | --- |
| pools | list --limit --offset；get ENTRY_ID；create --name --tactic --weight --roster --id；delete ENTRY_ID |
| drafts | list --limit --offset；get；create --name --scenario --source；update --name/--scenario/--source；delete；attributes --side --scope --operation --params --player-index；export-fmf --output；import-fmf --name --file --source；apply-roster --save-id --club-uid --side --scope；undo-roster |
| jobs | list --status --limit --offset；get；create --kind --name --config --workers --total；update --status/--completed/--summary/--name；cancel；delete；runs --limit --offset；summary --side；batch-action --action --ids；batch-delete --ids；export --output；pool-summary |
| saves | list --status --limit --offset；get；create --source-path --source-sha256 --status --stage --metadata；update；delete；import SAVE_ID --leagues --clubs --stage；import-file --source-path --replace；squad SAVE_ID --club-uid |
| artifacts | list --kind --job-id --limit --offset；get；content --output；create --kind --filename --file --job-id；delete |
| settings | list；get KEY；put KEY --value --note；delete KEY |
| concurrency | check --workers --cpu-count --available-memory-bytes --free-disk-bytes --allow-oversubscription |
| experiments | submit --draft-id --seed --workers --cpu-count --available-memory-bytes --free-disk-bytes --baseline-draft-id --name --allow-oversubscription；start；cancel JOB_ID；resume JOB_ID |
| catalog | show |
| results | compare --baseline --candidate --variant --side --reps |
| system | resources |
| 顶层 | version；serve；mcp |

分页默认值：pools 与 drafts 每页 128 条上限 128；jobs、saves、artifacts 每页 50 条上限 256；jobs runs 每页 50 条上限 200（fm27lab/cli.py:221-232）。

### 4.3 输出与退出码

- 成功时 stdout 输出紧凑 JSON（fm27lab/cli.py:151-152）；results compare 是唯一使用两空格缩进的命令（fm27lab/cli.py:931）。
- 下载类命令写文件后输出 {"path": "...", "bytes": 123}（fm27lab/cli.py:206-218）；删除类命令输出 {"deleted": true}（fm27lab/cli.py:178-196）。
- 失败时 stderr 输出“错误码: 消息”，退出码 1（fm27lab/cli.py:143-148）；参数或用法错误由 Typer 处理，退出码 2；成功退出码 0。

### 4.4 示例

以下命令都需要先设置相同的 --data-dir，或设置 FM27LAB_DATA。

```bash
.venv/bin/python -m fm27lab --data-dir ./data version
.venv/bin/python -m fm27lab --data-dir ./data drafts create --name demo --scenario @scenario.json
.venv/bin/python -m fm27lab --data-dir ./data drafts attributes <draft_id> --side home --scope starters --operation bulk --params '{"value":12}'
.venv/bin/python -m fm27lab --data-dir ./data experiments submit --draft-id <draft_id> --seed 101 --seed 102 --workers 2
.venv/bin/python -m fm27lab --data-dir ./data experiments start
.venv/bin/python -m fm27lab --data-dir ./data jobs runs <job_id> --limit 20
.venv/bin/python -m fm27lab --data-dir ./data jobs summary <job_id> --side 0
.venv/bin/python -m fm27lab --data-dir ./data results compare --baseline <job_a> --candidate <job_b> --reps 2000
.venv/bin/python -m fm27lab --data-dir ./data jobs export <job_id> --output runs.csv
```

version 输出为“2.0.0.dev0 fm27lab/v2”（fm27lab/cli.py:60-63）。drafts create 的场景必须是合法场景对象，teams 长度为 2，球员带唯一 source_uid 且包含门将，规范化细节见接入规格的数据模型章节（fm27lab/domain/scenario.py:95-102）。drafts attributes 的 --params 取值由操作决定：bulk 需要 value，position 需要 position 与 value，pair_feet 需要五个字段，undo 不接受参数（fm27lab/application/draft_attributes.py:18-40）。

## 5. MCP 接入

### 5.1 客户端配置

MCP 以 stdio 子进程方式运行 fm27lab mcp，不监听网络端口。启动时先读取 data_dir 的 endpoint.json，再探测 GET /api/health；失败时 stderr 输出“无法启动 MCP 服务：错误码: 消息”并以 1 退出（fm27lab/cli.py:90-140）。因此必须先有运行中的 sidecar。

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "python",
      "args": ["-m", "fm27lab", "mcp"],
      "env": {
        "FM27LAB_DATA": "<sidecar 使用的 data_dir>"
      }
    }
  }
}
```

### 5.2 协议与能力

协议版本固定为 2024-11-05，无版本协商分支（fm27lab/interfaces/mcp/protocol.py:8）。initialize 返回的 capabilities 只包含 tools、resources、prompts，各带 listChanged 为 false；serverInfo 的 name 为 fm27lab，version 取包版本（fm27lab/interfaces/mcp/protocol.py:215-225、fm27lab/cli.py:111、132-133）。支持的方法只有 initialize、tools/list、tools/call、resources/list、resources/read、prompts/list、prompts/get（fm27lab/interfaces/mcp/protocol.py:198-213）。

### 5.3 工具

共 49 个工具，按能力组列出（fm27lab/registry.py:27-39 定义 11 个能力组，其中 system 组没有 MCP 工具，故下列为 10 组；工具清单见 fm27lab/interfaces/mcp/tools.py:613-620）：

- pools_list、pools_get、pools_create、pools_delete
- drafts_list、drafts_get、drafts_create、drafts_update、drafts_delete、drafts_attributes、drafts_export_fmf、drafts_import_fmf、drafts_apply_roster、drafts_undo_roster
- jobs_list、jobs_get、jobs_create、jobs_update、jobs_cancel、jobs_delete、jobs_runs、jobs_batch_actions、jobs_batch_delete、jobs_export、jobs_pool_summary
- saves_list、saves_get、saves_create、saves_update、saves_delete、saves_import、saves_import_file、saves_squad
- artifacts_list、artifacts_get、artifacts_content、artifacts_create、artifacts_delete
- settings_list、settings_get、settings_put、settings_delete
- concurrency_check
- experiments_submit、experiments_start、experiments_cancel、experiments_resume
- catalog_snapshot
- results_compare

jobs_summary 与 system_resources 只有 HTTP 与 CLI 入口，没有对应的 MCP 工具（fm27lab/registry.py:242-248、415-421）。

工具成功结果的 content[0].text 是紧凑 JSON，structuredContent 为同一份数据，isError 为 false；失败时 isError 为 true，structuredContent.error.code 固定为 tool_error（fm27lab/interfaces/mcp/protocol.py:333-362）。

### 5.4 资源与提示词

静态资源 4 个，无资源模板（fm27lab/interfaces/mcp/resources.py）：fm27lab://drafts 与 fm27lab://pools 每页 128 条，fm27lab://jobs 与 fm27lab://saves 每页 256 条，读取结果为 JSON。

提示词 2 个（fm27lab/interfaces/mcp/prompts.py）：experiment-design 必填 draft_id 与 instruction，可选 baseline_draft_id 与 seeds；pool-review 必填 job_id，可选 focus。

### 5.5 长任务轮询

MCP 没有 notifications/progress、notifications/cancelled 或 logging 能力，工具调用不会推送进度（fm27lab/interfaces/mcp/protocol.py:198-225）。experiments start 在服务端同步执行整批实验，HTTP 客户端默认超时 30 秒（fm27lab/client.py:16、fm27lab/application/experiments.py:257-299），因此 start 调用可能先超时而服务端继续执行。用 jobs_get、jobs_runs、jobs_summary 轮询最终状态。

## 6. HTTP 客户端要点

- 鉴权：除 GET /api/health 与 GET /api/version 外，所有业务路由都要求 Authorization: Bearer <token>（fm27lab/interfaces/http/common.py:38-51、fm27lab/interfaces/http/routes/system.py:41-62）。FastAPI 自带的 /api/docs 与 /api/openapi.json 未加鉴权（fm27lab/interfaces/http/app.py:107-113）。
- 错误封套：{"error": {"code", "message", "details", "retriable", "retry_after_seconds"}}，retriable 在状态码大于等于 500 或等于 409 时为 true（fm27lab/interfaces/http/common.py:14-37）。
- 来源校验：Origin 不在白名单时返回 403 forbidden_origin，白名单为 tauri://localhost、http://tauri.localhost，开发模式追加 http://localhost:1420（fm27lab/interfaces/http/app.py:47-48、149-169）。服务端不做 Host 头校验。
- 幂等：写请求可带 Idempotency-Key，键非法返回 400 invalid_idempotency_key，同键不同载荷返回 409 idempotency_conflict，仅缓存 2xx 响应且回放不带额外标记头（fm27lab/interfaces/http/idempotency.py:17-24、fm27lab/application/idempotency.py:38-56）。
- 关闭：POST /api/shutdown 需要令牌，返回 202 与 {"status": "shutting_down"}（fm27lab/interfaces/http/routes/system.py:90-94）。
- 事件：GET /api/events 需要令牌，返回 text/event-stream；首帧为 ready，事件帧格式为 id、event、data 三行；Last-Event-ID 必须为非负整数，否则 400 invalid_last_event_id；每 15 秒发送 keepalive 注释（fm27lab/interfaces/http/routes/system.py:96-144、154-186）。
- 分页参数各端点上限不同：pools 与 drafts 为 1 到 128，jobs、saves、artifacts 为 1 到 256，jobs runs 为 1 到 200（fm27lab/interfaces/http/routes/pools.py:44-46、fm27lab/interfaces/http/routes/jobs.py、fm27lab/application/results.py:19）。

## 7. 典型工作流

1. 创建草案：drafts create 需要 name 与 scenario，scenario 可用 @文件传入；成功返回草案 ID、source、时间字段。
2. 调整属性：drafts attributes 按 side、scope、operation、params 修改，bulk 的 value 为 1 到 20 的显示值，内部按乘 5 存储（fm27lab/domain/attributes.py:165-183）。操作会写入属性快照，可用 undo 撤销（fm27lab/application/draft_attributes.py:23-40）。
3. 提交实验：experiments submit 的 seeds 不可重复，总数不超过 10000；未显式给出资源字段时 CLI 先调用 GET /api/system/resources 自动探测（fm27lab/cli.py:806-836、840-881）。
4. 启动执行：experiments start 调用 POST /api/experiments/start，服务端同步推进队首任务；未注入引擎且未配置 engine_root 时返回 503 engine_unavailable（fm27lab/interfaces/http/app.py:137-146、fm27lab/interfaces/http/routes/experiments.py:62-65），配置 engine_root 后首次启动按需构造原生宿主，引擎执行失败同样返回该码。
5. 查看结果：jobs runs 分页读取每场结果，jobs summary 给出胜平负、进球、xG 等指标与配对差值，results compare 做跨任务同种子配对比较，jobs pool-summary 展示客队战术池抽签（fm27lab/interfaces/http/routes/results.py、fm27lab/domain/results.py）。
6. 导出：jobs export 写 CSV，列固定为 job_id、sequence、variant、seed、score_home、score_away、verified、created_at、stats_json、events_json（fm27lab/application/results.py:19-30）。

客队战术池配置写在草案场景的 away_tactic_pool 字段内，profile 必须为 away-tactic-pool-v1，最多 128 套，权重 1 到 1000，轮战总场数不超过 10000（fm27lab/domain/pool.py:26-36、187-520）。

## 8. 数据目录

| 路径 | 内容 |
| --- | --- |
| fm27lab.db | SQLite 主库，保存草案、池条目、任务、结果、存档、产物、设置 |
| agent/endpoint.json | 发现文件，进程退出时删除 |
| agent/artifacts/<filename> | 登记的产物文件 |
| agent/experiments/<job_id>/ | 实验物化目录，含 provenance.json 与每场配置文件 |
| logs/sidecar-<pid>.stderr.log | sidecar 标准错误，由桌面壳写入 |
| exports/ | 目录会被创建，当前 fm27lab 没有写入该目录的代码 |

fm27lab.db 路径由 fm27lab/config.py:88-89 决定；agent、exports 等目录在 ensure_dirs 中创建（fm27lab/config.py:99-101）。草案存 SQLite 表，不写 agent/drafts 文件目录（fm27lab/adapters/storage_sqlite/repositories.py:241-266）。v1 文档中的 runs、save_library 目录不存在。

## 9. 排查

| 现象 | 原因与处理 |
| --- | --- |
| endpoint_missing | sidecar 未运行，或 CLI 的 data_dir 与 sidecar 不一致；确认 endpoint.json 存在 |
| 401 unauthorized | 令牌缺失或与 endpoint.json 不符；重启后令牌会轮换，客户端需重新读取发现文件 |
| 403 forbidden_origin | 请求 Origin 不在白名单；浏览器调试时使用开发来源或桌面壳 |
| 400 validation_failed 且消息为“引擎目录未配置，无法生成比赛配置” | engine_root 未设置 |
| 400 validation_failed 且消息为“未找到引擎目录文件，无法生成比赛配置” | engine_root 已设置但其中缺少 catalog.json |
| 503 engine_unavailable 且消息为原生引擎未配置 | sidecar 未配置 engine_root；用 serve --engine-root 或 FM27_ENGINE_ROOT 指定引擎工作区。引擎可执行文件缺失或启动失败也返回该码 |
| 503 database_unavailable | 数据库未就绪，查看 sidecar 日志 |
| 409 invalid_transition | 任务状态不允许该操作，例如对非 interrupted 任务执行 resume |
| 400 invalid_last_event_id | Last-Event-ID 必须为非负整数 |
| MCP 启动报“无法启动 MCP 服务” | 与 endpoint_missing 或 401 相同，先确保 sidecar 可用 |
| 命令长时间无响应后报超时 | 内部 HTTP 超时为 30 秒；用 jobs get 重新查询任务状态 |

## 10. 已知限制

- 本机 Linux 环境没有 FM27Simulator 可执行文件，端到端实验仍需 Windows 引擎宿主；配置 engine_root 后 sidecar 会惰性构造宿主，未配置或宿主不可用时 start 返回 503。
- 实验执行在请求线程内同步进行，没有后台调度线程（fm27lab/application/experiments.py:257-299）。
- MCP 无进度通知与取消通知，只能轮询任务状态。
- 仅支持本机回环访问，没有多用户或远程认证设计。
- 不提供 v1 的 /api/agent/v1/ 命名空间，v1 客户端与旧接入文档不适用。
- jobs summary 与 system resources 无 MCP 工具。
- exports/ 目录当前未使用。
