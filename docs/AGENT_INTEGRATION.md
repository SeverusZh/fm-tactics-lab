# AI Agent 接入规格

状态：v2 实现事实。本文按本仓库 2.0.0.dev0 代码与实测行为核对，核对日期 2026-11-14。历史上以启动器 EXE 与 fm27lab/v1 命名空间为前提的设计章节已删除，替代事实见各节代码位置。

## 1. 目标与非目标

目标

- 同一台机器上的 Agent 客户端通过回环 HTTP 调用 sidecar，完成战术池、草案、实验、结果、存档与产物的读写。
- 提供两种稳定封装：fm27lab CLI 与 fm27lab MCP 服务，二者都只依赖发现文件，不自行拉起进程。
- 契约以代码为唯一事实来源：参数字段见 fm27lab/interfaces/http/routes，能力映射见 fm27lab/registry.py，OpenAPI 见 GET /api/openapi.json。

非目标

- 不提供远程访问、多用户隔离、Cookie 会话或浏览器登录态。
- 不提供 Agent 专用命名空间；全部接口位于 /api 下。
- 不提供推送式进度通知；长任务靠轮询任务与运行接口。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| App | Tauri 2 桌面壳，负责启动、守护与展示 sidecar |
| Sidecar | fm27lab Python 进程，监听回环地址随机端口，暴露 /api 接口 |
| 发现文件 | 数据目录下 agent/endpoint.json，客户端只读 |
| 数据目录 | 平台默认或 FM27LAB_DATA 指定；存 SQLite、发现文件、产物与实验材料 |
| 引擎工作区 | FM27_ENGINE_ROOT；含 fm27_native 目录与 catalog 数据 |
| 草案 | 存于 SQLite drafts 表的场景记录 |
| 池条目 | 存于 SQLite 的战术池条目库；实验用的 away_tactic_pool 是草案场景内嵌配置 |
| 任务与运行 | Job 一次实验批次，Run 为其中一场比赛 |
| 能力 | fm27lab/registry.py 的 Capability，统一映射 HTTP、CLI、MCP 三个入口 |

## 3. 部署与生命周期

### 3.1 拓扑

客户端到 sidecar 的单跳链路

```text
Agent client / CLI / MCP
        |
        | HTTP 127.0.0.1:<port>，Authorization: Bearer <token>
        v
fm27lab sidecar  ->  SQLite fm27lab.db
        |        ->  agent/ 发现文件与产物
        v
原生引擎宿主  ->  fm27_native/FM27Simulator.exe
```

- sidecar 只能由两方启动：Tauri 壳的 start_sidecar_inner，或人工执行 python -m fm27lab serve。证据 src-tauri/src/lib.rs:209-300、fm27lab/cli.py:66-87。
- CLI 与 MCP 启动时只读 discovery 文件并探测 GET /api/health，不创建 sidecar 进程。证据 fm27lab/cli.py:121-140、fm27lab/client.py:101-141。
- 同一时刻最多一个任务处于 running；再次启动返回 409 invalid_transition，消息为「已有任务在运行」。证据 fm27lab/application/experiments.py:257-299。
- 桌面壳单实例运行；重启 sidecar 上限 3 次，每次重启生成新 token。证据 src-tauri/src/lib.rs:24-27、src-tauri/src/lib.rs:209-300。

### 3.2 发现文件

路径为数据目录下 agent/endpoint.json，由 sidecar 启动时写入，退出时删除。证据 fm27lab/config.py:92-93、fm27lab/sidecar.py:33-66。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| schema | integer | 发现文件版本，当前为 1 |
| api | string | 接口版本，当前为 fm27lab/v2 |
| url | string | 形如 http://127.0.0.1:<port> 的回环根地址 |
| port | integer | 实际监听端口；请求 0 时由系统分配 |
| token | string | Bearer token；任意非空 ASCII 字符串，缺省时由 sidecar 生成 64 位小写十六进制（fm27lab/config.py:31-66） |
| pid | integer | sidecar 进程号 |
| data_dir | string | 数据目录绝对路径 |
| engine_root | string 或 null | 引擎工作区；未配置时为 null |
| created_at | string | 本地时区的 ISO 8601 时间 |

```json
{
  "schema": 1,
  "api": "fm27lab/v2",
  "url": "http://127.0.0.1:54321",
  "port": 54321,
  "token": "<令牌；缺省生成为 64 位小写十六进制>",
  "pid": 24680,
  "data_dir": "/home/user/.fm27lab",
  "engine_root": "/home/user/.fm27lab/engine",
  "created_at": "2026-11-14T07:00:00.123456+08:00"
}
```

写入与权限

- 先写 endpoint.json.tmp 再原子替换，权限 0600；Windows 上用 icacls 去掉继承。证据 fm27lab/sidecar.py:33-59。
- 退出时删除发现文件；Tauri 壳停止 sidecar 后还会兜底删除 endpoint.json 与 .json.tmp。证据 fm27lab/sidecar.py:62-66、src-tauri/src/lib.rs:151-155。

客户端校验与错误码

- url 必须是 http 协议、回环主机且为根地址；token 必须非空 ASCII。证据 fm27lab/client.py:64-98。
- 错误码：endpoint_missing 找不到发现文件、endpoint_unreadable 无法读取、endpoint_invalid 字段不合法。证据 fm27lab/client.py:106-141。
- 本实现不生成 fm27lab.cmd，也不生成 mcp.json；客户端配置由用户自行编写，见 8.6。

### 3.3 启动与关闭

手工启动

```bash
python -m fm27lab serve \
  --data-dir /absolute/path/data \
  --engine-root /absolute/path/engine \
  --host 127.0.0.1 \
  --port 0
```

serve 选项

| 选项 | 说明 |
| --- | --- |
| --data-dir | 数据目录；相对路径会被解析为绝对路径，不得为空且不得等于当前工作目录 |
| --engine-root | 引擎工作区；可省略，省略时发现文件里 engine_root 为 null |
| --host | 回环主机，默认 127.0.0.1 |
| --port | 端口；默认 0 表示由系统分配 |
| --token | 固定 Bearer token；省略时生成 32 字节随机数的十六进制 |
| --dev 与 --no-dev | 是否允许 Vite 开发源 http://localhost:1420 |

证据 fm27lab/cli.py:66-87、fm27lab/config.py:29-56。

环境变量

| 变量 | 作用 |
| --- | --- |
| FM27LAB_DATA | 数据目录 |
| FM27_ENGINE_ROOT | 引擎工作区 |
| FM27LAB_TOKEN | 固定 token |
| FM27LAB_PORT | 监听端口 |
| FM27LAB_HOST | 监听主机 |
| FM27LAB_DEV | 值为 1 时开启开发模式 |

证据 fm27lab/config.py:69-85。

桌面壳启动注入

- 数据目录取 app_local_data_dir；引擎工作区取环境变量 FM27_ENGINE_ROOT，缺省为数据目录下 engine。
- 注入 FM27LAB_DATA、FM27LAB_TOKEN、FM27_ENGINE_ROOT、FM27LAB_PORT=0、PYTHONUTF8=1；debug 构建追加 FM27LAB_DEV=1。
- sidecar 标准错误写入数据目录 logs/sidecar-<pid>.stderr.log。
- 就绪判定：标准输出出现 ready 行，随后 GET /api/health 返回 200；启动超时 30 秒，健康轮询间隔 5 秒。
- 证据 src-tauri/src/lib.rs:24-27、src-tauri/src/lib.rs:209-300。

ready 行

```json
{"event":"ready","port":54321,"pid":24680}
```

证据 fm27lab/sidecar.py:69-95。

关闭

- 调用 POST /api/shutdown，需 Bearer；成功返回 202 与 {"status":"shutting_down"}，进程随后退出并删除发现文件。证据 fm27lab/interfaces/http/routes/system.py:90-94、fm27lab/sidecar.py:69-95。
- 桌面壳停止流程：先 POST /api/shutdown 探测 202，最多等待 10 秒，超时强制结束进程，最后清理发现文件。证据 src-tauri/src/lib.rs:119-155、src-tauri/src/lib.rs:433-463。
- 人工前台运行时可 Ctrl+C 停止，同样走退出清理。

### 3.4 打包与启动脚本

- 前端构建命令为 pnpm --dir web build && python scripts/build_sidecar.py，产物 sidecar-dist/fm27lab-sidecar 作为 Tauri 资源映射到安装目录 sidecar/；映射使用目录形式以保留 PyInstaller onedir 的 _internal 布局。证据 src-tauri/tauri.conf.json。
- release 启动可执行文件为资源目录 sidecar/fm27lab-sidecar，Windows 为 .exe；debug 构建用 FM27LAB_PYTHON 或 python 加参数 -m fm27lab serve，工作目录为项目根。证据 src-tauri/src/lib.rs:49-82。
- 环境变量 FM27LAB_SIDECAR 可覆盖可执行文件路径，主要用于本地联调。证据 src-tauri/src/lib.rs:49-82。
- 不再存在打包脚本生成 fm27lab.cmd 或 mcp.json 的逻辑；v1 的 src/fm27_agent 启动垫片未接入 v2 打包链路。

## 4. HTTP 契约

### 4.1 命名空间与兼容

- 全部接口位于 /api 下；registry 定义的系统与文档路径为 /api/health、/api/version、/api/events、/api/shutdown、/api/docs、/api/openapi.json。证据 fm27lab/registry.py:10-19。
- 不存在 /api/agent/v1 命名空间；实测 GET /api/agent/v1/manifest 返回 404 not_found。
- 文档端点 /api/docs 与 /api/openapi.json 由 FastAPI 直接提供，redoc 关闭。证据 fm27lab/interfaces/http/app.py:107-113。

### 4.2 鉴权与来源校验

- 鉴权为 Authorization: Bearer <token>。缺失或非 Bearer 返回 401 unauthorized 与消息 missing bearer token；不匹配返回 401 与消息 invalid bearer token，并带 WWW-Authenticate: Bearer。证据 fm27lab/interfaces/http/common.py:38-51。
- 免鉴权端点仅 GET /api/health 与 GET /api/version；/api/docs 与 /api/openapi.json 不属于业务路由，也不经过 token 依赖。
- 不提供 Cookie 鉴权，历史设计中的 fm27_session 会话不存在；也不做 Host 白名单校验，历史设计中的 forbidden_host 不存在。
- CORS 允许源为 tauri://localhost 与 http://tauri.localhost；开发模式追加 http://localhost:1420。允许头为 Authorization、Content-Type、Last-Event-ID、Idempotency-Key，方法为 GET、POST、PUT、PATCH、DELETE、OPTIONS，不携带凭据。证据 fm27lab/interfaces/http/app.py:47-48、fm27lab/interfaces/http/app.py:149-158。
- Origin 头存在且不在白名单时返回 403 forbidden_origin，消息 origin is not allowed。证据 fm27lab/interfaces/http/app.py:161-169。
- 安全边界：以上校验只保证本机回环与来源约束，不构成多用户隔离；token 泄露即等效于本机用户权限。

### 4.3 响应与错误

所有错误响应为统一封套

```json
{
  "error": {
    "code": "validation_failed",
    "message": "request body or query is invalid",
    "details": null,
    "retriable": false,
    "retry_after_seconds": null
  }
}
```

retriable 默认在状态码不小于 500 或等于 409 时为 true。证据 fm27lab/interfaces/http/common.py:19-37。

| 状态码 | code | 触发 |
| --- | --- | --- |
| 400 | validation_failed | 请求体或查询参数校验失败 |
| 400 | invalid_idempotency_key | Idempotency-Key 格式非法 |
| 400 | invalid_last_event_id | Last-Event-ID 不是非负整数 |
| 401 | unauthorized | 缺失或无效 Bearer |
| 403 | forbidden_origin | Origin 不在白名单 |
| 404 | not_found | 资源不存在或路径未知 |
| 405 | method_not_allowed | 方法不允许，响应带 Allow 头 |
| 409 | conflict | 唯一约束冲突，如池条目 ID 重复 |
| 409 | invalid_transition | 状态机不允许该流转 |
| 409 | idempotency_conflict | 同一幂等键对应不同载荷 |
| 409 | insufficient_memory | 资源预检内存不足 |
| 409 | insufficient_disk | 资源预检磁盘不足 |
| 413 | payload_too_large | 产物内容超过 16 MiB |
| 500 | internal_error | 未捕获异常 |
| 503 | database_unavailable | 数据库未就绪 |
| 503 | resource_probe_failed | 宿主资源探测失败 |
| 503 | engine_unavailable | 原生引擎未配置或启动失败 |

证据 fm27lab/interfaces/http/app.py:171-212、fm27lab/interfaces/http/routes/*.py。

### 4.4 分页

列表接口统一返回 items、total、next_offset；next_offset 为 null 表示已到末页。证据 fm27lab/application/results.py、fm27lab/interfaces/http/routes/*.py。

| 端点 | limit 默认 | limit 上限 | offset |
| --- | --- | --- | --- |
| GET /api/pools、GET /api/drafts | 128 | 128 | 默认 0 |
| GET /api/jobs、GET /api/saves、GET /api/artifacts | 50 | 256 | 默认 0 |
| GET /api/jobs/{job_id}/runs | 50 | 200 | 默认 0 |

### 4.5 幂等

- 请求头为 Idempotency-Key，只对 POST、PATCH、DELETE 且路径以 /api/ 开头的请求生效；未带该头时直接放行。证据 fm27lab/interfaces/http/idempotency.py:17-24。
- 带 key 时先鉴权；指纹为 sha256 覆盖方法、路径、规范化查询串与请求体；同键同载荷回放首次 2xx 响应的状态码与响应体，不做 Idempotency-Replayed 标记。证据 fm27lab/application/idempotency.py:38-56。
- 只缓存 2xx 响应；同键不同载荷返回 409 idempotency_conflict，消息「幂等键已被不同载荷使用」；键格式非法返回 400 invalid_idempotency_key。
- 幂等记录持久化在数据目录的 SQLite idempotency 表中，进程重启后仍然有效，同一数据库的多进程共享；进程内 asyncio.Lock 只串行单进程内的同键请求，跨进程并发由表的主键与事务裁决。证据 fm27lab/interfaces/http/app.py:148、fm27lab/adapters/storage_sqlite/idempotency.py:35-103、fm27lab/adapters/storage_sqlite/migrations/001_init.sql:97-102。

### 4.6 端点总表

系统端点

| 方法与路径 | 鉴权 | 说明 |
| --- | --- | --- |
| GET /api/health | 否 | 数据库就绪时 200，未就绪 503 database_unavailable |
| GET /api/version | 否 | 返回 api、version、capabilities、limits |
| POST /api/shutdown | 是 | 202 shutting_down |
| GET /api/events | 是 | SSE 事件流 |

证据 fm27lab/interfaces/http/routes/system.py、fm27lab/registry.py:10-19。GET /api/system/resources 与 GET /api/catalog 属于普通能力（system_resources、catalog_snapshot），需要 Bearer，已列入下方能力表；/api/docs 与 /api/openapi.json 见 4.7。

能力端点与三入口映射

| 能力 | HTTP | CLI | MCP |
| --- | --- | --- | --- |
| pools_list | GET /api/pools | pools list | pools_list |
| pools_get | GET /api/pools/{entry_id} | pools get | pools_get |
| pools_create | POST /api/pools | pools create | pools_create |
| pools_delete | DELETE /api/pools/{entry_id} | pools delete | pools_delete |
| drafts_list | GET /api/drafts | drafts list | drafts_list |
| drafts_get | GET /api/drafts/{draft_id} | drafts get | drafts_get |
| drafts_create | POST /api/drafts | drafts create | drafts_create |
| drafts_update | PATCH /api/drafts/{draft_id} | drafts update | drafts_update |
| drafts_delete | DELETE /api/drafts/{draft_id} | drafts delete | drafts_delete |
| drafts_attributes | POST /api/drafts/{draft_id}/attributes | drafts attributes | drafts_attributes |
| drafts_export_fmf | GET /api/drafts/{draft_id}/export.fmf | drafts export-fmf | drafts_export_fmf |
| drafts_import_fmf | POST /api/drafts/import-fmf | drafts import-fmf | drafts_import_fmf |
| drafts_apply_roster | POST /api/drafts/{draft_id}/apply-roster | drafts apply-roster | drafts_apply_roster |
| drafts_undo_roster | POST /api/drafts/{draft_id}/undo-roster | drafts undo-roster | drafts_undo_roster |
| jobs_list | GET /api/jobs | jobs list | jobs_list |
| jobs_get | GET /api/jobs/{job_id} | jobs get | jobs_get |
| jobs_create | POST /api/jobs | jobs create | jobs_create |
| jobs_update | PATCH /api/jobs/{job_id} | jobs update | jobs_update |
| jobs_cancel | POST /api/jobs/{job_id}/cancel | jobs cancel | jobs_cancel |
| jobs_delete | DELETE /api/jobs/{job_id} | jobs delete | jobs_delete |
| jobs_batch_actions | POST /api/jobs/actions | jobs batch-action | jobs_batch_actions |
| jobs_batch_delete | DELETE /api/jobs | jobs batch-delete | jobs_batch_delete |
| jobs_runs | GET /api/jobs/{job_id}/runs | jobs runs | jobs_runs |
| jobs_summary | GET /api/jobs/{job_id}/summary | jobs summary | 无 |
| jobs_export | GET /api/jobs/{job_id}/export.csv | jobs export | jobs_export |
| jobs_pool_summary | GET /api/jobs/{job_id}/pool-summary | jobs pool-summary | jobs_pool_summary |
| saves_list | GET /api/saves | saves list | saves_list |
| saves_get | GET /api/saves/{save_id} | saves get | saves_get |
| saves_create | POST /api/saves | saves create | saves_create |
| saves_update | PATCH /api/saves/{save_id} | saves update | saves_update |
| saves_delete | DELETE /api/saves/{save_id} | saves delete | saves_delete |
| saves_import | POST /api/saves/import | saves import-file | saves_import_file |
| saves_squad | GET /api/saves/{save_id}/squad | saves squad | saves_squad |
| saves_import_payload | POST /api/saves/{save_id}/import | saves import | saves_import |
| artifacts_list | GET /api/artifacts | artifacts list | artifacts_list |
| artifacts_get | GET /api/artifacts/{artifact_id} | artifacts get | artifacts_get |
| artifacts_content | GET /api/artifacts/{artifact_id}/content | artifacts content | artifacts_content |
| artifacts_create | POST /api/artifacts | artifacts create | artifacts_create |
| artifacts_delete | DELETE /api/artifacts/{artifact_id} | artifacts delete | artifacts_delete |
| settings_list | GET /api/settings | settings list | settings_list |
| settings_get | GET /api/settings/{key} | settings get | settings_get |
| settings_put | PUT /api/settings/{key} | settings put | settings_put |
| settings_delete | DELETE /api/settings/{key} | settings delete | settings_delete |
| concurrency_check | GET /api/concurrency/check | concurrency check | concurrency_check |
| experiments_submit | POST /api/experiments | experiments submit | experiments_submit |
| experiments_start | POST /api/experiments/start | experiments start | experiments_start |
| experiments_cancel | POST /api/experiments/{job_id}/cancel | experiments cancel | experiments_cancel |
| experiments_resume | POST /api/experiments/{job_id}/resume | experiments resume | experiments_resume |
| catalog_snapshot | GET /api/catalog | catalog show | catalog_snapshot |
| results_compare | POST /api/results/compare | results compare | results_compare |
| system_resources | GET /api/system/resources | system resources | 无 |

证据 fm27lab/registry.py:96-101、fm27lab/registry.py:104-421。共 51 项能力，其中 jobs_summary 与 system_resources 没有 MCP 工具。

### 4.7 文档端点

- GET /api/docs 返回 Swagger UI，GET /api/openapi.json 返回 OpenAPI 文档；二者无 token 依赖，仅供本机调试。证据 fm27lab/interfaces/http/app.py:107-113。
- 契约核对以 openapi.json 为准：当前 39 条路径、55 个操作、63 个组件模型。

## 5. 数据模型

### 5.1 场景

草案场景在创建与更新时归一化。证据 fm27lab/domain/scenario.py:25-102。

- 顶层必须是对象，teams 必须是长度为 2 的列表，否则报「场景必须是对象」或「场景必须包含两支球队」。
- 每队 players 必须是非空对象列表，每项必须有唯一 source_uid，否则报「球队球员缺少 source_uid」「球队球员 source_uid 重复」「球队球员列表为空」「球队球员 source_uid 无效」。
- 每队必须有门将；门将判定取自球员属性的位置熟练度。证据 fm27lab/domain/roster.py:141-159。
- 输出队伍含 players、roster_size=23、lineup、captains、takers、setpieces.role_priorities、roster_trim；首发 11 人、替补 12 人。证据 fm27lab/domain/roster.py:8-10、fm27lab/domain/scenario.py:25-93。
- 球员属性为 69 维：前 15 维位置熟练度取值 0 到 20，其后取值 1 到 100。证据 fm27lab/domain/attributes.py:12-13、fm27lab/domain/attributes.py:96-102。

### 5.2 草案

- 存储为 SQLite 表 drafts，字段 id、name、scenario_json、source_json、created_at、updated_at；列表按 updated_at 倒序、同时间按 rowid 倒序。证据 fm27lab/adapters/storage_sqlite/repositories.py:241-266。
- ID 由 8 字节随机数生成，16 位小写十六进制。证据 fm27lab/adapters/storage_sqlite/repositories.py:340-342。
- 创建与更新均归一化场景；更新只接受 name、scenario、source，未提供字段或未知字段报「草案更新字段无效」，source 必须是对象，否则报「草案来源必须是对象」。证据 fm27lab/application/drafts.py:59-70。
- 删除为物理删除，返回 204。证据 fm27lab/adapters/storage_sqlite/repositories.py:323、fm27lab/interfaces/http/routes/drafts.py。
- 不存在磁盘草案目录；历史设计中的 agent/drafts/<id>.json 与 dr_ 前缀不存在。

### 5.3 池条目与 away_tactic_pool

池条目库

- 字段 id、name、weight、tactic、roster、created_at。name 长度 1 到 80，weight 取值 1 到 1000 默认 1，tactic 必填对象，roster 可选对象，id 可选且需匹配 ^[A-Za-z0-9_-]{1,64}$。证据 fm27lab/interfaces/http/routes/pools.py:44-46。
- 创建返回 201；ID 冲突返回 409 conflict，消息 pool entry already exists。证据 fm27lab/adapters/storage_sqlite/repositories.py:77-120。
- 池条目库与实验没有代码关联：实验只读取草案场景内的 away_tactic_pool 配置。证据 fm27lab/application/experiment_material.py:89-113。

草案内 away_tactic_pool

- 顶层结构仅 profile，profile 必须为 away-tactic-pool-v1，包含 enabled、entries、uniform、rotation、real。证据 fm27lab/domain/pool.py:36、fm27lab/domain/pool.py:187-520。
- 条目上限 128，单套 weight 上限 1000，轮战 rounds 上限 1000，名称上限 80 字符，名单人数上限 26，单套名单序列化上限 1500000 字节。证据 fm27lab/domain/pool.py:26-31。
- 每套 tactic 必填 tactic_name、mentality、instructions、native_extra_team_bits、phases；phases 为两阶段乘十一位位置的矩阵。证据 fm27lab/domain/pool.py:461-520。
- roster 可选；real.enabled 时每套必须带存档名单，人数 11 到 26。证据 fm27lab/domain/pool.py:379-380。
- random 模式按权重逐场抽签，抽签随机源为 salt 与 seed 拼接字符串，实验物化时 salt 取任务 ID；rotation 模式按顺序轮换，要求种子数等于条目数乘 rounds 且总场数不超过 10000。证据 fm27lab/domain/pool.py:90-112、fm27lab/application/experiment_material.py:89-113。
- uniform.enabled 时客队可见属性统一取值 attribute_value，默认 15，门将属性置 1，战术位置熟练度置 20；real 名单优先于 uniform。证据 fm27lab/domain/pool.py:600-640。
- 提交实验时按 seed 展开为每场场景并移除 away_tactic_pool 键。证据 fm27lab/domain/pool.py:520 附近 expand_away_scenarios。

### 5.4 任务与运行

任务状态集合与流转

| 起始状态 | 允许流转到 |
| --- | --- |
| queued | running、cancelled、error |
| running | completed、error、cancelled、interrupted |
| interrupted | queued、running、cancelled |
| completed、error、cancelled | 无 |

证据 fm27lab/application/jobs.py:13-21。

- 创建字段：kind 长度 1 到 64 必填，name 长度 1 到 100 可选，config 对象默认空，workers 取值 1 到 256 默认 1，total 不小于 0 默认 0。证据 fm27lab/interfaces/http/routes/jobs.py:12-18。
- 更新只接受 status、completed、summary、name；completed 不得小于 0；非法状态报「任务状态无效」，状态机不允许报 409 invalid_transition。证据 fm27lab/interfaces/http/routes/jobs.py:21-27、fm27lab/application/jobs.py。
- 取消走 POST /api/jobs/{job_id}/cancel；批量操作为 POST /api/jobs/actions，action 取值 cancel 或 delete，ids 最多 256 个且不可重复；批量删除为 DELETE /api/jobs 携带 body ids。
- 运行字段：job_id、sequence、variant、seed、score、verified、stats、events、log_path、created_at；score 解析顺序为 result.score、run.score、home_goals 与 away_goals，要求长度为 2 的非负整数，否则为空。证据 fm27lab/domain/results.py:12-24。
- 任务字段：id、kind、status、name、config、summary、workers、total、completed、created_at、started_at、finished_at。

### 5.5 结果视图

汇总

- GET /api/jobs/{job_id}/summary?side=0|1 返回 job、metrics、paired。side 取 0 表示主队视角，1 表示客队视角；非 0 或 1 返回 400。证据 fm27lab/interfaces/http/routes/results.py。
- metrics 字段为 n、wins、draws、losses、win_rate、win_interval、goals_for、goals_against、points、xg、xga、possession、shots、pass_completion；xg、xga、possession、shots、pass_completion 可为 null。证据 fm27lab/domain/results.py:53-113。
- win_rate 为胜场比，win_interval 为 Wilson 95% 区间；进球与积分按场均计算。
- paired 字段为 n 与 goal_difference_delta，可为 null。

逐场与导出

- GET /api/jobs/{job_id}/runs 分页返回运行记录。
- GET /api/jobs/{job_id}/export.csv 返回 text/csv，列顺序为 job_id、sequence、variant、seed、score_home、score_away、verified、created_at、stats_json、events_json。证据 fm27lab/application/results.py:19-30、fm27lab/application/results.py:342-352。
- GET /api/jobs/{job_id}/pool-summary 返回 enabled、entry_count，以及可选的 mode、rounds、players、uniform、entries、draws；draws 为种子到条目下标的映射。

比较

- POST /api/results/compare 输入 baseline_job_id、candidate_job_ids、variant 默认 B、side 默认 0、reps 默认 2000 且取值 1 到 20000；候选最多 32 个。证据 fm27lab/interfaces/http/routes/results.py。
- 输出 baseline、variant、side、candidates；每个候选含 job_id、name、metrics、tactic_pool、comparable、reason、pairing、paired；pairing 含 common_seeds、draw_mismatches、mismatched_seeds、missing_seeds；paired 含 seeds、win_rate_delta、points_delta、goal_difference_delta、xgd_delta 及各自置信区间。
- 池任务先核对模式、条目与抽签分配；不一致时 comparable 为 false 并给出 reason。证据 fm27lab/domain/compare.py。

### 5.6 存档、产物、设置与并发检查

存档

- 字段 id、source_path、source_sha256、status、stage、metadata、created_at、updated_at。
- 状态流转：pending 到 reading、error、cancelled；reading 到 ready、error、cancelled；ready、error、cancelled 为终态。证据 fm27lab/application/saves.py:12-18。
- 导入分两个接口：POST /api/saves/import 从源文件登记并读取存档，返回 save_id、status、managed_clubs、clubs；POST /api/saves/{save_id}/import 上传 leagues 与 clubs 结构。证据 fm27lab/interfaces/http/routes/saves.py。
- GET /api/saves/{save_id}/squad?club_uid= 返回球队名单与当前选择；club_uid 取值 1 到 2147483647。

产物

- 字段 id、job_id、kind、path、sha256、bytes、created_at。
- 内容上限 16 MiB，超限返回 413 payload_too_large；文件写入数据目录 agent/artifacts。证据 fm27lab/interfaces/http/routes/artifacts.py:14、fm27lab/interfaces/http/routes/artifacts.py:141-150。

设置

- 字段 key、value、note、updated_at；PUT 接受任意 JSON 值与可选 note；删除返回 204；不存在返回 404。证据 fm27lab/interfaces/http/routes/settings.py。

并发检查

- GET /api/concurrency/check 查询参数 workers、cpu_count、available_memory_bytes、free_disk_bytes、allow_oversubscription 全部以字符串传入并逐个解析，解析失败返回 400 validation_failed。证据 fm27lab/interfaces/http/routes/settings.py:148-187。
- 输出 allowed、code、recommended_workers、warnings、memory_required_bytes、disk_required_bytes；每个并行 worker 预算内存 1 GiB、磁盘 1 GiB，另保留内存 2 GiB，推荐值上限 256。证据 fm27lab/domain/concurrency.py。

## 6. 实验提交与执行

提交

- POST /api/experiments 输入 name、seeds、draft_id、baseline_draft_id、workers、cpu_count、available_memory_bytes、free_disk_bytes、allow_oversubscription。
- seeds 为 1 到 10000 个不重复整数，取值 0 到 4294967295；越界或重复由请求模型拒绝，HTTP 与 CLI 均返回 400 validation_failed、消息「request body or query is invalid」。服务层另有「种子必须为非空且不重复的 0–4294967295 整数列表」，仅内部调用可达。证据 fm27lab/interfaces/http/routes/experiments.py:13-14、:34-39、fm27lab/interfaces/http/app.py:199-204、fm27lab/application/experiments.py:24。
- 有 baseline_draft_id 时变体为 A 与 B，否则只跑 B；总场数为种子数乘变体数，超过 10000 报「实验总场数不能超过 10000」。证据 fm27lab/application/experiments.py:160-164、fm27lab/application/experiments.py:20。
- 资源预检不通过返回 409，错误码为 insufficient_memory 或 insufficient_disk。证据 fm27lab/domain/concurrency.py。
- 草案不存在返回 404 not_found。
- 引擎工作区缺失时报「引擎目录未配置，无法生成比赛配置」；catalog 缺失时报「未找到引擎目录文件，无法生成比赛配置」，均为 400 validation_failed。证据 fm27lab/application/experiment_material.py:30-31。
- 物化目录为数据目录 agent/experiments/<job_id>/，含 provenance.json 与每场配置；配置编码为 FM27CFG1，场景模式为 fm27lab-scenario/1。证据 fm27lab/application/experiment_material.py:63-160。

执行

- 没有后台调度线程。POST /api/experiments/start 取 created_at 最早的 queued 任务，在请求线程内同步执行整批；成功返回 200 与 job，无待运行任务返回 204。证据 fm27lab/application/experiments.py:252-299、fm27lab/interfaces/http/routes/experiments.py:120。
- 已有 running 任务返回 409 invalid_transition，消息「已有任务在运行」；工具异常返回 503 engine_unavailable，错误摘要写入任务 summary.error。证据 fm27lab/application/experiments.py:252-299。
- 取消：queued 直接置 cancelled；running 设置取消事件并调用引擎取消；其他状态报「任务状态不允许取消」。恢复：仅 interrupted 可回到 queued。证据 fm27lab/application/experiments.py:301-333。
- CLI 与常见 HTTP 客户端的单次请求超时约 30 秒，而 start 会一直执行到批次结束；长批次应改用直接 HTTP 调用或轮询，CLI start 超时后服务端仍在继续执行。证据 fm27lab/client.py:16。

当前实现边界

- 引擎解析顺序为注入 EnginePort、settings.engine_root 非空的惰性原生宿主、MissingEngine 占位；未配置 engine_root 时 POST /api/experiments/start 返回 503 engine_unavailable，消息为「原生引擎未配置」。惰性宿主在首次能力协商或启动批次时构造，并在派发前按任务并行数配置分道。证据 fm27lab/interfaces/http/app.py:102、126-149、fm27lab/adapters/engine_native/lazy.py:22-71、fm27lab/sidecar.py:28。
- 引擎宿主真实要求：可执行文件默认位于引擎工作区 fm27_native/FM27Simulator.exe，单批超时 190 秒，重试 1 次。证据 fm27lab/adapters/engine_native/host.py:231-330。

## 7. CLI

入口

- 安装后命令为 fm27lab，也可以用 python -m fm27lab；控制台入口定义于 pyproject.toml 的 project.scripts。证据 pyproject.toml、fm27lab/__main__.py。
- 全局只有 --data-dir 一个选项，且必须写在子命令之前；数据目录缺省时读 FM27LAB_DATA 或平台默认路径。证据 fm27lab/cli.py:47-57。
- 版本命令输出版本号与接口版本，形如 2.0.0.dev0 fm27lab/v2。证据 fm27lab/cli.py:60-63。

命令组

| 命令组 | 子命令 |
| --- | --- |
| version | 无子命令 |
| serve | 启动 sidecar |
| mcp | 以 stdio 启动 MCP 服务 |
| pools | list、get、create、delete |
| drafts | list、get、create、update、delete、attributes、export-fmf、import-fmf、apply-roster、undo-roster |
| jobs | list、get、create、update、cancel、delete、runs、summary、batch-action、batch-delete、export、pool-summary |
| saves | list、get、create、update、delete、import、import-file、squad |
| artifacts | list、get、content、create、delete |
| settings | list、get、put、delete |
| concurrency | check |
| experiments | submit、start、cancel、resume |
| catalog | show |
| results | compare |
| system | resources |

证据 fm27lab/cli.py:34-44、fm27lab/cli.py:236-931。

关键选项

- pools list 与 drafts list 的 limit 默认 128、上限 128；jobs、saves、artifacts 的 list 默认 50、上限 256；jobs runs 默认 50、上限 200。证据 fm27lab/cli.py:221-232。
- drafts attributes 需要 --side、--scope、--operation、--params，可选 --player-index；参数细节见 9.1。
- drafts apply-roster 需要 --save-id、--club-uid、--side、--scope。
- experiments submit 缺省资源参数时会先 GET /api/system/resources 探测宿主资源。证据 fm27lab/cli.py:806-836。
- results compare 是唯一使用两空格缩进输出的命令，其余命令输出紧凑 JSON。

输出与退出码

- 普通输出为单行紧凑 JSON；删除类命令输出 {"deleted":true}；下载类命令写文件后输出 path 与 bytes。证据 fm27lab/cli.py:151-152、fm27lab/cli.py:178-196、fm27lab/cli.py:206-218。
- 退出码 0 表示成功；1 表示接口或发现文件错误并输出 code: message 到标准错误；2 表示命令行用法错误。证据 fm27lab/cli.py:143-148。

示例

```bash
python -m fm27lab --data-dir /absolute/path/data version
python -m fm27lab --data-dir /absolute/path/data drafts list
python -m fm27lab --data-dir /absolute/path/data jobs runs <job_id> --limit 50
```

## 8. MCP

### 8.1 传输与生命周期

- 传输为 stdio，命令为 python -m fm27lab mcp；服务名固定为 fm27lab。证据 fm27lab/cli.py:90-140、fm27lab/cli.py:111-118。
- 启动时读取数据目录、加载发现文件并探测 GET /api/health；失败时向标准错误输出「无法启动 MCP 服务：code: message」并以 1 退出。不自动拉起 sidecar。证据 fm27lab/cli.py:121-140。
- 协议版本固定为 2024-11-05，无版本协商分支。证据 fm27lab/interfaces/mcp/protocol.py:8。
- 支持方法：initialize、tools/list、tools/call、resources/list、resources/read、prompts/list、prompts/get。initialize 返回 capabilities，其中 tools、resources、prompts 各为 {"listChanged": false}，serverInfo 含 name 与 version。证据 fm27lab/interfaces/mcp/protocol.py:198-225。

### 8.2 工具

- 工具总数为 49，名称与参数由 fm27lab/interfaces/mcp/tools.py 定义，运行时与 4.6 表一致。
- 命名差异：saves_import_payload 的 MCP 名为 saves_import，saves_import 的 MCP 名为 saves_import_file。
- jobs_summary 与 system_resources 没有 MCP 工具；需要汇总时调用 jobs_runs 自行统计，系统资源通过 HTTP 或 CLI 获取。
- 工具入参接受 JSON 对象；返回封套为 content 数组内单个 text 项、structuredContent 为原始结果、isError 为 false。执行失败时 isError 为 true，structuredContent 为 error 对象，code 为 tool_error。证据 fm27lab/interfaces/mcp/protocol.py:333-370。

### 8.3 资源

4 个静态资源，无资源模板

| URI | 内容 |
| --- | --- |
| fm27lab://drafts | 草案列表，等价 drafts list，limit 128 |
| fm27lab://pools | 池条目列表，等价 pools list，limit 128 |
| fm27lab://jobs | 任务列表，等价 jobs list，limit 256 |
| fm27lab://saves | 存档列表，等价 saves list，limit 256 |

证据 fm27lab/interfaces/mcp/resources.py。

### 8.4 Prompts

| 名称 | 参数 |
| --- | --- |
| experiment-design | draft_id 必填、instruction 必填、baseline_draft_id 可选、seeds 可选 |
| pool-review | job_id 必填、focus 可选 |

证据 fm27lab/interfaces/mcp/prompts.py。

### 8.5 进度与取消

- 当前 MCP 服务不发送 notifications/progress、notifications/cancelled 或 logging 消息，也没有 notifications/message。长任务需轮询 jobs_get、jobs_runs 或 HTTP SSE。
- 取消通过 jobs_cancel 或 experiments_cancel 工具发起，不在协议层取消。

### 8.6 客户端配置示例

客户端直接以 Python 进程方式启动 MCP，环境变量提供数据目录

```json
{
  "mcpServers": {
    "fm27lab": {
      "command": "python",
      "args": ["-m", "fm27lab", "mcp"],
      "env": {
        "FM27LAB_DATA": "/absolute/path/data"
      }
    }
  }
}
```

- mcp 子命令本身没有 --data-dir 选项，但全局选项可以放在子命令之前：客户端不支持 env 时，把 args 写成 ["-m", "fm27lab", "--data-dir", "/absolute/path/data", "mcp"] 即可指定数据目录。证据 fm27lab/cli.py:47-57、fm27lab/cli.py:90-93。
- 桌面壳运行期间会自动写入发现文件；若 MCP 与桌面壳共享同一数据目录，可直接读取。

## 9. 工作流

### 9.1 草案与属性编辑

- 创建草案：POST /api/drafts 或 drafts create，body 为 name 与 scenario；scenario 归一化失败返回 400 validation_failed。
- 属性编辑：POST /api/drafts/{draft_id}/attributes，输入 side、scope、operation、params、player_index。side 取 home 或 away；scope 取 all、starters、player、squad。证据 fm27lab/application/draft_attributes.py:18-20。
- operation 取 bulk、position、copy、pair_feet、undo，参数约束：bulk 需 value，可选 groups 与 include_personality；position 需 position 与 value；copy 接受 source_uid 或 source_index 及可选 groups、copy_personality；pair_feet 需 left_index、right_index、preferred、preferred_value、weaker_value；undo 不接受参数。证据 fm27lab/application/draft_attributes.py:23 起。
- 显示值按 1 到 20 输入，内部按 5 倍换算；位置熟练度单独使用 position 操作，取值 0 到 20。证据 fm27lab/domain/attributes.py:165-183、fm27lab/domain/attributes.py:245-267。
- 输出 draft、snapshot、changed_players；快照存于草案 source 的 attribute_snapshot 键，可用 undo 回退。

### 9.2 实验与结果对比

1. 创建草案并确认场景合法。
2. 提交实验：experiments submit 或 POST /api/experiments，必填 seeds 与 draft_id；需要 A/B 时提供 baseline_draft_id。
3. 启动：experiments start 或 POST /api/experiments/start；该调用同步执行到批次结束。
4. 轮询：jobs get 查看 status 与 completed，jobs runs 分页读取逐场结果。
5. 汇总：jobs summary 取 metrics 与 paired。
6. 对比：results compare 传 baseline 与候选任务，读取 paired 差值；池任务先看 comparable。
7. 导出：jobs export 得到 CSV，列定义见 5.5。

### 9.3 阵容同步

1. saves import-file 登记存档文件并读取，得到 save_id。
2. saves squad 读取指定俱乐部的名单。
3. drafts apply-roster 将存档名单写入草案，scope 取 starters、bench、both，side 取 home 或 away。证据 fm27lab/application/save_import.py:23、fm27lab/application/save_import.py:124-178。
4. drafts undo-roster 从 roster_snapshot 回退；无快照时报「没有可撤销的阵容同步」。证据 fm27lab/application/save_import.py:184-201。

### 9.4 客队战术池

- 池配置写在草案场景的 away_tactic_pool 内；提交实验时按种子逐场抽签并写入每场场景。
- 运行后 jobs pool-summary 查看条目、权重、概率与抽签分布。
- 多任务对比时，抽签不一致会导致 comparable 为 false，应先确认种子与模式一致。

### 9.5 战术文件往返

- 导出：drafts export-fmf，下载文件名为草案名加 .fmf 后缀。
- 导入：drafts import-fmf，name 长度 1 到 80，内容为 base64，解码后不超过 4 MiB。证据 fm27lab/interfaces/http/routes/fmf.py:19-20。

## 10. 安全与隐私

- 监听地址限定回环，token 为任意非空 ASCII 字符串（缺省时生成 64 位十六进制），发现文件权限 0600，Windows 上收紧 ACL。
- 鉴权只接受 Bearer；不写 Cookie，不使用浏览器会话。
- CORS 仅允许桌面壳来源与开发端口；不携带凭据。
- 产物文件名做清理，禁止 . 与 .. 路径段；产物内容上限 16 MiB，战术文件上限 4 MiB。
- 存档读取为只读复制，不修改源文件。
- 日志只记录 sidecar 标准错误，不输出 token；桌面壳写入的日志文件位于数据目录 logs。
- 边界：缺少 Host 校验与多用户隔离，同一台机器的其他进程若取得 token 即可调用全部接口；token 不应写入共享脚本或版本库。

## 11. 性能与预算

| 项目 | 数值 | 证据 |
| --- | --- | --- |
| 并行 worker 上限 | 256 | fm27lab/domain/concurrency.py |
| 单次提交种子上限 | 10000 | fm27lab/interfaces/http/routes/experiments.py:14（MAX_SEEDS） |
| 单批总场数上限 | 10000 | fm27lab/application/experiments.py:20 |
| 每 worker 内存预算 | 1 GiB | fm27lab/domain/concurrency.py |
| 内存保留 | 2 GiB | fm27lab/domain/concurrency.py |
| 每 worker 磁盘预算 | 1 GiB | fm27lab/domain/concurrency.py |
| 引擎单批超时 | 190 秒 | fm27lab/adapters/engine_native/host.py:231-330 |
| 引擎重试次数 | 1 | fm27lab/adapters/engine_native/host.py:231-330 |
| SSE 历史保留 | 256 条 | fm27lab/application/events.py |
| SSE 心跳间隔 | 15 秒 | fm27lab/application/events.py |
| CLI 与 HTTP 客户端超时 | 30 秒 | fm27lab/client.py:16 |
| 启动超时 | 30 秒 | src-tauri/src/lib.rs:24-27 |
| 关闭等待 | 10 秒 | src-tauri/src/lib.rs:24-27 |

推荐并行数取中央处理器核数与内存可支撑并行数中的较小值，上限 256；低于需求时报 insufficient_memory 或 insufficient_disk，除非显式允许超配。

## 12. 兼容与版本

| 项目 | 当前值 | 证据 |
| --- | --- | --- |
| 包版本 | 2.0.0.dev0 | fm27lab/__init__.py:3 |
| 接口版本 | fm27lab/v2 | fm27lab/__init__.py:4 |
| 发现文件 schema | 1 | fm27lab/sidecar.py:19-30 |
| Python | 3.12 | pyproject.toml |
| 存档读取库 | fmsave 0.9.0 | pyproject.toml |
| MCP 协议 | 2024-11-05 | fm27lab/interfaces/mcp/protocol.py:8 |
| 桌面壳 | Tauri 2 | src-tauri/tauri.conf.json |

- GET /api/version 返回 api、version、capabilities 与 limits；capabilities 当前为空数组，limits 为 max_workers 256 与 max_seeds 10000。证据 fm27lab/interfaces/http/routes/system.py:55-62。
- 兼容策略：破坏性变更提升 API_VERSION 与发现文件 api 字段；客户端应先比较 api 字段再调用。

## 13. 验收要点

1. GET /api/health 返回 200 且 database 为 ready；带错误 Origin 返回 403 forbidden_origin。
2. 未带 token 访问业务端点返回 401 unauthorized；错误 token 返回 invalid bearer token。
3. GET /api/agent/v1/manifest 返回 404 not_found，证明旧命名空间已不存在。
4. 发现文件包含 schema、api、url、port、token、pid、data_dir、engine_root、created_at 九个业务字段，无 game_root、versions、capabilities、limits。
5. CLI 版本命令输出 2.0.0.dev0 fm27lab/v2；不带 --data-dir 时读取 FM27LAB_DATA 或平台默认目录。
6. MCP 初始化返回协议 2024-11-05 与 49 个工具；资源为 4 个静态 URI。
7. 任务生命周期覆盖 queued、running、completed 与 cancelled；非法流转返回 409 invalid_transition。
8. CSV 列顺序与 5.5 一致。
9. POST /api/shutdown 返回 202，进程退出后发现文件被删除。

## 14. 当前实现边界

- 引擎可执行文件缺失时 experiments start 返回 503 engine_unavailable；Linux 本机无 FM27Simulator，端到端实验需 Windows 引擎宿主，配置 engine_root 后不会在 create_app 阶段启动子进程。
- 数据目录 exports 子目录只在初始化时创建，当前没有写入使用方。
- 池条目库与实验解耦，实验只读草案内嵌 away_tactic_pool。
- CLI 无超时选项；批次超过 30 秒时 CLI start 会本地超时，服务端继续执行。
- MCP 无进度与取消通知，只能轮询。
- 历史设计中的 Agent 命名空间、Cookie 会话、Host 白名单、manifest、schemas、defaults、logs、phase-plan、selection、repair 等端点均不存在，不应再按旧文档实现。

## 15. 风险与待评审

| 风险 | 说明 |
| --- | --- |
| 引擎可执行文件缺失 | 配置 engine_root 但其中没有可用的 FM27Simulator 时 start 返回 503；Linux 本机无该二进制，端到端实验需 Windows 宿主 |
| 单请求同步执行 | start 在请求线程内跑完整批，长批次受客户端超时影响，且无进度推送 |
| 幂等记录清理 | 幂等记录持久化在 SQLite 的 idempotency 表，主键唯一并对 request_hash 校验载荷，跨重启有效且同一数据库的多进程共享；进程内 asyncio.Lock 只串行单进程内同键请求。当前没有定时调用 prune，记录会随不同键累积。证据 fm27lab/interfaces/http/app.py:148、fm27lab/adapters/storage_sqlite/idempotency.py:35-81。 |
| 发现文件竞争 | 手工启动与桌面壳共用数据目录时相互覆盖发现文件，需保证同一时刻只有一个 sidecar |
| 无 Host 校验 | 依赖回环与 token，token 泄露风险需由宿主权限控制兜底 |
| 池条目库未参与实验 | 条目库仅做 CRUD，实验使用草案内嵌配置，两者易被误认为同一数据源 |

