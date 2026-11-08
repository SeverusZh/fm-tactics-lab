# AI Agent 接入规格

状态：设计草案 v1，待评审
适用范围：本机 Windows 部署；MCP 为主、CLI 为辅；首期核心能力
依据：v1108.5 源码静态分析；控制面与推演内核的逐行证据保存在本机 .team 目录，不随仓库分发

## 决策基线

| 决策 | 结论 |
| --- | --- |
| 形态 | MCP 为主、CLI 为辅，共用客户端库 |
| 改造 | 允许服务端增量改造 |
| 部署 | 仅本机 Windows |
| 范围 | 首期自由推演与存档对战核心 |
| 并发 | 单任务，忙时报错 |
| 草案 | draftId 与文件化草案 |

## 1. 目标与非目标

目标：

- 让 AI Agent 发现本机应用、校验引擎、创建草案、提交批次、等待进度、读取结果、导出战术文件。
- 契约可版本化、可 schema 化、可测试；CLI 与 MCP 行为一致。
- 保持现有 Web UI、原生兼容门禁与完赛校验不变。

非目标：

- 远程或局域网访问；默认仅本机 loopback。
- 多任务队列与多租户并发；首期单任务，忙时报错。
- 定位球片段实验、实验执行力、原生 AI 生成对手；后续版本。
- 绕过原生兼容检查、DLL 指纹门禁或完赛校验。
- 游戏资源提取、再分发或替代原生引擎。
- 比赛中实时指挥。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| App | 桌面应用进程，含 Launcher、Python 控制面与原生宿主 |
| Engine workspace | FM27_ENGINE_ROOT，含 fm27_native、默认编辑快照与 match.pkm |
| Game root | 本机 FM27 安装目录 |
| Scenario | schema 3 为权威，schema 4 为双阶段视图，含双方球队、球员、战术与定位球 |
| Draft | Agent 侧文件化场景草案，带 id 与来源 |
| Job | 一次批次实验 |
| Run | 批次内单场，含比分、统计、事件与校验信息 |
| Agent layer | src/fm27_agent 客户端库、fm27lab CLI、fm27lab-mcp sidecar |

## 3. 部署与生命周期

### 3.1 拓扑

```text
Agent client  ──stdio──  fm27lab-mcp sidecar ──HTTP loopback──  App
     │                        │                                  ├─ Python 控制面
     └──shell──  fm27lab CLI ─┘                                  └─ FM27Simulator.exe
```

- App 与 sidecar 运行在同一台 Windows 机器；CLI 同机运行。
- sidecar 与 CLI 都不直接调用原生宿主，只调用 Agent 命名空间 HTTP 接口。
- App 未运行时，sidecar 可选自动拉起 headless 实例；默认关闭自动拉起。

### 3.2 发现文件

路径：%FM27_DESKTOP_DATA%/agent/endpoint.json
写入时机：Python 服务启动完成后原子写入；退出时删除。
权限：当前用户可读写；建议启动时用 icacls 收紧到当前用户。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| schema | int | 文件格式版本，首期 1 |
| api | string | fm27lab/v1 |
| url | string | http://127.0.0.1:<port> |
| token | string | 32 字节随机数的 64 位十六进制，每次启动轮换 |
| pid | int | Python 服务进程号 |
| data_dir | string | 数据根目录 |
| engine_root | string | 引擎工作区 |
| game_root | string | 游戏安装目录，可为空 |
| created_at | string | ISO 8601 本地时间 |
| versions | object | server、adapter、engine_build、scenario_schema、batch_schema |
| capabilities | array | free_run、career_save、comparison、fmf、repair、resume、cancel、idempotency |
| limits | object | 与 manifest 中 limits 相同 |

### 3.3 无头模式与关闭

Launcher 新增参数：

| 参数 | 行为 |
| --- | --- |
| --headless | 不显示托盘、不打开浏览器，服务持续运行直到 shutdown 或进程结束 |
| --port N | 固定端口，默认沿用 18765，被占用时仍回退临时端口 |
| --data-dir PATH | 数据目录，默认 %LOCALAPPDATA%/FM27TacticsDesktop |
| --game-root PATH | 游戏根目录，可省略，之后通过 engine select 设置 |

关闭流程：

- 新增 POST /api/agent/v1/shutdown，要求 token。
- 收到请求后取消活动任务，等待原生会话清理，最长 15 秒，然后退出。
- 响应 202 后进程退出；sidecar 若自动拉起过实例则一并停止。

### 3.4 打包与启动脚本

新增 Python 包：

```text
src/fm27_agent/__init__.py
src/fm27_agent/client.py       HTTP 客户端、发现、鉴权、错误映射
src/fm27_agent/drafts.py       草案存储与编辑
src/fm27_agent/schemas.py      MCP 工具与资源 schema
src/fm27_agent/cli.py          fm27lab 命令
src/fm27_agent/mcp.py          stdio MCP sidecar
src/fm27_agent/__main__.py     python -m fm27_agent
```

App 启动时生成稳定入口，避免 release 哈希路径变化：

```text
<dataDir>/agent/fm27lab.cmd    set PYTHONPATH=<release>/source，调用 <release>/python/python.exe -m fm27_agent
fm27lab mcp                    以 stdio 启动 MCP sidecar
<dataDir>/agent/mcp.json       MCP 客户端配置片段
```

源码版由 scripts/run.py 在 build/source 与 data/agent 下生成同样的入口。

## 4. HTTP 契约

### 4.1 命名空间与兼容

- 新增 Agent 命名空间 /api/agent/v1/，现有 /api/ 端点保持不变。
- 新命名空间返回结构化错误、分页与幂等语义；旧端点继续服务 Web UI。
- 旧端点与新端点共享内部实现与状态，不复制任务模型。

### 4.2 鉴权与 Host

所有请求先校验 Host，再判定鉴权：

- Host 只允许 127.0.0.1:<port>、localhost:<port>、[::1]:<port>，否则 403 forbidden_host。
- 鉴权方式二选一：Authorization: Bearer <token>，或 Cookie fm27_session=<token>。
- Cookie 在 GET / 返回页面时设置，HttpOnly、SameSite=Strict、Path=/；Web UI 无需改动。
- 仅以下路径免鉴权：GET /、静态资源白名单、GET /api/agent/v1/health、GET /api/status、GET /api/desktop-presence。
- 保留现有 Origin 同源检查，作为纵深防御。
- 不启用 CORS；不提供跨域预检。

### 4.3 响应与错误

成功：HTTP 2xx，JSON body 为数据本身。
失败：

```json
{
  "error": {
    "code": "engine_busy",
    "message": "已有比赛运行中",
    "details": {"active_job": "ab12cd34ef56"},
    "retriable": true,
    "retry_after_seconds": 30
  }
}
```

| 错误码 | HTTP | 可重试 | 说明 |
| --- | --- | --- | --- |
| unauthorized | 401 | 否 | 缺少或错误 token |
| forbidden_host | 403 | 否 | Host 不在白名单 |
| forbidden_origin | 403 | 否 | Origin 与 Host 不符 |
| unknown_endpoint | 404 | 否 | 路径不存在 |
| not_found | 404 | 否 | 资源不存在 |
| validation_failed | 400 | 否 | 参数或场景校验失败，details 带 field 或 side/slot |
| engine_unavailable | 409 | 否 | 引擎资源缺失或不可用 |
| engine_incompatible | 409 | 否 | 兼容检查失败 |
| engine_busy | 409 | 是 | 已有任务运行，details 带 active_job |
| conflict | 409 | 否 | 状态不允许，如运行中删除 |
| idempotency_conflict | 409 | 否 | 同一幂等键载荷不同 |
| storage_insufficient | 507 | 是 | 磁盘空间不足 |
| unsupported | 501 | 否 | 首期不支持的能力 |
| internal_error | 500 | 是 | 未预期异常 |

### 4.4 分页

- 列表接口统一支持 limit 与 offset。
- limit 默认 50，范围 1 到 200；offset 大于等于 0。
- 响应统一为：

```json
{"items": [], "total": 0, "limit": 50, "offset": 0, "next_offset": null}
```

- 通用列表字段名为 items；任务列表用 jobs，任务详情中的 runs 分页用 runs，字段含义相同。
- run 分页按 sequence 升序，保证追加期间的偏移稳定。
- 任务详情带 progress 参数时走增量模式，返回 runs_delta；与 runs_offset 同时出现时以增量模式为准。

### 4.5 幂等

- 请求头 Idempotency-Key，长度 8 到 128，字符限可见 ASCII。
- 适用端点：runs、career/import、career/run、resume。
- 同键同载荷返回首次响应，并带响应头 Idempotency-Replayed: true。
- 同键不同载荷返回 409 idempotency_conflict。
- 键保存在内存，有效期 24 小时；App 重启后清空。

### 4.6 端点总表

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| GET | /api/agent/v1/manifest | 无 | manifest |
| GET | /api/agent/v1/status | 无 | 引擎兼容、活动任务、存档活动状态 |
| GET | /api/agent/v1/health | 无 | ok、pid、server_version；免鉴权 |
| GET | /api/agent/v1/catalog | 无 | 领域枚举与配置 |
| GET | /api/agent/v1/defaults | 无 | 默认场景 schema 4 |
| GET | /api/agent/v1/schemas | 无 | JSON Schema 包 |
| POST | /api/agent/v1/shutdown | 无 | 202 accepted |
| GET | /api/agent/v1/jobs | limit、offset、status | 任务分页 |
| GET | /api/agent/v1/jobs/{id} | runs_offset、runs_limit、variant、progress | 任务详情与 runs 分页 |
| GET | /api/agent/v1/jobs/{id}/export | 无 | summary、scenarios、provenance |
| POST | /api/agent/v1/jobs/{id}/cancel | 无 | accepted |
| POST | /api/agent/v1/jobs/{id}/resume | workers | 202 id |
| POST | /api/agent/v1/jobs/{id}/rename | name | id、name |
| POST | /api/agent/v1/jobs/{id}/delete | 无 | id |
| POST | /api/agent/v1/runs | scenario、reference、seeds、workers、event_details、name | 202 id、total |
| POST | /api/agent/v1/engine/select | game_root | 引擎兼容状态 |
| POST | /api/agent/v1/validate | scenario | scenario、records |
| POST | /api/agent/v1/repair | scenario | scenario、changes |
| POST | /api/agent/v1/phase-plan | scenario | schema 4 |
| GET | /api/agent/v1/jobs/{id}/logs/{name} | 无 | 原始 JSONL，供诊断 |
| POST | /api/agent/v1/fmf/import | side、scenario、file_base64、setpiece_target | scenario、report |
| POST | /api/agent/v1/fmf/export | side、scenario、name | filename、path、sha256、report |
| POST | /api/agent/v1/setpiece/export | side、scenario、type、variant | filename、path、sha256、report |
| POST | /api/agent/v1/career/import | path | 202 id、reused |
| GET | /api/agent/v1/career/status | id | 进度与元数据 |
| POST | /api/agent/v1/career/import/cancel | id | accepted |
| POST | /api/agent/v1/career/team | save_id、club_uid | 球员、战术、选择 |
| POST | /api/agent/v1/career/load | save_id、club_uid、tactic_index、lineup、bench、scenario | scenario、source |
| POST | /api/agent/v1/career/selection | scenario、lineup、bench | scenario |
| POST | /api/agent/v1/career/opponents | save_id、club_uid | reading、complete、error |
| POST | /api/agent/v1/career/opponents/cancel | save_id、club_uid | accepted |
| POST | /api/agent/v1/career/preview | save_id、club_uid、key、scenario | team、source |
| POST | /api/agent/v1/career/run | save_id、club_uid、opponents、count、first_seed、scenario、reference、workers、event_details、name | 202 id、total |

### 4.7 清单与 Schema

manifest 示例：

```json
{
  "api": "fm27lab/v1",
  "server_version": "1108.5",
  "adapter_version": "27.0.0+2493426",
  "engine_build": null,
  "scenario_schema": 3,
  "scenario_view_schema": 4,
  "batch_schema": 1,
  "capabilities": ["free_run", "career_save", "comparison", "fmf", "repair", "resume", "cancel", "idempotency"],
  "limits": {
    "max_seeds": 10000,
    "max_workers": 4,
    "max_opponents": 40,
    "max_career_count": 10000,
    "max_body_bytes": 1500000,
    "max_import_bytes": 6000000,
    "max_draft_bytes": 5242880
  },
  "schemas": "/api/agent/v1/schemas"
}
```

Schema 包包含：

- scenario_v3、scenario_v4、job、run、metrics、save_progress、catalog、manifest。
- 由服务端维护，字段名与校验规则同源；MCP 工具 inputSchema 从同一份定义生成。

### 4.8 复用映射

| Agent 端点 | 复用现有实现 |
| --- | --- |
| runs | /api/run 的校验、任务创建与 execute |
| career/import 与 career/status | SaveLibrary.start 与 status |
| career/team、load、selection、preview | SaveLibrary.club、load_team、select_squad、inspect_opponents、opponent_team |
| career/opponents | SaveLibrary.begin_opponents |
| career/run | create_save_job |
| jobs 查询与操作 | JOBS、persist、resume_job、cancel |
| validate、repair、phase-plan | validate_scenario、repair_saved_scenario、phase_inputs.pack |
| fmf/import、fmf/export、setpiece/export | import_fmf、export_fmf、export_setpiece |
| status | ENGINE_COMPATIBILITY 与 /api/status |

## 5. 数据模型

### 5.1 Scenario

沿用现有格式：

- schema 3 为权威输入；schema 4 为双阶段视图，字段为 teams[].phase_plans[2]。
- 顶层字段：schema、rules、fixture、teams[2]，可选 native_generation、experimental_execution。
- 球队字段：name、tactic_name、mentality、instructions、lineup、captains、takers、setpieces、opposition、players、phases 或 phase_plans、roster_size、native_extra_team_bits。
- Agent 只操作 schema 4；提交时由服务端归一化为 schema 3。

### 5.2 Draft

草案文件路径：<dataDir>/agent/drafts/<draft_id>.json
draft_id 格式：dr_ 加 12 位十六进制。

```json
{
  "schema": 1,
  "id": "dr_ab12cd34ef56",
  "name": "高位逼抢对照",
  "created_at": "2026-11-08T18:40:00+08:00",
  "updated_at": "2026-11-08T18:42:10+08:00",
  "source": {"kind": "default", "ref": null},
  "meta": {"api": "fm27lab/v1", "scenario_view_schema": 4, "server_version": "1108.5"},
  "scenario": {"schema": 4, "rules": "game", "fixture": "bundled_match_pkm", "teams": []}
}
```

约束：

- scenario 保持 schema 4。
- 单文件不超过 5 MB。
- 原子写入：临时文件加 os.replace。
- 草案归 Agent 层所有；App 不读取、不感知草案。
- 提交时由服务端重新校验并快照，草案之后可继续修改而不影响已提交实验。

### 5.3 Job 与 Run

沿用现有字段，Agent 视图补充：

- job.runs_total、job.runs_truncated。
- Agent 视图的 runs 按 sequence 升序。
- run 精简字段：variant、seed、sequence、score、statistics、verified、attempts、elapsed_seconds、native_elapsed_seconds、log、events 可选。
- 失败继续放在 job.failures，字段同现有实现。
- 状态机沿用 queued、running、complete、error、cancelled、interrupted。

### 5.4 Career

- 存档进度状态：reading、complete、error、empty，新增 cancelled。
- 导入结果含 save_id、source_sha256、date、build、managed、clubs、warnings。
- 对手报告沿用现有字段，首期只保证 coach 来源。
- count 语义为每对手总场数，必须偶数，主客场各半。

### 5.5 结果视图

- metrics 沿用现有结构，含 n、wins、draws、losses、win_rate、win_interval、goals_for、goals_against、points。
- 存档模式追加 xg、xga、possession、shots、pass_completion、opponent_metrics、paired。
- results_csv 输出列见 CLI 章节。

## 6. Draft 工作区

### 6.1 创建来源

| source | 必填 | 行为 |
| --- | --- | --- |
| default | 无 | 读取 /api/agent/v1/defaults 的默认场景，转 schema 4 |
| save | save_id、club_uid、tactic_index，可选 lineup、bench | 调用 career/load 生成场景，转 schema 4 |
| fmf | file_base64 或 file_path、side、base_scenario 或 base_draft_id | 调用 fmf/import，结果转 schema 4 |
| job | job_id、variant | 调用 jobs/{id}/export，取指定 variant 的场景 |
| inline | scenario | 直接校验并保存 |

### 6.2 语义编辑

每次调用只改一个目标，成功返回 changed 与摘要，失败不保存。

| op | 参数 | 语义 |
| --- | --- | --- |
| team_instruction | side、phase、group、option | 设置 phase_plans[phase].team_instructions[group] |
| mentality | side、value 1 到 7 | 设置球队心态 |
| role | side、phase、slot 0 到 10、role、duty 可选 | 设置位置角色与职责 |
| player_instruction | side、phase、slot、group、option | 设置个人指令 |
| lineup | side、starters 11 人、bench 0 到 12 人 | 设置首发与替补 |
| formation | side、phase、positions 11 项 | 设置阶段阵型位置，必须含唯一 GK |
| tactic_name | side、value | 设置战术名称 |

约束：

- side 0 与 1 对应 teams[0] 与 teams[1]，不代表实际主客；存档批次的实际主客由 schedule 决定。
- group 与 option 的合法值来自 catalog；非法值返回 validation_failed。
- role 必须属于该 phase；duty 只允许现有职责位。
- 首期不提供定位球、针对性指令和球员属性的语义编辑；这些字段通过 FMF 导入或完整场景替换维护。
- 编辑后立即调用服务端 validate 与 phase-plan，通过后才落盘。

### 6.3 校验与规范化

- 编辑流程：应用修改，调用 /api/agent/v1/validate，失败则回滚内存修改。
- 校验通过后调用 /api/agent/v1/phase-plan 获得归一化 schema 4，落盘。
- validate 只返回第一条错误；Agent 应逐次编辑并校验，便于定位。
- 草案加载时记录当时的 scenario_view_schema 与 server_version，版本不匹配时提示重新校验。

### 6.4 生命周期

- draft_list 按 updated_at 倒序。
- draft_delete 为物理删除；已被实验引用的场景已由 App 快照，不受影响。
- 草案与导出文件不自动清理；由用户或 Agent 显式删除。

## 7. CLI

入口：fm27lab 或 python -m fm27_agent。

### 7.1 全局选项

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| --data-dir PATH | 环境变量 FM27LAB_DATA 或默认数据目录 | 读取 endpoint.json |
| --endpoint URL | endpoint.json | 覆盖服务地址，用于测试 |
| --token TOKEN | endpoint.json | 覆盖 token |
| --json | 关 | 输出单份 JSON |
| --timeout SECONDS | 120 | 单次 HTTP 超时 |
| --quiet | 关 | 仅输出结果 |
| --no-color | 关 | 关闭颜色 |

### 7.2 命令表

| 命令 | 关键参数 | 说明 |
| --- | --- | --- |
| fm27lab status | 无 | 清单、引擎、活动任务 |
| fm27lab mcp | 无 | 以 stdio 启动 MCP sidecar |
| fm27lab engine select | --game PATH | 设置游戏根并预检 |
| fm27lab draft create | --from default、save、fmf、job、inline；--name；--save-id；--club；--tactic；--job；--variant；--file；--side；--base-draft；--inline FILE | 创建草案 |
| fm27lab draft list | 无 | 列出草案 |
| fm27lab draft show | ID、--full | 摘要或完整场景 |
| fm27lab draft edit | ID、--op、--team A 或 B、--phase、--group、--option、--value、--slot、--role、--duty、--starters、--bench、--positions | 语义编辑 |
| fm27lab draft validate | ID | 校验与规范化 |
| fm27lab draft delete | ID | 删除草案 |
| fm27lab run | --draft、--baseline、--seeds 1-10、--workers、--quick、--name、--wait | 自由模式运行 |
| fm27lab job list | --status、--limit、--offset | 任务分页 |
| fm27lab job get | ID | 任务详情 |
| fm27lab job wait | ID、--timeout | 等待终态或超时 |
| fm27lab job action | ID、--cancel、--resume、--delete、--rename NAME、--workers | 任务操作 |
| fm27lab job logs | ID、--run LOG、--out FILE | 下载单场原始日志 |
| fm27lab job export | ID、--out DIR | 导出汇总、方案与 provenance |
| fm27lab results summary | ID | 汇总指标 |
| fm27lab results matches | ID、--variant、--limit、--offset、--events | 逐场分页 |
| fm27lab results match | ID、--variant、--seed | 单场详情 |
| fm27lab results csv | ID、--out FILE | 导出 CSV |
| fm27lab career import | --save PATH、--wait | 导入存档 |
| fm27lab career status | --save-id | 导入进度 |
| fm27lab career team | --save-id、--club | 球队、球员、战术 |
| fm27lab career opponents | --save-id、--club、--wait | 同联赛对手扫描 |
| fm27lab career preview | --save-id、--club、--key、--draft | 对手预览 |
| fm27lab career cancel | --save-id、--kind import 或 opponents | 取消导入或扫描 |
| fm27lab career run | --save-id、--club、--draft、--opponents KEY,...、--count、--first-seed、--baseline、--workers、--quick、--wait | 存档批次 |
| fm27lab fmf import | --draft、--side、--file | 导入战术到草案 |
| fm27lab fmf export | --draft、--side、--out | 导出战术文件 |
| fm27lab setpiece export | --draft、--side、--type、--variant、--out | 导出定位球文件 |

### 7.3 输出与退出码

- 默认输出人类可读表格；--json 输出单份 JSON 到 stdout。
- 进度写 stderr；结果写 stdout。
- 退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 2 | 用法错误 |
| 3 | 应用未运行或 endpoint.json 不存在 |
| 4 | 鉴权失败 |
| 5 | 引擎不可用或不兼容 |
| 6 | 校验失败 |
| 7 | 引擎忙 |
| 8 | 资源不存在 |
| 9 | 任务失败、取消或中断 |
| 10 | 内部错误 |

### 7.4 CSV 列

自由模式：mode、variant、seed、home_goals、away_goals、shots、shots_on_target、xg、possession、passes、completed_passes、elapsed_seconds、attempts、log。
存档模式追加：opponent_key、venue、tested_side。
事件明细导出时追加：goals、cards 的紧凑 JSON 字符串。

## 8. MCP

### 8.1 传输与生命周期

- 传输：stdio，JSON-RPC 2.0，按行分隔；stdout 只写协议消息，日志写 stderr。
- 协议版本：支持 2025-06-18 与 2024-11-05，按客户端请求协商。
- 能力：tools、resources、prompts、logging。
- 启动时读取 endpoint.json；缺失且启用自动拉起时调用 Launcher --headless，等待最长 120 秒。
- 连接失败时重新读取 endpoint.json 一次，端口或 token 变化后自动重连。
- 初始化时读取 manifest，校验 api 主版本；不兼容直接返回错误并退出。
- 工具调用为同步 HTTP；长任务返回 job_id，由 job_wait 或进度通知推进。
- 客户端断开时退出 sidecar；不主动停止 App，除非本次由 sidecar 拉起。

### 8.2 工具清单

| 工具 | 作用 |
| --- | --- |
| lab_status | 清单、引擎兼容、活动任务、存档活动状态 |
| engine_select | 设置游戏根并预检 |
| draft_create | 从默认、存档、战术文件、任务导出或内联场景创建草案 |
| draft_get | 读取草案摘要或完整场景 |
| draft_edit | 单步语义编辑 |
| draft_validate | 校验并规范化 |
| draft_list | 列出草案 |
| draft_delete | 删除草案 |
| career_import | 导入存档，返回 save_id |
| career_status | 存档导入进度 |
| career_team | 读取球队、球员、战术与选择 |
| career_opponents | 扫描同联赛对手 |
| career_preview | 预览指定对手 |
| career_cancel | 取消导入或扫描 |
| experiment_run | 自由模式批次，可带对照草案 |
| career_run | 存档对战批次 |
| job_get | 任务详情与 runs 分页 |
| job_wait | 等待任务终态或超时 |
| job_list | 任务分页 |
| job_action | 取消、续跑、删除、重命名 |
| results_summary | 汇总指标、分布与配对差值 |
| results_matches | 逐场分页，可选事件 |
| results_csv | 导出 CSV 并返回路径 |
| fmf_import | 战术文件导入草案 |
| fmf_export | 战术文件导出 |
| setpiece_export | 定位球文件导出 |

### 8.3 工具参数细则

通用输出：成功返回 content 文本摘要与 structuredContent 数据；失败 isError 为 true，structuredContent 为错误封套。

lab_status：无参数。返回 manifest、engine 兼容状态、active_job、save_active。

engine_select：game_root 字符串必填。返回兼容状态，等价于 /api/agent/v1/engine/select。

draft_create：source 必填，取值 default、save、fmf、job、inline；name 可选；save 来源需要 save_id、club_uid、tactic_index，可选 lineup、bench；fmf 来源需要 side、file_base64 或 file_path，以及 base_scenario 或 base_draft_id；job 来源需要 job_id、variant；inline 来源需要 scenario。返回 draft_id 与摘要。

draft_get：draft_id 必填；include_scenario 布尔，默认 false。返回摘要或完整场景。

draft_edit：draft_id 与 op 必填，其余按 op 必填，字段同 6.2。返回 draft_id、changed、摘要与校验结果。

draft_validate：draft_id 必填。返回 valid、errors、records、摘要。

draft_list：无参数。返回草案摘要列表。

draft_delete：draft_id 必填。返回 deleted。

career_import：save_path 必填；wait 布尔，默认 false；timeout_seconds 默认 60。未等待时返回 save_id 与状态；等待时最多等 timeout_seconds，超时返回当前进度，由 Agent 继续轮询。

career_status：save_id 可选。返回进度与元数据。

career_team：save_id、club_uid 必填。返回球员、战术列表、选择与来源。

career_opponents：save_id、club_uid 必填；wait 布尔，默认 false；timeout_seconds 默认 60。未等待返回 reading；等待返回完整报告或超时进度。

career_preview：save_id、club_uid、key、draft_id 必填；适配器从草案取场景后调用 career/preview。返回对手 team 与来源。

career_cancel：kind 取 import 或 opponents，save_id 必填，club_uid 在 opponents 时必填。返回 accepted。

experiment_run：draft_id 必填；baseline_draft_id 可选；seeds 为起始与数量，或长度 1 到 10000 的唯一整数数组；workers 可选；event_details 默认 true；name 可选。返回 job_id、total、workers。

career_run：save_id、club_uid、draft_id、opponents、count、first_seed 必填；baseline_draft_id、workers、event_details、name 可选。返回 job_id、total、workers。

job_get：job_id 必填；runs_offset、runs_limit、variant 可选。返回任务详情与 runs 分页。

job_wait：job_id 必填；timeout_seconds 默认 60，最大 300；poll_ms 默认 1000。返回任务详情；超时返回当前状态并带 timed_out。

job_list：status、limit、offset 可选。返回分页。

job_action：job_id 与 action 必填，action 取 cancel、resume、delete、rename；resume 可带 workers；rename 必须带 name。返回对应结果。

results_summary：job_id 必填。返回 metrics、distributions、paired、failures 摘要、timings。

results_matches：job_id 必填；variant、seed、limit、offset、include_events 可选。返回 runs 分页与 runs_total；带 seed 时返回单场。

results_csv：job_id 必填；out 可选。MCP 工具只接受 dataDir/agent/exports 下的相对文件名，默认按 job_id 命名；CLI 的 --out 可写用户指定路径。返回 path、sha256、rows。

fmf_import：draft_id、side、file_base64 或 file_path 必填。返回更新后的草案摘要与 report。

fmf_export：draft_id、side 必填；name 可选。返回 filename、path、sha256、report。

setpiece_export：draft_id、side、type、variant 必填。返回 filename、path、sha256、report。

### 8.4 资源

| URI | 内容 |
| --- | --- |
| fm27://manifest | 清单与能力 |
| fm27://catalog | 领域枚举与默认值 |
| fm27://status | 引擎、活动任务、存档状态 |
| fm27://drafts/{draft_id} | 草案 JSON |
| fm27://jobs/{job_id} | 任务摘要 |
| fm27://jobs/{job_id}/export | 汇总、方案与 provenance |
| fm27://jobs/{job_id}/logs/{name} | 单场原始 JSONL |
| fm27://saves/{save_id} | 存档导入状态与元数据 |

大结果只走资源，工具回摘要与游标。

### 8.5 prompts

| 名称 | 参数 | 用途 |
| --- | --- | --- |
| test_tactic_change | draft_id、instruction、seeds | 引导执行单变量对照实验 |
| compare_baseline_vs_current | baseline_draft_id、draft_id、seeds | 引导读取配对差值并解释 |
| opponent_sweep | save_id、club_uid、draft_id、count | 引导存档多对手扫描 |

### 8.6 进度、取消与日志

- 请求带 progressToken 时，job_wait 按 poll_ms 轮询并发送 notifications/progress，字段为 progress、total，可选 message。
- 收到 notifications/cancelled 时停止等待，保留 job，不自动取消。
- 阶段变化通过 notifications/message 发送，级别 info。
- 工具文本摘要控制在 2 KB 内，明细走 structuredContent 或资源。

### 8.7 客户端配置

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "C:\\Users\\<you>\\AppData\\Local\\FM27TacticsDesktop\\agent\\fm27lab.cmd",
      "args": ["mcp"]
    }
  }
}
```

### 8.8 工具 schema 细则

工具 inputSchema 由 src/fm27_agent/schemas.py 单点定义，MCP 与 CLI 共用同一份参数定义。字段类型、必填与约束与 8.3 一致；枚举值来自 manifest 与 catalog。错误统一映射为 4.3 错误码。

## 9. 工作流

### 9.1 自由模式对比

```text
lab_status
draft_create source=default name=baseline
draft_create source=default name=pressing
draft_edit pressing op=team_instruction side=1 phase=out_of_possession group=<逼抢组> option=<更高强度>
draft_validate pressing
experiment_run draft_id=pressing baseline_draft_id=baseline seeds={start:101,count:10} workers=2 event_details=false
job_wait job_id timeout_seconds=300
results_summary job_id
```

读取口径：

- metrics.B.win_rate 与 win_interval 判断变化是否稳定。
- paired.goal_difference_delta 判断同种子配对差值。
- 先 2 到 6 场探测，再扩到 20 到 100 场。

### 9.2 存档对战

```text
career_import save_path=... wait=false
career_status save_id
career_team save_id club_uid
draft_create source=save save_id club_uid tactic_index
draft_edit draft_id op=team_instruction side=0 phase=in_possession group=... option=...
draft_validate draft_id
career_opponents save_id club_uid wait=true
career_preview save_id club_uid key draft_id
career_run save_id club_uid draft_id opponents=[key,...] count=6 first_seed=100 workers=2
job_wait job_id
results_summary job_id
```

注意 count 为每对手总场数，必须偶数，主客场各半。

### 9.3 战术文件往返

```text
draft_create source=job job_id variant=B
fmf_import draft_id side=1 file_base64=...
draft_validate draft_id
fmf_export draft_id side=1
```

导出后 App 会立即回读并比对，report 中不一致会报错。

## 10. 安全与隐私

- 仅 loopback；Host 白名单；token 或 cookie；Origin 检查保留。
- token 存于用户目录，建议 icacls 收紧到当前用户；每次启动轮换。
- Agent 命名空间不提供任意文件读写：存档导入只读用户指定 .fm，导出只写 dataDir 下 agent/exports；MCP 工具不接受绝对路径输出。
- 不暴露原生宿主命令行，不提供绕过兼容检查、DLL/SHA 门禁或完赛校验的入口。
- 破坏性操作需要显式参数：删除草案与实验、切换游戏根、覆盖导出文件。
- 不提取、不打包、不上传游戏 DLL 与资源；存档与结果仅保留本机。
- 日志只记录命令、耗时、退出码与错误码，不记录完整场景与存档内容。
- 单任务限制由 App 执行，Agent 层不排队、不重试提交。

## 11. 性能与预算

- 单场耗时没有公开基准；按 190 秒无进度超时作为最坏边界理解。
- 原生会话复用 64 场，首批比赛承担 DLL 加载与激活开销。
- workers 上限由机器计算，当前最大 4。
- 准备阶段要求约 20 GiB 可用磁盘；每场按 3 MiB 预留。
- 建议预算：

| 场景 | 建议 |
| --- | --- |
| 首次探测 | 每方案 2 到 6 场，事件明细关闭 |
| 战术对比 | 每方案 10 到 20 场，同种子 |
| 对手扫描 | 每对手 4 到 6 场，偶数 |
| 单次提交上限 | 10000 场，超出需用户确认 |
| job_wait 单次 | 60 秒，最大 300 秒 |

- 提交回包带 total；运行中 job 带 eta_seconds 与 matches_per_minute。
- 首次实际运行后记录单场耗时，用于后续预算。

## 12. 兼容与版本

- api 为 fm27lab/v1；主版本不同即不兼容。
- manifest 暴露 server、adapter、engine_build、scenario_schema、batch_schema 与能力位。
- 草案记录 scenario_view_schema 与 server_version；加载时校验，不匹配提示重新校验。
- 引擎状态原样透出 compatible、trial_allowed、original_build_verified、resource_fingerprint。
- 适配器版本绑定参考构建 27.0.0+2493426；升级时需要同步 adapter 与规格。
- App 升级后旧草案仍可加载，但提交前必须重新校验；旧实验按 provenance 规则不可混跑。
- 幂等键与活动任务在重启后清空；状态以磁盘 summary 与 provenance 为准。

## 13. 验收标准

| 编号 | 验收项 | 通过标准 |
| --- | --- | --- |
| A1 | 发现与鉴权 | 无 token 访问 Agent 端点返回 401；错误 Host 返回 403；UI 页面正常 |
| A2 | 清单与 schema | manifest 字段齐全；schema 包可解析；主版本不匹配时 CLI 与 MCP 明确报错 |
| A3 | 草案 | 五种来源均可创建；编辑、校验、删除、列表均通过；非法编辑不落盘 |
| A4 | 自由模式 | 通过 CLI 与 MCP 各完成一次 A/B 对比；结果含 metrics 与 paired |
| A5 | 存档模式 | 导入、球队读取、对手扫描、预览、批次运行完成；count 口径正确 |
| A6 | 任务 | 列表分页、详情分页、取消、续跑、删除、重命名、导出均通过 |
| A7 | 结果 | 汇总、逐场分页、单场事件、CSV 列正确 |
| A8 | 战术文件 | FMF 导入导出往返一致；定位球导出回读通过 |
| A9 | 错误 | 每个错误码至少一条用例；错误可重试标记正确 |
| A10 | 幂等 | 同键同载荷不重复建任务；同键异载荷返回 409 |
| A11 | 生命周期 | headless 启动、shutdown 优雅退出、活动任务取消后退出 |
| A12 | 兼容 | 现有 UI 全流程不受影响；旧 /api 响应形状不变 |
| A13 | 安全边界 | 路径越界被拒；不暴露原生宿主 |
| A14 | 恢复 | App 重启后任务标记 interrupted，可续跑；草案保留 |
| A15 | 性能基线 | 记录单场耗时与批次吞吐，写入验收记录 |

## 14. 实施分期

| 阶段 | 内容 | 完成标准 |
| --- | --- | --- |
| P0 服务端契约 | endpoint.json、Host 与 token、Agent 命名空间、manifest 与 schema、错误封套、分页、幂等、health、shutdown、save cancel、headless | A1、A2、A6 的分页部分、A9、A10、A11、A12 通过 |
| P1 CLI 与草案 | src/fm27_agent 客户端、草案存储、CLI 命令、mock server 契约测试 | A3、A4 的 CLI 链路、A7、A8 的 CLI 链路通过 |
| P2 MCP | stdio sidecar、tools、resources、prompts、进度与取消、配置生成 | A4 的 MCP 链路、A5、A14 通过 |
| P3 收尾 | 打包与入口脚本、文档、Windows 端到端验收 | A13、A15 与全量回归通过 |

改动清单：

- src/fm27_tactics_server.py：鉴权与 Host 校验、Agent 路由、manifest 与 schema、分页、幂等、endpoint.json、shutdown、save cancel 接口。
- src/desktop_save_mode.py：读取进程句柄、取消与 cancelled 状态。
- Launcher.cs：headless、token 感知的自检与关闭、入口脚本生成。
- scripts/run.py 与 scripts/build_exe.py：打包 src/fm27_agent、生成源码版入口。
- tests：Agent 契约、CLI、MCP、安全用例。

## 15. 风险与待评审问题

风险：

- 取消存档读取需要终止 fmsave 子进程，可能留下部分缓存；需要定义 cancelled 状态与残留清理。
- token 与 cookie 鉴权会触及所有请求处理；必须回归 UI 全流程。
- headless 与 Launcher Mutex、托盘生命周期需要明确交互。
- 部分 MCP 客户端不支持 resources 与 prompts；工具必须可独立完成全流程。
- 草案与实验绑定本机 data 目录的 HMAC 来源签名，不适合跨机器迁移。
- 单任务与存档单槽限制多 Agent 并行；首期接受忙时返回错误。
- 单场耗时未知，预算默认值需要目标机实测后校准。
- 幂等键仅内存保存，重启后失效。

待评审问题：

- MCP 协议版本支持列表是否需要覆盖更多客户端。
- token 文件是否需要 DPAPI 加密或仅依赖用户目录 ACL。
- 导出文件默认目录是否固定为 dataDir/agent/exports。
- 是否在首期提供 job_export 工具，或仅作为资源。
- CSV 中事件列是否默认关闭，避免大文件。
