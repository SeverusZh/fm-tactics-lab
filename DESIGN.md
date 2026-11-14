# FM Tactics Lab 重构设计

## 状态

设计基线，适用于 `refactor/v2-modular` 分支。技术栈由仓库维护者选定为 Tauri 2 + Rust + TypeScript + Python sidecar。实现按 TDD 推进，每个切片必须通过独立审核后才能结束。

## 目标

- 删除“存档对战”，把存档读取收敛到唯一的“存档战术库”入口。
- 把战术、球员、定位球、模拟、存档、结果、并发、存储与接口拆成可独立运行和测试的模块。
- 所有能力同时具备 HTTP、CLI 与 MCP 入口，三者共享同一份命令定义。
- 使用 SQLite 重建持久化，空库启动；旧目录保留为只读归档。
- 统一比赛名单为 23 人，不再提供 26 人分支。
- 移植上游 v1112 的原生 worker 复用与 1–256 路并行。
- 实现 Issue #5、#6、#7 与 PR #10 中尚未完成的功能。
- 以 FM 固有紫色体系重建现代、简洁、可访问的界面。

## 非目标

- 不重新实现 FM27 比赛引擎，不提取或再分发游戏资源。
- 不提供远程、多租户或公网访问。
- 不保留旧文件存储写入路径，不做旧数据自动迁移。
- 不保留“存档对战”的 UI、HTTP、CLI 或 MCP 兼容入口。
- 不在本轮实现 26 人名单、同进程多线程模拟或云同步。

## 约束

- Windows x64；FM27 参考构建 27.0.1+2494687；原生适配器继续执行兼容门禁。
- Python 3.12 作为 sidecar 运行时；玩家不需要安装 Python、Node 或 Rust。
- Tauri 2 使用 Windows WebView2；安装包必须包含 sidecar 与原生宿主。
- HTTP 仅 loopback；HTTP 写操作需要 Bearer token 与 Origin/CORS 校验；CLI/MCP 使用同一 token；业务写操作支持幂等键，系统路由按需。
- 无桌面模式：`fm27lab serve` 可在没有 Tauri 时独立运行；未提供 token 时自行生成并写 endpoint.json。CLI/MCP 默认读取 endpoint；缺失时可显式 `--launch` 启动 sidecar。
- 鉴权规则：无 Origin 的本地请求只校验 token；带 Origin 的浏览器请求必须命中 CORS allowlist。开发模式额外允许 `http://localhost:1420`，生产模式只允许 Tauri origin。
- 系统路由：`/api/health`、`/api/version`、`/api/openapi.json` 与 `/api/docs` 免鉴权；`/api/shutdown` 与 `/api/events` 需要 token，不参与业务命令注册表，但必须在契约测试中覆盖。
- 23 人名单是唯一合法比赛名单；26 人存档名单在读取时截断并明确提示。
- 不提交存档、游戏 DLL、私钥、本机路径或凭据。

## 目标架构

```text
Windows x64
┌──────────────────────────────────────────────────────────────┐
│ Tauri 2 shell · Rust                                         │
│ 窗口 / 单实例 / 文件对话框 / sidecar 监督（托盘/更新 Phase 4） │
│        │ Tauri command get_connection()：只返回 URL 与 token │
│        ▼                                                     │
│ React 19 + TypeScript + Vite · WebView2                      │
│ 战术板 / 球员 / 存档战术库 / 实验 / 结果 / 设置              │
│        │ loopback HTTP + Bearer token                        │
│        ▼                                                     │
│ Python 3.12 sidecar · fm27lab                                │
│ domain · application · ports · adapters · interfaces         │
│ HTTP/OpenAPI · SSE · CLI · MCP · SQLite                      │
│        │ 子进程与文件协议                                     │
│        ▼                                                     │
│ FM27Simulator.exe · C++17 → 本机 FM27 引擎 DLL               │
└──────────────────────────────────────────────────────────────┘
```

Rust 不持有足球领域逻辑，不直接读写 SQLite。Python sidecar 是领域、引擎、存储、CLI 与 MCP 的唯一所有者。前端只通过带 token 的 loopback API 访问 sidecar，不经过 Rust 代理。

Phase 0 的桌面壳覆盖窗口、单实例、sidecar 启动/健康检查/退避重启/退出清理与连接信息注入；文件对话框、打开数据目录、外部链接、托盘与自动更新在 Phase 4 接入，不以当前分支的 `cargo check` 作为完成证据。

sidecar supervisor 在 ready 行后轮询 `/api/health`，失败或进程退出时按 500/1000/2000ms 退避重启，最多 3 次；重启前清空旧连接并发送 `sidecar-down`/`sidecar-ready`/`sidecar-error`/`sidecar-failed` Tauri events；应用退出时调用 `/api/shutdown`，随后 kill child。

## 桌面接入契约

- React 只调用 sidecar 的 loopback HTTP；Rust 不转发、不改写 API 请求，避免形成第二个 API owner。
- Rust 生成 32 字节随机 token，通过环境变量 `FM27LAB_TOKEN` 传给 sidecar；sidecar 原子写入 `<data>/agent/endpoint.json`，权限收紧到当前用户。
- React 通过 Tauri command `get_connection` 获取 `{url, token, api}`；不直接读取文件，不把 token 写入 localStorage 或日志。
- sidecar 只绑定 `127.0.0.1:0`；启动完成后向 stdout 输出一行 `{"event":"ready","port":...}`，同时写入 endpoint.json。
- Rust 读取 ready 行，轮询 `GET /api/health` 直到成功；健康检查失败或进程退出时按指数退避重启，最多 3 次，并通过 Tauri event 通知前端。
- 正常退出时 Rust 调用 `POST /api/shutdown`，等待 10 秒；超时后终止进程。sidecar 退出时删除 endpoint.json。
- 生产模式 CORS 只允许 `tauri://localhost` 与 `http://tauri.localhost`；开发模式额外允许 `http://localhost:1420`。不使用 cookie，统一使用 Bearer token。
- CLI 与 MCP 读取 endpoint.json 与 token；MCP stdio 不暴露 HTTP 鉴权细节，只把 token 用于内部 loopback 请求。

## 所有权与依赖规则

- `domain` 只包含纯函数、数据模型与校验，不导入任何适配器或接口。
- `application` 编排用例，依赖 `domain` 与 `ports`，不导入具体适配器；存档读取通过 `SaveReaderPort`，FMF 通过 `FmfPort`。
- `ports` 定义引擎、存储、时钟、事件发布等协议。
- `adapters` 实现 `ports`，包括 native、fmsave、SQLite、FMF、locale。
- `interfaces` 只做协议转换与鉴权，调用 `application`。
- 组合根 `bootstrap.py` 是唯一允许同时导入适配器与应用服务的位置。
- 模块之间禁止通过模块级可变全局状态通信；依赖通过构造函数注入。
- 每个模块拥有独立测试文件；测试不启动完整桌面应用。

## 模块清单

```text
fm27lab/
  domain/
    scenario.py        场景 schema、归一化、校验、修复
    catalog.py         角色、位置、指令、属性目录
    tactics.py         双阶段战术、职责、个人指令
    setpieces.py       定位球模型与编码
    pool.py            客队战术池、抽签、轮战、名单
    results.py         指标、配对差值、分布、CSV
    roster.py          23 人名单策略与重映射
  application/
    experiments.py     提交、排队、取消、续跑
    library.py         存档读取、联赛、教练预设、真实战术
    drafts.py          Agent 草案
    jobs.py            任务查询与批量管理
    results.py         汇总、对比、导出
    engine.py          引擎选择与兼容状态
    settings.py        设置与并发建议
  ports/
    engine.py          EnginePort
    save_reader.py     SaveReaderPort
    fmf.py             FmfPort
    repositories.py    JobRepository、DraftRepository、PoolRepository、
                       SettingsRepository、ArtifactRepository、SaveRepository
    idempotency.py     IdempotencyStore
    events.py          EventPublisher
  adapters/
    engine_native/     原生宿主、二进制编码、counted-session
    save_fmsave/       fmsave 读取、教练与生成输入
    storage_sqlite/    连接、迁移、仓储实现
    fmf/               FMF 导入导出与回读校验
    locale/            中英文
  interfaces/
    http/              FastAPI 路由、鉴权、SSE、错误封套
    cli/               Typer 命令
    mcp/               MCP stdio 服务
  registry.py          命令注册表
  bootstrap.py         组合根
web/                   React 19 + TypeScript + Vite
rust/                  纯 Rust 契约与 sidecar 监督核心，可独立 cargo test
src-tauri/             Tauri 2 桌面壳与系统集成
native/                C++17 适配器
```

## 接口契约

- HTTP 使用 FastAPI，OpenAPI 3.1 位于 `/api/openapi.json`，本地文档位于 `/api/docs`。
- 错误统一为 `{"error":{"code","message","details","retriable","retry_after_seconds"}}`。
- 列表统一支持 `limit`、`offset`，返回 `items`、`total`、`next_offset`。
- 写操作支持 `Idempotency-Key`；同键同载荷返回首次响应，同键异载荷返回 409。
- 长任务通过 `GET /api/events` 的 SSE 推送进度；React 使用 fetch 流式读取并携带 `Authorization: Bearer`、`Accept: text/event-stream` 与 `Last-Event-ID`，不使用 EventSource 或 URL token；CORS preflight 允许 `Authorization` 与 `Last-Event-ID`。服务端先发送 ready 事件并支持按 `Last-Event-ID` 重放，客户端仅在重连时携带最后事件 id，断开后按 1s 起、30s 封顶的指数退避重连；事件驱动的查询失效按 300ms 窗口合并，页面保留手动刷新作为降级路径，未实现自动轮询。
- `registry.py` 声明每个能力的名称、HTTP 方法与路径、CLI 命令路径与 MCP 工具名；三入口适配层当前手写并保持薄，`fm27lab/tests/test_registry_contract.py` 校验 OpenAPI 业务操作、CLI 叶子命令与 MCP 工具名同注册表一致，并检测名称、方法与路径约定漂移。输入/输出模型尚未纳入注册表。
- 业务路由只允许在 `fm27lab/interfaces/http/routes/` 的模块中声明并登记到 `registry.py`；除 `/api/health`、`/api/version`、`/api/openapi.json`、`/api/docs`、静态资源与显式系统路由 `/api/shutdown`、`/api/events` 外，不得在其他位置新增业务路由。
- 契约测试验证每个能力在 HTTP、CLI、MCP 三个入口都存在，并校验 OpenAPI 操作、CLI 命令与 MCP 工具名一致；输入/输出 schema 快照尚未建立。
- MCP 提供 tools、resources、prompts，并保留 stdio 传输。

## 存储

- 单一 SQLite 文件 `<data>/fm27lab.db`，WAL、`foreign_keys=ON`、`busy_timeout=5000`。
- 迁移文件位于 `fm27lab/adapters/storage_sqlite/migrations/`，由 `schema_migrations` 记录版本。
- 主要表：`settings`、`saves`、`save_leagues`、`save_clubs`、`jobs`、`job_runs`、`drafts`、`pool_entries`、`idempotency`、`artifacts`。
- 场景、战术与名单以 JSON 文档存储；任务状态、比分、统计与索引列正常化，便于查询与聚合。
- 空库启动。旧 `runs/`、`save_library/`、`agent/drafts/` 保留但不读取、不写入、不迁移；用户可在文件管理器中自行查阅。
- 每个请求使用独立连接；写事务使用 `BEGIN IMMEDIATE`；逐场进度按批提交，减少 fsync。
- 不引入 ORM；仓储层使用参数化 SQL 与显式行映射。

## 并发

- 采用上游 v1112 的 counted-session 协议：宿主按自身能力声明可复用场数，逐场释放比赛对象并清理执行力上下文。
- 并行数 1–256 始终是合法输入；CPU 与可用内存只决定推荐值。高于推荐值只产生警告。可用内存低于 2 GiB 或磁盘不足时提交默认返回 409，可由 `allow_oversubscription=true` 显式覆盖；超过 256 属于范围错误。
- 单一批次队列串行执行，批次内按 worker 分道；排队位置、取消、续跑与失败明细可见。
- 高于推荐值显示非阻塞资源警告；高于 8 路的收益不做保证。
- 每场保留原生校验、超时、取消与磁盘空间检查；失败保留现场，不自动重跑。
- 资源预检：按每路 1 GiB 加 2 GiB 保留估算；高于推荐值时显示非阻塞警告。只有可用内存低于 2 GiB、磁盘不足或并行数超过 256 时返回 409；前两者可由 `allow_oversubscription=true` 覆盖。UI 对 256 路要求二次确认，CLI/MCP 暴露同名参数。
- 旧宿主缺少 counted-session 能力时回退到每会话 64 场；执行力实验回退到隔离模式。回退路径必须记录在任务 provenance 中。
- 验收矩阵：1、8、256 路各验证提交、取消、续跑与结果身份一致；256 路的真实耗时与内存只在 Windows 真机记录，不作为 Linux 单测断言。
- 性能目标：同一输入与种子下结果一致；并发提升不改变比分、统计与执行力回执。

## 23 人名单规则

- `MATCH_ROSTER_SIZE = 23` 是唯一合法值；所有来源先归一化到 23 人。
- 首发 11 人优先保留来源 selection 的 slot 顺序；缺失时按位置覆盖顺序、ability 降序、source_uid 升序补齐。
- 必须保留至少 1 名门将；有第二名门将时优先进入替补；0 名门将时返回 `roster_missing_goalkeeper`。
- 替补 12 人优先保留来源 substitute 顺序；不足时按位置覆盖顺序补齐，再按 ability 降序、source_uid 升序。
- 截断后按 source_uid 过滤并重映射队长、主罚与定位球优先级；被移除的引用不得保留。队长被移除时取第一位非 generated 的首发；若全部为 generated，队长留空。
- 不足 23 人时使用标记为 `generated=true` 的中性占位球员补齐，并在 UI 明确提示；占位球员不担任队长或第一主罚。
- 所有排序键必须稳定；同一输入必须得到同一 23 人集合与同一重映射结果。完整规则见 ADR-0005。

## UI/UX

- 深炭紫底、FM 紫主操作色、球场绿数据强调、琥珀警告、红色危险。
- 左侧固定导航，图标加文字；每屏一个主操作；页面可深链。
- 页面：战术板、球员属性、存档战术库、实验、实验结果、设置与说明。
- 战术板支持双阶段、拖拽与键盘换位；球员页支持隐藏属性分组；存档页支持唯一存档导入、联赛战术库、真实 AI 生成与我的球队同步；结果页支持多选批量管理、对比与可折叠战术池卡片；实验页以草案为输入，提交时自动探测主机资源并做并发预检，可启动批次并跳转结果。
- 所有数据视图提供空、加载、错误、成功状态；键盘、焦点、对比度与减少动画遵循设计系统。
- React 只保存临时 UI 状态；业务数据、草稿、设置与历史一律通过 API 写入 SQLite，不使用 localStorage 或 IndexedDB 作为第二持久化 owner。
- OpenAPI 生成 TypeScript 类型与请求客户端；前端不得手写重复的请求/响应类型。
- 详细视觉与组件规则见 [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md)。

## 兼容与打包

- Tauri 安装包包含：Rust 壳、WebView2 前端资源、Python sidecar、原生宿主与私有引擎输入。
- Python sidecar 使用 PyInstaller onedir 构建到 `sidecar-dist/fm27lab-sidecar`，独立可运行；`scripts/build_sidecar.py` 负责构建，`tauri.conf.json` 的 `bundle.resources` 将其复制到 `resource/sidecar/`。
- `beforeBuildCommand` 先构建前端再构建 sidecar；Windows CI 执行 sidecar 打包、Python 测试、`cargo build`、Tauri 安装包构建与 `cargo test`。`src-tauri/Cargo.lock` 必须提交以固定依赖。
- Tauri 只负责启动、健康检查、重启与退出；若 sidecar 构建失败，安装包构建失败，不生成缺少后端的发布包。
- sidecar 通过环境变量接收数据目录、引擎目录、端口与 token；token 只保存在内存与受保护文件。
- 保留 `fm27lab serve`、`fm27lab mcp` 与 CLI 独立入口，便于无桌面环境测试与 Agent 接入。
- Windows 真实引擎验证不在 Linux 开发环境内完成；作为发布门槛记录在 TODO。

## 测试与审核

- TDD Route: strict。每个行为先写失败测试，再写最小实现。
- Python 使用 pytest；前端使用 Vitest 与 React Testing Library；Rust 核心模块使用 cargo test。Playwright 主流程与可访问性检查为待补项。
- 契约测试覆盖 OpenAPI、CLI 帮助、MCP 工具 schema、三入口能力对齐，以及由 OpenAPI 生成的 TypeScript 类型快照。
- 集成测试使用 fake engine；真实原生比赛测试需要 Windows + FM27，作为发布前人工/CI 门槛。
- 每个切片由独立审核子代理只读审查，给出 findings 与明确 PASS/FAIL；未通过不得进入下一阶段。
- 审核记录维护在 [docs/REVIEWS.md](docs/REVIEWS.md)。

## 交付阶段

1. Phase 0：合并上游 v1112，建立文档、ADR、工具链与审核流程。
2. Phase 0.5：删除存档对战与 `career_*`，给出 `library_*` 映射，清理旧文档、测试与 schema 快照。
3. Phase 1：领域模块与严格 TDD 测试。
4. Phase 2：SQLite、引擎适配器与并发调度。
5. Phase 3：HTTP、SSE、CLI、MCP 统一命令层。
6. Phase 4：Tauri 壳、sidecar 监督与打包。
7. Phase 5：React UI 与设计系统。
8. Phase 6：Issue #5/#6/#7 与 PR #10 未完成项。
9. Phase 7：集成、性能、发布文档与最终审核。

## ADR 索引

- [ADR-0001](docs/adr/0001-tauri2-shell-python-sidecar.md)：Tauri 2 壳与 Python sidecar 边界。
- [ADR-0002](docs/adr/0002-sqlite-empty-database.md)：SQLite 空库与旧数据只读归档。
- [ADR-0003](docs/adr/0003-module-boundaries.md)：模块化单体与命令注册表。
- [ADR-0004](docs/adr/0004-native-concurrency.md)：原生 counted-session 与 1–256 并行。
- [ADR-0005](docs/adr/0005-uniform-23-roster.md)：统一 23 人比赛名单。
- [ADR-0006](docs/adr/0006-remove-career-match.md)：删除存档对战，收敛存档入口。
