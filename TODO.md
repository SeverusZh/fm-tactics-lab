# TODO

状态标记：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成，`[!]` 阻塞。完成必须附带独立审核 PASS。

## 当前

- [x] 开启 fork 的 Issues 功能。
- [x] 创建 `refactor/v2-modular` 分支。
- [x] 合并上游 v1112 的 worker 复用与 1–256 并行。
- [x] 合并提交 `0c24c66` 独立审核（合并第三轮 PASS）。
- [x] 设计文档与 ADR，第十一轮审核 PASS；合并审核第三轮 PASS。
- [x] React/Tauri 壳层第五轮 PASS；Windows cargo build/test、NSIS 与 sidecar 资源断言在 Actions run 43252465016 全部通过。
- [x] 安装包内 sidecar 启动、退出与卸载真机 QA（发布门槛）：`scripts/verify_installer_windows.ps1` 在 windows-latest 静默安装、启动桌面壳、等待 sidecar 与 endpoint.json、关闭窗口并静默卸载，23 项断言全通过（CI run 43735497957），证据为 installer-qa 工件。
- [x] 23 人名单领域切片（31 项测试）第五轮审核 PASS；bench/显式多 GK/短名单规则闭环。
- [x] 存档对战退役最终 PASS；核心 career 入口、存档对战旧 UI、测试与文档已删除。
- [x] sidecar 基础切片：三轮审核 PASS；28 项测试；迁移/health/错误封套/连接/Origin/token repr/CLI env/入口/ACL 已闭环。
- [x] PyInstaller onedir sidecar 构建成功，并通过 ready/health/shutdown 冒烟测试（Linux）。
- [x] Rust 纯核心 crate：ready/token/backoff/connection，4 项 cargo test 通过。
- [x] Python 3.12 sidecar 可独立启动与自检；PyInstaller onedir 冒烟通过。
- [x] Tauri 2 壳、React 前端与打包链路：Windows CI run 43252465016 与 43552112064 全 job success，cargo build/test、`tauri build --bundles nsis`、sidecar 资源与安装包断言均通过；安装包内真机启动与卸载 QA 仍为发布门槛。

## Phase 0 基础设施

- [x] 锁定技术栈：Tauri 2 + Rust 桌面壳，Python 3.12 sidecar，React 19 + TypeScript + Vite。
- [x] 锁定存储边界：SQLite 空库启动，旧目录保留但不读取、不写入、不迁移。
- [x] 锁定名单边界：只允许 23 人。
- [x] README 增加独立维护声明。
- [x] 建立 DESIGN.md、TODO.md、ADR 与设计系统文档。
- [x] 修复设计审核 findings 并复审 PASS。
- [x] Rust 工具链与纯核心 crate（ready/token/backoff/connection），4 项 cargo test 通过。
- [x] CI：Linux Python/前端/Rust core 与 Windows sidecar 构建、`cargo build/test`、`tauri build --bundles nsis` 工作流已建立；run 43552112064 全 job success。
- [x] Rust 核心 crate 补齐 sidecar 进程监督测试：`rust/crates/fm27lab-core/src/supervisor.rs` 承载阶段机、重启预算、健康分级与关闭三步，`src-tauri/src/lib.rs` 改为复用，12 项契约测试覆盖；review-backend 独立审核 PASS。
- [x] Windows sidecar 打包、Tauri 安装包构建与真机验证：CI windows-tauri 以 PyInstaller 打包 sidecar、`tauri build --bundles nsis` 构建安装包并断言载荷，随后在 Windows runner 执行安装与卸载 QA（CI run 43735497957），证据为 installer-qa 与 windows-nsis 工件。
- [x] Python 3.12 sidecar 打包与自检：PyInstaller onedir 构建与独立启动冒烟通过。
- [x] 前端构建、字体资产与静态资源打包：字体自托管、构建产物与资源引用已验证。
- [x] OpenAPI、CLI、MCP 三入口契约测试骨架：注册表对齐、命令树与工具名契约测试已建立。
- [x] 独立审核流程与 REVIEWS.md 记录规范：每个切片由独立审核子代理给出 PASS/FAIL 并记录。

## Phase 0.5 删除存档对战

目标：在新建接口与 UI 之前完成 delete-first，避免旧任务模型继续存活。

- [x] 删除 UI：`save-mode.js` 的存档对战模式、`save-mode.css` 相关样式、页面入口与 i18n 文案；战术执行力实验控件拆到 `workspace-controls.js`。
- [x] 删除 HTTP 的 career 批次路径：`/api/save/load`、`opponents`、`preview`、`run`、`club`，以及 `/api/agent/v1/career/*` 全部路径。`/api/save/selection` 作为通用名单选择保留，并新增 `/api/agent/v1/selection`。
- [x] 删除 CLI：`fm27lab career *` 全部命令与 `draft create --from save`。
- [x] 删除 MCP：`career_import`、`career_status`、`career_team`、`career_opponents`、`career_preview`、`career_cancel`、`career_run` 及 save source/schema。
- [x] 替换映射：ADR-0008 记录 `library import/status/club/load/pool-import` 在 v2 的路由映射（`/api/saves/import`、`/api/saves`、`/squad`、`tactics/{index}/import`、`apply-roster`、`tactics/{index}/pool`、`export.fmf`），不保留 `library_*` 别名。
- [x] 删除旧文档中的存档对战与 `career_*` 段落；AGENT 三份文档、README 与发布说明已同步。
- [x] 删除旧 career 测试与 schema，新增负向测试：Agent career 路径 404、旧 MCP 工具未知、旧 CLI 子命令不可用、旧 UI 资源不存在；静态路由检查保留。
- [x] 更新 ADR-0006、CHANGELOG、TODO 与 REVIEWS。
- [x] 独立审核 PASS：retirement-reviewer-2 最终确认。

## Phase 1 领域模块

- [x] catalog 快照与 scenario 23 人归一化；完整 schema 修复待 service 接入。
- [x] tactics 双阶段、角色阶段/资格上下文、职责与指令校验。
- [x] setpieces 模型与编码：定位球领域与原生场景编码已实现并 PASS。
- [x] pool 抽签、轮战与真实名单应用已实现并 PASS。
- [x] roster 统一 23 人策略、确定性重映射与真实名单应用。
- [x] results 胜平负、Wilson、进失球、xG/xGA、控球、射门、传球与同种子配对差值；分布/CSV 待 service。
- [x] 每个模块的单元测试与性质测试：hypothesis 性质测试覆盖 scenario、tactics、results、pool 与 compare 五个域模块（`fm27lab/tests/test_properties_*.py`），setpieces、编码器与客队池另有专项测试。
- [x] 独立审核 PASS。

## Phase 2 存储与引擎

- [x] SQLite 连接、迁移与仓储：settings、pool_entries、drafts、jobs/job_runs、saves/save_leagues/save_clubs、artifacts、idempotency 与 `/api/pools`、`/api/drafts`、`/api/jobs`、`/api/saves`、`/api/results`、`/api/artifacts`、`/api/settings` 均已实现并通过独立审核。
- [x] 空库启动、只读旧目录探测与存档读取端口：旧目录不写不迁移，存档经 fmsave 适配器只读；真实存档读取由 Windows 真机 run 43593986849 覆盖。
- [x] 原生宿主适配器与 counted-session 能力协商：能力解析、运行时计划与文件协议适配器已实现并通过审核；Windows 真机完成真实宿主联调：宿主 `--worker-capabilities` 声明 protocol 2、max_jobs 1000000、execution_context_reset 与 per_match_resource_release，`--check-image` 对游戏镜像给出 compatible true 与 disposition verified，单场真实比赛当次墙钟 2.97 秒、宿主计时 2.875 秒完成 23797 tick 且球员统计身份校验通过；批次验收经 `scripts/verify_engine_windows.ps1` 完成，见第 189 行；批次 provenance 记录 counted_sessions true、session_scope remaining_batch_lane、capability_version 2。仓库 `native/adapter_version.json` 已更新为 27.0.1+2503222，镜像 sha256 与游戏 dll 一致；适配器仍按运行时镜像指纹协商而不依赖静态版本号，被验收宿主为用仓库源码与本机 DLL 构建的本地产物。
- [x] 1–256 路调度、取消、续跑、磁盘/内存预检：并发预检、串行调度与引擎分道已实现；1/8/256 矩阵见 Phase 2 并发验收矩阵项，真实引擎吞吐见收官项，真机 1/8/32 路取证见第 189 行。
- [x] 实验提交接线：草案与客队战术池按种子物化为 FM27CFG1 场景、A/B 共用同一次抽签、提交持锁与失败清理、删除任务清理物化目录；已通过独立审核。
- [x] 原生引擎生产接线：create_app 按注入 engine、engine_root 惰性宿主、未配置占位的顺序解析，运行时计划在启动时按能力协商，派发前按任务并行数配置宿主分道；已通过独立审核。
- [x] 宿主资源探测：CPU、可用内存、空闲磁盘与推荐并行数，CLI 自动预填；已通过独立审核。
- [x] 旧宿主回退到 64 场或执行力隔离模式，并记录 provenance：运行时计划按能力协商 counted/legacy 分支并写入任务 summary；已通过独立审核；真机 counted-session 声明由第 68 行覆盖，旧宿主回退分支仍只由假引擎用例覆盖。
- [x] 并发验收矩阵：`scripts/verify_concurrency_matrix.py` 与 `fm27lab/tests/test_concurrency_matrix.py` 覆盖 1/8/256 路提交、取消、派发竞态与续跑，Linux 实测 256 场三档分别为 169.5、863.1、1508.5 场每秒，逐场身份一致；CI 的 windows-concurrency job 复跑并上传证据。
- [x] 真实引擎 Windows 验证脚本：`scripts/verify_engine_windows.ps1` 经 HTTP 驱动运行中的 sidecar，跑 1/8/256 三档、按 seed 比对 score 与 stats 签名，资源受限时以覆盖容量重试并记录，输出 evidence.json；CI 校验脚本语法，执行需要具备 FM27 资产的 Windows 环境。
- [x] 独立审核 PASS：并发取消竞态、仓储与实验接线、注册表、性质测试与 Rust supervisor 等切片由 review-backend 独立审核通过，记录见 docs/REVIEWS.md；真实宿主联调由第 68 与 189 行记录。

## Phase 3 接口

- [x] FastAPI 路由、错误封套、分页、幂等：路由模块化、任务/存档/结果/产物/设置接口与 Idempotency-Key 已实现；注册表生成边界由 ADR-0007 定为能力声明单一来源、适配层手写。
- [x] 草案写入的双阶段战术校验：创建与更新按运行时目录校验位置、角色阶段、资格上下文、职责与 2×11 结构，目录缺失或不可解析时跳过；已通过独立审核。
- [x] SSE 进度推送：事件发布器、SSE 流、任务与实验事件接线，以及前端事件订阅（指数退避重连、断线提示、300ms 合并刷新）已实现并通过独立审核；断线时以手动刷新降级，未实现自动轮询。
- [x] 命令注册表：`fm27lab/registry/` 由 model.py 与 parts/ 分片聚合 61 项能力，三入口双向契约测试与漂移检测通过；ADR-0007 修订生成表述为声明单一来源加一致性锁定。
- [x] CLI 全功能命令与退出码：61 项能力对应 64 个叶子命令含三个下载命令，0/1/2 退出码已实现并 PASS。
- [x] MCP tools/resources/prompts 全功能同步：stdio 协议层、58 个工具、4 个 resources、2 个 prompts 与 `fm27lab mcp` 命令已实现并通过审核。
- [x] 前端 API 类型统一到生成的 OpenAPI schema：68 个类型中 41 项别名与 2 项派生复用生成接口、25 项保留手写并记录理由、前后端状态枚举按领域状态机收紧；已通过独立审核。
- [x] 契约测试：三入口能力对齐、错误码与幂等契约已覆盖；OpenAPI 快照 `docs/openapi.json` 记录 57 条路径、75 个操作与 86 个组件模型，由 `scripts/generate_openapi_snapshot.py` 生成、`fm27lab/tests/test_openapi_snapshot.py` 校验。
- [x] 独立审核 PASS：Phase 3 各切片由独立审核子代理给出 PASS，记录见 docs/REVIEWS.md。

## Phase 4 桌面壳

- [x] Tauri 2 窗口、单实例、sidecar supervisor、文件选择对话框、系统托盘、打开数据目录与外部链接均实现；自动更新按 ADR-0010 不在本轮范围。
- [x] sidecar PyInstaller 打包脚本与 Tauri resources 已接入；Windows 安装包由 CI 构建并断言载荷。
- [x] sidecar 启动、ready 行、健康检查、重启、优雅退出：编写并由 review-backend 独立复核，Windows CI 的 cargo build/test 与安装包 QA 为编译与运行证据。
- [x] token 生成、endpoint.json、Tauri `get_connection`、事件刷新已实现并通过独立复核。
- [x] 文件对话框、打开数据目录与外部链接：文件选择经 tauri-plugin-dialog 且只授予 dialog:allow-open；外部链接只允许 http(s)，Windows 走 FileProtocolHandler，目录走系统文件管理器，未引入额外依赖。
- [x] 文档与 v2 实现事实对齐：AGENT_QUICKSTART、AGENT_INTEGRATION、AGENT_VERIFICATION 已按真实 endpoint、关闭接口、命名空间与测试计数重写；已通过独立审核。
- [x] 删除 Launcher.cs 与旧 C# 构建入口，并从 scripts/export_source.py 的 TOP 移除；同步 `docs/AGENT_INTEGRATION.md`、`docs/AGENT_VERIFICATION.md` 与 `THIRD_PARTY_NOTICES.md` 中的 Launcher 描述；已通过独立审核。
- [x] Windows 安装包构建与卸载清理：CI 通过 `tauri build` 生成 NSIS 并断言 sidecar resources，安装、启动、关闭与卸载清理由 `scripts/verify_installer_windows.ps1` 在 Windows runner 验证（CI run 43735497957，卸载后进程、目录与注册表项均已清理）。
- [x] 独立审核 PASS：桌面壳切片由 review-backend 两轮独立审核通过，打开器注入面、脚本与工作流契约均已闭环，记录见 docs/REVIEWS.md。

## Phase 5 UI

本阶段只做应用骨架、设计系统、页面框架与通用组件；Issue 行为在 Phase 6 作为增量实现，避免同一功能重复实现。

- [x] React 应用骨架、路由、查询层与错误边界：骨架、路由与查询层已实现，页面错误边界提供回退、重试与按路由复位；已通过独立审核。
- [x] 设计 token、字体、组件库与 FM 配色。
- [x] 战术板双阶段：只读板、阶段切换与 catalog 中文标签，编辑模式与本地副本、拖拽与键盘交换首发、按阶段角色编辑、保存/放弃与脏态保护；已通过独立审核。
- [x] 球员属性与隐藏属性分组：只读分组页与批量编辑面板已实现并 PASS。
- [x] 存档战术库：fmsave 读取、FMF 导入导出、战术库页面文件导入、战术导出为 FMF 与加入客队池、名单与阵容同步均已实现；真实 AI 生成按 ADR-0009 不在本轮范围。
- [x] 结果页、对比、历史与批量管理：结果页、跨任务对比与任务批量管理已实现；历史任务由任务页分页与状态筛选、结果页任务列表覆盖，未单设历史页面；已通过独立审核。
- [x] 实验提交页面：草案与基线选择、种子解析与总场数上限、并行数与超分配、主机资源探测与自动并发预检、提交与启动、启动结果独立展示；已通过独立审核。
- [x] 设置、说明、空/加载/错误状态：设置页含连接状态、版本与说明分区，空、加载与错误状态复用统一组件。
- [x] Playwright 主流程与可访问性检查：`web/e2e` 覆盖应用壳、战术板、实验与任务、结果与无障碍五组 30 项用例，CI playwright job 执行；本机经本地系统库跑通 30 项。
- [x] 独立审核 PASS：Phase 5 各切片由独立审核子代理给出 PASS，记录见 docs/REVIEWS.md；Playwright 主流程待具备浏览器依赖的环境补做。

## Phase 6 功能请求

本阶段只实现 Issue/PR 的增量行为与验收；Phase 5 已完成的基础组件不重复开发。

### Issue #5 隐藏属性

上游：https://github.com/lqf0624/fm-tactics-lab/issues/5

- [x] 批量设置默认只改可见能力属性；隐藏属性与左右脚默认保留。
- [x] 技术/精神/身体/门将与隐藏/倾向分组，可分别启用与设值。
- [x] 从参考球员复制隐藏属性与左右脚到全队/首发/当前球员。
- [x] 左右脚按惯用脚与逆足配对，避免两脚同值。
- [x] 提供撤销或恢复原值。
- [x] 客队池统一属性使用同一策略：客队池统一属性已复用可见属性策略；已通过独立审核。
- [x] 旧场景 schema 兼容：schema 4 的 phase_plans 在名单归一化与物化前升级为 schema 3 原生两阶段形状，按阶段名映射、阶段指令合并与中文字段校验，历史旧形状草案无需迁移即可物化；已通过独立审核。
- [x] 测试覆盖分组、复制、配对、撤销、旧方案与客队池：领域 51 项、客队池 66 项与旧场景转换 36 项新增测试通过；已通过独立审核。
- [x] 独立审核 PASS：领域、属性接口与批量编辑 UI 均已 PASS。

### Issue #6 批量管理

上游：https://github.com/lqf0624/fm-tactics-lab/issues/6

- [x] `DELETE /api/jobs` 支持 `ids` 数组，返回 `{deleted, failed:[{id,error}]}`。
- [x] 运行中或排队任务跳过并报告原因；单条失败不影响其余。
- [x] 结果页与实验列表多选、全选、按状态筛选、删除所选：任务页与结果页均已实现并 PASS。
- [x] 二次确认列出名称/ID/场数；删除后刷新历史与当前选择。
- [x] 旧单条删除接口回归或明确退役：旧接口保留兼容并由测试记录契约分叉。
- [x] 测试覆盖部分失败、运行中跳过、空选择、目录校验：后端 58 项与前端 90 项相关测试通过。
- [x] 独立审核 PASS。

### Issue #7 统一 23 人

上游：https://github.com/lqf0624/fm-tactics-lab/issues/7

- [x] `MATCH_ROSTER_SIZE = 23` 单点定义，移除 23/26 分支：定义在 `fm27lab/domain/roster.py:8`；26 只作为旧池 schema 的接收上限并在 `fm27lab/domain/pool.py:552` 起裁剪，与比赛名单无关。
- [x] 样本、存档、FMF、战术池与结果统计全部归一化；真实 AI 生成输入在 `fm27lab/adapters/engine_native/scenario_codec.py` 显式拒绝，按 ADR-0009 不在本轮范围。
- [x] 确定性截断与重映射，覆盖首发、替补、门将、队长、主罚与定位球优先级：`fm27lab/tests/test_roster.py:124`、`:259`、`:370` 与 `fm27lab/tests/test_roster_apply.py:50`、`:367` 覆盖。
- [x] 不足 23 人的占位策略与 UI 提示：占位策略与球员页提示已实现（`fm27lab/tests/test_roster.py:72`、`fm27lab/tests/test_scenario.py:63`、`web/src/pages/PlayersPage.tsx`），含逐字文案与占位标识；已通过独立审核。
- [x] 旧 26 人方案加载兼容与提示：兼容、`roster_trim` 记录与球员页裁剪提示已实现（`fm27lab/tests/test_roster.py:34`、`:390`、`fm27lab/tests/test_roster_apply.py:168`、`web/src/pages/PlayersPage.tsx`）；已通过独立审核。
- [x] 测试矩阵覆盖 26→23、23→23、<23、只有 1 名门将、0 名门将、全部首发为 generated、引用被移除：`fm27lab/tests/test_roster.py:34`、`:57`、`:72`、`:95`、`:106`、`:222`、`:124` 与 `fm27lab/tests/test_scenario.py:63`。
- [x] 独立审核 PASS。

### PR #10 遗留功能

上游：https://github.com/lqf0624/fm-tactics-lab/pull/10

- [x] 人类经理阵容自动读取：fmsave 适配器识别 managed club 并读取当前 selection。
- [x] 首发 11 人与替补按存档 selection 覆盖，保留战术与定位球；提供撤销。
- [x] 导入存档后可读取经理俱乐部与名单；覆盖导入确认与错误提示 UI 已实现。
- [x] 结果页客队战术池卡片可折叠，显示条目数、模式、名单来源：摘要接口与前端卡片均已实现并通过审核。
- [x] 折叠状态在会话内保留；移动端/窄屏可用。
- [x] 测试覆盖自动检测、首发/替补覆盖、撤销、折叠状态：接口与 UI 测试均已覆盖。
- [x] 独立审核 PASS。

### 导入体验改进

- [x] 导入存档支持从资源管理器选择：接入 tauri-plugin-dialog 并只授予 dialog:allow-open，桌面环境存档与 FMF 导入共用原生选择器，浏览器与测试环境保留手动路径；已通过独立审核。
- [x] 修复存档导入的路径输入失败：导入前去除首尾空白与成对 ASCII 引号，修复复制文件地址带引号或空白导致“存档文件不存在”；已通过独立审核。
- [x] 免存档直接导入 FMF 战术文件：`POST /api/drafts/import-fmf-file` 按路径读取、4 MiB 上限、名称派生与截断、CLI `drafts import-fmf-file`、前端存档库表单与导入后跳转战术板，空状态说明无存档可用的功能范围；已通过独立审核。
- [x] 战术页草稿参数恢复：清除 `?draft=` 参数后手动改选草稿，再重新加入同一参数仍会应用；未保存修改期间参数不抢占当前草稿；已通过独立审核。
- [x] 修复新版引擎存档无法读取：fmsave 升级到 0.12.4 支持 FM27 未验证构建，版本不支持时提示具体 build 并引导更新应用，unique_id 冲突消歧与缺失名称占位使真实存档可导入并应用到草案；已通过独立审核。
- [x] 手动选择草稿同步地址栏参数：下拉切换以 replace 写回 `?draft=` 并保留其他查询参数，刷新与分享可恢复，未保存修改期间不写 URL，非法参数回退首个草稿。

## Phase 7 收尾

- [x] 删除存档对战的残留引用与旧构建入口：C# Launcher 与 EXE 构建入口退役，代码、脚本、文档与清单同步；已通过独立审核。
- [x] README 中英文重写并同步升级说明：删除 v1 语义与旧截图引用，改写为 v2 架构、三入口、实验与结果流程、构建测试与版本状态；数字与常量逐条核对、双语对称；已通过独立审核。
- [x] DESIGN.md、DESIGN_SYSTEM.md、CHANGELOG.md、TODO.md 同步：按实现校准接口契约、事件流、注册表与测试章节。
- [x] 字体资产与 OFL 许可写入 THIRD_PARTY_NOTICES：Barlow 与 JetBrains Mono 的 OFL 1.1 说明已就位。
- [x] 性能基准：`scripts/benchmark.py` 与 `docs/PERFORMANCE.md` 覆盖 HTTP 只读路径、场景归一化、客队池展开与配对 bootstrap 成本，输出结构由测试锁定；已通过独立审核。
- [x] 并发通道对比基准：固定每场 2 秒的模拟器下实测 1、2、4 条通道的墙钟与加速比，JSON 与中文表格输出、失败路径中文受控退出；已通过独立审核。
- [x] Windows 安装包 sidecar 资源映射修复：`bundle.resources` 改用目录形式以保留 PyInstaller onedir 的 `_internal/` 与迁移目录，CI 解包安装包校验载荷；重建安装包经 7-Zip 复核与独立审核 PASS。
- [x] 真实引擎并发吞吐验证：`scripts/verify_engine_windows.ps1` 在具备 FM27 资产的 Windows 真机上经 HTTP 驱动 sidecar 完成。256 场批次 1、8、32 路墙钟 484.2、76.841、34.653 秒，按引擎计时的吞吐 0.529、3.413、8.0 场每秒，三档均 256/256 完成且按 seed 的 score 与 stats 签名与 1 路基线零差异；64 场批次记录并行 1、8、256 三档按引擎计时吞吐 0.525、2.909、3.048 场每秒且身份零差异，其中任务数 64 使实际 lane 数上限为 64。256 场配 256 路时实际 lane 达到 256，宿主在 256 路并发加载阶段返回 Windows 1455 系统资源耗尽并把这些场次记为失败 run，与资源预检给出的 recommended_workers 32 一致，故 256 场验收以 32 路取证；假引擎矩阵仍由 `scripts/verify_concurrency_matrix.py` 在 Linux 与 Windows CI 覆盖（1、8、256 路 1508.5、863.1、169.5 场每秒，CI run 43735497957）。
- [x] 安全与隐私检查：`docs/SECURITY.md` 与 22 条边界测试覆盖鉴权矩阵、令牌与 endpoint 权限、CORS、路径包含、输入上限、幂等与仓库隐私；修复数据目录 0755 缺陷；已通过独立审核。
- [x] 最终独立审核 PASS：本轮七条审查线（后端、前端、formations、CI 脚本、宿主取消、前端修复复核与后端修复复核）均 PASS；质量门 2855 项 pytest、281 项 legacy unittest、593 项 Vitest（21 文件）、ruff、类型生成、OpenAPI 快照与 manifest 505 文件通过；Windows CI run 43735497957 六个作业全部 success。
- [x] Windows 真机验证：CI run 43593986849 的安装包静默安装后，原生选择器导入 240,956,721 字节 FM27 存档 29.9 秒后 ready，名单 34 人标识唯一且恰 1 个占位名，apply-roster 范围 both 返回 200（首发 11 替补 12）且草案 23 人标识唯一，免存档 FMF 导入经原生选择器建草案成功。
- [x] 发布候选构建：`release.yml` 经 workflow_dispatch 在 Windows 全流程通过（run 43866462594，commit `0ea10fd`），构建、前端检查、pytest、legacy unittest、源码清单、cargo test、NSIS 安装包与安装/卸载 QA 依次成功；23 项安装断言全 PASS，工件为 release-installer `FM Tactics Lab_2.0.0_x64-setup.exe` 22.5 MB 与 release-installer-qa 证据；同提交 CI run 43866436688 六个作业 success。
- [x] 逐场释放标记竞态修复：消费端对不可解析标记做有界等待（宿主存活 5 秒上限、宿主已退出即判无效），并同步修复 legacy 源码版入口；假引擎以 partial_ack、garbage_alive、bad_exit_ack、bad_index_ack 夹具确定性覆盖，变异证明用例具判别力；4 核绑定探针修复前 22 次中 3 次失败，修复后 40 次全部完成 256 场，全量矩阵校验 229/229 通过；ADR-0012 记录写端原子发布为后续改进。

### 联赛对手战术池

- [x] 联赛目录、当前联赛、对手与一线队主教练偏好读取；真实存档验证 19 个对手与 17–18 名主教练。
- [x] 原装预设匹配、主/次偏好战术生成、FMF 导出与加入客队池；原生不可用时逐队返回原因。
- [x] 客队池随机/轮战模式、轮数、统一属性/真实名单写回草案；轮战种子数校验与前端提示。
- [x] 客队池 JSON 包导出/导入与前端测试；pytest、vitest、ruff 与 OpenAPI 快照通过。
- [x] 独立审核 PASS（2026-11-18，两轮；Critical 队伍指令位端序与 Important 索引、名单缓存、陈旧战术、偏好校验均已闭环）。
- [x] 运行时适配画像与自动重定位：宿主可按安装镜像 SHA-256 读取 `adapter_profile.txt`，`scripts/adapt_profile.py` 用公开掩码窗口摘要定位参考 RVA 并传播调用/数据引用，`--probe-engine` 验证加载、指纹与激活；ADR-0014 记录。BuildID 26620374 自动映射 57/99 个 `at()` 锚点，剩余 42 个（代码、VTable 与数据槽）待补齐。
- [ ] 原生引擎 26620374 真机验收：试验宿主已推进到 preparation 与模拟 tick 0，但随后在 `.tls` 保护代码触发未处理 `0x80000004` 单步异常（RVA 0x74b5950/0x47b4ac0），游戏 VEH 不处理，关闭宿主 VEH 结果相同。补齐 42 个锚点本身不足以绕过；需旧 DLL 精确画像复核或保护层分析，当前暂缓；试验诊断模式已合入 main，仅显式 `--trial-profile` 可用。

### 设计评审与体验重构

- [x] 引擎配置与诊断：引擎与游戏目录、宿主版本校验、sidecar 重启与 CLI 参数；已通过独立审核。
- [x] 引擎资源导入：从旧版安装与发布目录发现并组装数据目录下的引擎工作区，按游戏 dll 匹配版本；已通过独立审核。
- [x] 真实 FMF 导入与导出：原生宿主解析 AFE 归档、场景映射、FMF v8 打包与回读校验；已通过独立审核。
- [x] 存档战术库：签名扫描、宿主两段式回读、列表与建草案；已通过独立审核。
- [x] 服务端战术模板与战术板球队级编辑：心态与球队指令、草案生命周期修复；已通过独立审核。
- [x] 球员单项属性编辑与批量工具折叠；已通过独立审核。
- [x] 设置页、球员页、实验页、存档页与帮助页交互重做；已通过独立审核。
- [x] 客队战术池 UI 含改名、权重与 FMF 条目导入；职责、个人指令、盯防球员与盯防位置编辑；六套阵型模板按位置熟悉度自动排阵；存档战术导出 FMF 与加入客队池；定位球套路、任务与角色编辑及导入导出。
- [x] 实验进度与预计剩余、任务关键字筛选与重命名、结果单场明细与失败徽标；640px 窄屏布局、焦点可见性、对比度与加载骨架；旧引擎目录迁移提示与导入入口。

## 上游同步 v1113–v1114.6

- [x] 2503222 引擎兼容：`native/` 同步上游 v1113/v1113.1/v1114.6，Steam 参考构建改为 `27.0.1+2503222`（镜像 `8c6971ce…`），激活地址取自画像的 `activation_flag_rva`，执行回执按原始名单身份记录与校验；Windows 真机用仓库源码重建宿主后通过 `--worker-capabilities`、`--check-image` 与单场真实比赛（tick 23797、统计身份 verified）。当时存档布局沿用 fmsave 0.12.4，真实 2503222 存档读取验证通过。
- [x] Epic 适配：新增 `native/epic_adapter_version.json` 与 `native/epic_profile_metadata.json`（仅 rva/size/sha256 摘要），宿主按 `FM27_COMPAT_DIGEST_RANGES` 校验；构建支持 `--platform steam|epic`，分别输出到 `private/engine` 与 `private/epic-engine`。Windows 编译级验证通过（本机无 Epic DLL，未执行 --platform epic 完整构建，改用等价 digest header 编译与指纹拒绝分支验证），Steam DLL 对 Epic 构建返回 `epic_build_fingerprint_mismatch`；Epic 运行时验收需要具备 Epic 版游戏资产的机器。
- [x] 存档球员显示身份：名单新增 `display_name`（存档本地化名优先，读取失败回退原名）、`shirt_number`（仅已验证构建 27.0.0+2486695 与 27.0.1+2503222 且 game_db schema 4000，后者由本机真实存档验证、前者来自上游只读参考实现；歧义或未分配为 null，无可用注册记录时省略）与租借字段 `on_loan`/`loan_parent_club`/`loan_end`；真实 2503222 存档 34 人探针得到 22 个本地化名、24 个号码、1 名租借；存档页展示号码列与租借徽标。
- [x] 启动诊断保留：sidecar stderr 有界保留并持续写入日志文件，启动失败、超时或健康检查失败时错误信息包含退出码，并在日志文件可用时给出路径，同时写入 `<data>/logs/startup-error.txt`。
- [x] 未绑定草案与存档绑定映射：存档导入与替换不清除既有草案（回归测试锁定）；v2 不保存按存档绑定的球员指令，上游「切换存档时隔离指令」在 v2 不适用，映射结论记录在审核记录。
- [x] 独立审核 PASS。

## 上游 v1118.1 27.1.0 适配

- [x] 运行时布局画像（独立审核 PASS）：`adapter_profile.txt` 增加 manager/player 偏移、战术版本与执行采样栈字段；未激活画像保持参考布局零偏移。
- [x] Steam/Epic 静态画像（独立审核 PASS）：`scripts/static_profile.py` 从公开 RVA 映射与元数据生成 105 条映射，`scripts/build_native.py` 复制对应平台画像；镜像不匹配回退编译期契约，reference 不匹配 fail-closed。
- [x] 宿主 27.1.0 接线（独立审核 PASS）：RVA、manager/player 偏移、战术版本、FMF 流版本 61、执行采样栈与激活字；match importance 与 XGP 不移植。
- [x] 测试：画像生成/导出、宿主契约、engine import 可选画像；47 项聚焦 pytest 与 ruff 通过，f1/f3/h 变异全杀，独立审核 PASS。
- [x] fmsave 0.14.1：新增 27.1.0 布局模块与生成球员 Unique ID 兜底；现有真实存档与全量 sidecar 测试 2974 项在 0.14.1 下通过；CI 待跑。
- [ ] Windows 真机：MSVC 编译、`--check-image`、`--probe-engine`、真实单场、A/B、27.1.0 存档导入与 Epic 27.1.0 完赛。
- [ ] 27.1.0 真实存档布局验证与发布矩阵更新。

## 发布门槛

- Windows x64 + FM27 Steam 27.0.1+2503222 或 Epic 27.0.1+epic：原生兼容、单场、A/B、战术池、真实名单、取消/续跑；Epic 运行时验证需要具备 Epic 版游戏资产的机器，执行力实验仅对 Steam 8c6971ce 构建开放。
- 并发 1、8、256 路的结果身份一致；资源预检与旧宿主回退有记录。
- 23 人名单在样本、存档、FMF 导入与结果统计中一致（真实 AI 生成不在本轮范围，见 ADR-0009）。
- Tauri 安装包可启动 sidecar，退出后无残留进程。
- CLI 与 MCP 在无桌面环境下可完成完整实验流程。
- 旧目录不被修改；新库为空启动。
- README 不再包含 `career_*` 或存档对战使用说明。

本轮已覆盖：并发的假引擎身份一致与 Windows CI 矩阵、真实引擎 64 场 1/8/256 路与 256 场 1/8/32 路吞吐与身份一致、安装包启动与卸载清理、CLI 与 MCP 无桌面流程、旧目录只读与新库空启动。

## 审核记录

见 [docs/REVIEWS.md](docs/REVIEWS.md)。
