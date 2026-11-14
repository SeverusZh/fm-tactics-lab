# Changelog

## v2.0.0 · 未发布

本版本正在 `refactor/v2-modular` 分支开发，尚未发布，也不存在可下载构建。计划范围与验收状态以 [TODO.md](TODO.md) 为准；在功能落地并通过独立审核前，本节不列完成项。

已合入本分支、但尚未发布的基线能力：

- 删除旧“存档对战”模式：UI、`career_*` HTTP/CLI/MCP/schema、`draft_create source=save` 与旧文档段落已移除；保留存档战术库、通用比赛名单选择、FMF 与自由推演。该退役已通过独立审核。
- 新增纯领域客队战术池选择模块：加权抽签、轮战顺序、同种子 A/B 共享、完成计数与 summary；已通过独立审核。
- 新增真实名单应用：强制 23 人、保留 host native_id、按 source_uid 重映射队长/主罚/定位球，并拒绝 generated/非法 UID/名单；已通过独立审核。
- 新增纯领域结果指标：主客视角胜平负、Wilson 区间、进失球、xG/xGA、控球、射门、传球成功率与同种子配对净胜球差；已通过独立审核。
- 新增 scenario 23 人归一化：两队截断/补齐、source_uid 引用重映射、roster_trim、球员深拷贝；已通过独立审核。
- 新增 catalog 快照与双阶段战术校验：位置/角色/职责、`role_eligibility_context` 四桶资格、2×11、指令与盯防边界；已通过独立审核。
- 新增 SQLite 客队战术池仓储：JSON 战术/名册、事务读己之写、128 条原子上限、并发安全与稳定排序；已通过独立审核。
- 新增 sidecar `/api/pools` CRUD：Bearer/OpenAPI 契约、严格 body/query、分页、URL-safe id、409/204 与统一错误封套；已通过独立审核。
- 新增 drafts 仓储与 DraftService：scenario 23 人归一化、JSON/事务、原子更新、updated_at 排序与分页摘要；已通过独立审核。
- 新增 sidecar `/api/drafts` CRUD：严格 body、23 人归一化、分页、PATCH、CORS、OpenAPI 与错误封套；已通过独立审核。
- 新增 jobs/job_runs 仓储：状态/进度不变量、逐场 run、级联删除、事务与分页过滤；已通过独立审核。
- 新增 saves/save_leagues/save_clubs 仓储与 SavesService：存档状态机、UTC 时间规范化、子表原子导入与分页；已通过独立审核。
- 新增 artifacts 与 idempotency 仓储：产物元数据与外键置空、同键同载荷重放、同键异载荷冲突、并发原子写入；已通过独立审核。
- 新增 JobService 与 `/api/jobs`：任务状态机、取消、逐场 runs、分页信封、鉴权与 409/404 契约；已通过独立审核。
- 新增 ResultsService 与 ArtifactService：任务结果汇总与配对差值、逐场分页、确定性 CSV 导出，产物原子写入、路径穿越与符号链接防护；已通过独立审核。
- HTTP 路由拆分为 common 与 routes 模块并新增 `/api/saves`：存档 CRUD、状态流转、子表原子导入与分页，既有 pools/drafts/jobs 契约保持不变；已通过独立审核。
- 新增引擎能力协商与运行时计划：counted-session 复用、旧宿主 64 场回退、执行力实验隔离与 provenance，供后续原生适配器接线；已通过独立审核。
- 新增 1–256 并行校验、资源预检与实验串行调度：提交队列、启动、取消、续跑与缺失场次过滤；已通过独立审核。
- 新增 sidecar HTTP 客户端与 CLI 资源命令：endpoint 发现、Bearer 请求、pools/drafts/jobs/saves 命令与退出码；已通过独立审核。
- 新增 MCP stdio 协议层与 22 个工具面：JSON-RPC 错误码、工具 schema、参数校验与错误透传；已通过独立审核。
- 新增结果摘要、CSV 导出与产物下载接口：容器化下载校验、ETag 与分页；已通过独立审核。
- 新增前端结果页与存档战术库页：指标卡、逐场表格、CSV 下载、存档创建与导入；已通过独立审核。
- 新增 SSE 事件发布器与 `/api/events` 流：Last-Event-ID 重放、有界历史、心跳与断连清理；已通过独立审核。
- 新增 `/api/settings` 与并发预检接口：键值校验、深度与大小上限、resource_check 复用及 CORS PUT 预检；已通过独立审核。
- 新增 Idempotency-Key 中间件：2xx 快照重放、同键异载荷 409、在途去重与鉴权前置；已通过独立审核。
- 新增 `fm27lab mcp` stdio 命令：endpoint 发现、health 就绪探测、22 工具注册与纯协议 stdout；已通过独立审核。
- 新增任务批量操作接口：批量取消与删除、逐条失败明细与稳定顺序；已通过独立审核。
- 新增前端设置页：设置 CRUD、JSON 校验、并发预检面板与错误状态；已通过独立审核。
- 新增属性分组与批量编辑领域：可见/隐藏分组、half-up 换算、参考复制、左右脚配对与撤销快照；已通过独立审核。
- 新增 `DELETE /api/jobs` 原子批量删除与任务页多选管理：运行中保护、失败明细、可访问确认与焦点还原；已通过独立审核。
- 新增 `/api/jobs/{id}/pool-summary`：客队战术池模式、条目、名单来源与抽中次数；已通过独立审核。
- 新增原生引擎适配器：worker manifest 文件协议、逐场释放回执、无进展超时、只重试未完成场次、退出码 180 处理与取消清理；已通过独立审核。
- 新增实验调度 HTTP：提交、启动、取消、续跑与资源预检 409；已通过独立审核。
- 新增 MCP resources 与 prompts：四个资源读取与两个中文提示词，initialize 声明能力；已通过独立审核。
- 新增只读球员属性页：草稿选择、主客切换、六组属性与隐藏开关；已通过独立审核。
- 新增引擎并发分道：1–256 workers 按 legacy lanes 并行会话、回调互斥、取消全道与跨道失败隔离，1/4/8 路结果身份一致；已通过独立审核。
- 新增三入口契约注册表：51 项能力与 HTTP/Typer/MCP 双向对齐及漂移检测；已通过独立审核。
- 新增 `/api/catalog` 运行时目录：三处查找、字段裁剪与缺失降级；已通过独立审核。
- 新增只读双阶段战术板：11 槽位球场、阶段与主客切换、catalog 中文标签与降级提示；已通过独立审核。
- 新增存档读取端口与 fmsave 适配器：经理俱乐部、69 属性与左右脚、性格、首发与替补选择；已通过独立审核。
- 新增 FMF 战术编解码与导入导出接口：确定性字节格式、往返一致、损坏文件统一 400；已通过独立审核。
- 新增草稿属性批量编辑接口：批量/位置/复制/双脚配对/撤销，复用领域策略并持久化单步快照；已通过独立审核。
- 新增存档文件导入与阵容同步：fmsave 读取写入 SQLite、名单查询、首发/替补/全量同步与撤销，含 generated 占位保留与引用重映射；已通过独立审核。
- 新增 OpenAPI TypeScript 类型生成脚本与 `api-schema.ts`，测试锁定不漂移；已通过独立审核。
- 新增球员页属性批量编辑面板：分组多选、范围、复制、撤销与结果提示；已通过独立审核。
- 新增前端任务管理页与 jobs 类型客户端：状态筛选、分页、取消、删除、创建与错误态；已通过独立审核。
- 新增 CLI 全量命令：26 条命令覆盖产物、设置、并发、实验、目录与批量与下载，客户端补 PUT、二进制请求与布尔 query，退出码与 token 脱敏经审核。
- 新增 MCP 48 工具面：补齐 26 个工具与下载 base64 封套，严格 schema 与本地校验经审核。
- 新增存档库文件导入与阵容同步面板：文件导入与覆盖、经理俱乐部与名单、首发/替补/全量同步与撤销，经审核。
- 新增结果对比能力：跨任务同种子配对、bootstrap 置信区间、客队战术池一致性核对与不可比指标保留，HTTP/CLI/MCP 三入口及前端对比面板；已通过独立审核。
- 新增原生场景编码器与定位球领域：FM27CFG1 记录编码、绝对与相对差量、资源搜索与 defaults、定位球合法化与枚举；已通过独立审核。
- 新增客队战术池 schema 与整批展开：条目归一化、统一属性与真实名单、23 人裁剪、轮战一次抽签逐场展开；已通过独立审核。
- 新增结果页任务批量管理：状态筛选、全选、二次确认批量删除与失败原因、客队池卡片折叠状态会话内保留；已通过独立审核。
- 新增宿主资源探测：GET /api/system/resources 返回 CPU、可用内存、空闲磁盘与推荐并行数，CLI 提交实验时自动预填；已通过独立审核。
- 新增实验场景物化与执行接线：草案与客队战术池按种子展开为 FM27CFG1 场景、物化目录与 provenance、A/B 变体共用同一次抽签，提交持锁并在失败时清理任务与目录；已通过独立审核。
- 新增实验提交页面：草案与基线选择、种子解析、总场数上限、并行数与超分配、主机资源探测与自动并发预检、提交与启动、启动结果独立展示；已通过独立审核。
- 新增原生引擎生产接线：未配置引擎时保持空库可启动，配置 engine_root 后按需以双检锁构造原生宿主、按任务并行数在派发前配置宿主分道，运行时计划在启动时按能力协商；已通过独立审核。
- 新增前端 API 类型统一到生成的 OpenAPI schema：67 个类型中 40 项别名与 2 项派生改为生成接口，25 项保留手写并记录理由，前后端状态枚举按领域状态机收紧；已通过独立审核。
- 新增草案写入的双阶段战术校验：创建与更新按运行时目录校验位置、角色阶段、资格上下文、职责与 2×11 结构，目录缺失或不可解析时跳过，未配置目录保持既有行为；已通过独立审核。
- 新增战术板编辑：编辑模式与本地副本、拖拽与键盘交换首发、按阶段角色编辑、保存与放弃、未保存保护与无障碍播报；已通过独立审核。
- 新增球员页名单兼容提示：原始人数超 23 人裁剪、不足 23 人补足、裁剪后仍含占位三类逐字文案，占位球员在名单与详情显示标识；已通过独立审核。
- 新增安全与隐私检查：docs/SECURITY.md 逐条取证鉴权矩阵、令牌与 endpoint 权限、CORS、路径包含、输入上限、幂等与仓库隐私，新增 22 条边界测试，并修复数据目录 0755 可被同机用户读取的缺陷；已通过独立审核。
- 重写中英文 README：删除 v1 语义与旧截图引用，覆盖 v2 架构、CLI/MCP/HTTP 三入口、实验与结果流程、构建与测试、版本状态，数字与常量与代码逐条对齐；已通过独立审核。
- 新增前端服务端事件订阅：fetch 流解析 SSE 帧、Last-Event-ID 仅重连时携带、1 秒起 30 秒封顶指数退避、任务/实验/结果页事件到查询失效映射、断线提示与手动刷新降级；已通过独立审核。
- 新增事件刷新 300ms 尾沿合并：同窗口重复查询键只失效一次、卸载清理定时器，避免大批次逐场事件造成请求风暴；已通过独立审核。
- 新增页面错误边界：渲染失败按路由复位显示回退、重试按钮与无障碍角色，单页错误不影响导航；已通过独立审核。
- 新增性能基准脚本与文档：HTTP 只读路径、场景归一化与客队抽签展开、bootstrap 重抽样三类指标，quick 与 json 输出及复现方法；已通过独立审核。
- 修复跨平台测试与场景快照写出：场景与 provenance 按 UTF-8 字节写入避免 Windows 换行差异、实验与宿主夹具使用临时目录与可注入 sysconf、CLI 帮助断言不依赖富文本渲染；Linux 与 Windows CI 用例恢复一致；已通过独立审核。
- 新增旧场景 schema 兼容归一化：schema 4 的 phase_plans 在名单归一化与物化前升级为 schema 3 原生两阶段形状，按阶段名映射、阶段指令合并与中文字段校验，历史旧形状草案无需迁移即可物化；已通过独立审核。
- 新增并发通道对比基准：固定每场 2 秒的模拟器下实测 1、2、4 条通道的墙钟与加速比，输出 JSON 与中文表格、失败路径中文受控退出，方法与局限写入 docs/PERFORMANCE.md；脚本与测试按 UTF-8 输出，非 UTF-8 区域设置下中文表格与错误原因可读；已通过独立审核。
- 修复 Windows 安装包 sidecar 资源映射：Tauri 资源映射改用目录形式，保留 PyInstaller onedir 的 `_internal` 运行时与迁移目录，避免安装后 sidecar 无法启动并触发重启上限；CI 解包安装包校验载荷布局；已通过独立审核。
- 新增存档导入路径清洗：导入前去除首尾空白与成对 ASCII 引号，修复从资源管理器复制文件地址粘贴后被判“存档文件不存在”的常见失败；已通过独立审核。
- 新增桌面原生文件选择：接入 tauri-plugin-dialog 且仅授予 dialog:allow-open，存档与 FMF 导入可从资源管理器选择文件，浏览器与测试环境保留手动路径；已通过独立审核。
- 新增免存档 FMF 导入：POST /api/drafts/import-fmf-file 按路径读取 FMF 创建草案，限制 4 MiB、名称缺省取文件名并截断 80，CLI 增加 drafts import-fmf-file，前端存档库提供导入表单并在成功后跳转战术板；已通过独立审核。
- 修复战术页草稿参数恢复：清除 ?draft= 参数后手动改选草稿，再重新加入同一参数时仍会应用，未保存修改期间仍不抢占当前草稿；已通过独立审核。

- 上游 v1112 的原生 worker 复用、counted-session 协议与 1–256 并行输入已合并。
- 本地分支已有的客队战术池轮战/真实名单与 Agent 接入层保留在合并基线中；v2 的模块化改造会逐步替换其接口。

### 继承自 v1111.2 分支

- Add rotation and real-roster modes to the away tactic pool: rotation cycles every candidate for a configured number of rounds instead of drawing by weight, real-roster mode applies the saved club's current squad and attributes instead of uniform values, the run-bar checkbox becomes a single pool button that opens a bottom-right popup holding both draw modes and both squad sources, save-library rows gain an Overwrite home squad action, and the starting seed gains a random button; pool summaries, provenance and Agent results carry the mode, rounds and roster flags, while CSV keeps the per-match tactic entry columns.
- Add a local AI agent interface: /api/agent/v1 endpoints, fm27lab CLI, stdio MCP sidecar, file-backed drafts, endpoint discovery with token authentication, headless launcher mode, and cancellable save import and opponent scans.
- Improve the agent surface: compact JSON tool text, richer draft/job/results payloads, batch draft edits, draft clone, legal option lookup, inline scenario file paths, cross-job paired comparisons, queued free-run submissions with queue positions, and shorter job wait defaults.
- Unify run submission: the web UI and Agent interface share one start_run path; /api/run and /api/run-episodes keep the UI 409 behaviour while Agent submissions enter a real FIFO queue that executes one batch at a time in creation order; cancelling a queued run lands status cancelled immediately and resume uses the same serial gate.
- Add random away tactic pool support to the Agent layer: draft summaries and inline/draft/job/fmf sources preserve away_tactic_pool; one task draws each seed once so A/B variants face the same opponent tactic; results_summary reports per-entry draw counts, results_matches exposes the drawn tactic, CSV gains tactic_pool_entry_index and tactic_pool_entry_name, and results_compare returns comparable=false instead of pairing tasks whose draws differ.
- Fix the merged status contract: lab_status tolerates engine_compatibility with a string native profile, and MCP reloads endpoint.json and retries once after token rotation or an app restart; run submissions carry an idempotency key so the retry does not create duplicate jobs.
- Bump the server and agent contract version to 1111.2; extend the offline server queue tests, the pool mock and the Agent/MCP regression suite (210 tests).

## v1112 · 2026-11-12

- Keep each supported native worker alive until its assigned batch lane finishes instead of recycling after 64 matches. Release the original match, recording references, event observer and thread context after every match.
- Install execution trampolines once per process and reset policies, team bindings, CA receipts and counters for every match. Execution and random-pool A/B batches now reuse workers too.
- Negotiate the counted-session protocol by host identity; older hosts retain the previously verified 64-match/isolated-execution behavior. Keep per-match progress timeouts, cancellation and periodic disk-space checks.
- Let users enter 1–256 concurrent workers directly and preserve their choice. CPU and free-memory estimates only set the default recommendation (up to four); they do not cap manual choices. Counts above the recommendation display a nonblocking resource warning. Higher counts than eight have not been benchmarked.
- Validation: 160 matches in one process matched cold-worker scores, statistics and execution receipts; mixed execution transitions matched full events; three-preset execution A/B cancel/restart/resume passed. A fixed 48-match quick-mode trial took 51.687 / 34.859 / 26.468 seconds at 4 / 6 / 8 workers, with identical results and about 332 MiB peak private memory per native process. These are local measurements, not universal speed guarantees.
- Same-process multi-threaded simulation remains a separate research prototype and is not exposed by this release.


## v1111.2 · 2026-11-11

- Move random opponent tactics into the match run controls and remove the standalone away-pool sidebar page.
- Enable the option to open candidate import, weights and uniform-attribute settings; closing the settings retains the enabled state, while disabling randomization retains candidates and weights.
- Rename save-library import to Add random candidates, without enabling randomization automatically.
- Keep empty-candidate setup local and prevent starting a random match until candidates are added.
- Preserve the existing pool format, per-seed draws and tactical-execution integration; update Chinese and English copy.


## v1111.1 · 2026-11-11

- Integrate PR #3 with the v1111 official FM27 27.0.1+2494687 adapter.
- Browse loaded leagues and read league/country names from local game data.
- Generate original-engine AI plans for opponents in the managed league, with club-home/club-away contexts, progress, caching and retry.
- Export verified FMF plans and import mixed generated/preset plans into the away pool without silently dropping teams.
- Invalidate derived plans when engine identity changes and preserve missing-coach restrictions.
- Retain v1111 save-layout, tactic auxiliary-map, TEAM-count discovery and tactical-execution compatibility fixes.
- AI generation uses current squads, fixed seed 0 and the default player-side template; imported pool plans are static.
- Validation on a 27.0.1 Manchester United save: 19 opponents; 36 generated plans plus one fallback preset exported/imported; one unavailable secondary preset explicitly reported. HIGHWAY STAR FMF round-trip passed. Three complete native matches passed, including one using the final bundled runtime. Automated checks: 145 passed, one Windows symlink skip; i18n and EXE self-test passed.

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


## v1111.2 分支历史

以下为 v1111.2 分支已合入但未独立发布的内容。

- 新增真实AI战术批量生成：读取每队现任主教练、当前阵容和你自己的主教练，用本机原版引擎做 0 tick 对局准备并回读完整双阶段战术；每个对手生成对手主场/对手客场两套（列表显示为「球队主场战术/球队客场战术」）并直接替换第1/2套，支持进度条、并行生成与缓存增量补齐；缓存绑定引擎与生成协议身份，引擎或适配器变化后失效重生成；导出与导入客队战术池按球队/变体合并真实战术与可用预设并报告遗漏，空库不再阻断预设导出。
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
