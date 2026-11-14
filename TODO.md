# TODO

状态标记：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成，`[!]` 阻塞。完成必须附带独立审核 PASS。

## 当前

- [x] 开启 fork 的 Issues 功能。
- [x] 创建 `refactor/v2-modular` 分支。
- [x] 合并上游 v1112 的 worker 复用与 1–256 并行。
- [x] 合并提交 `0c24c66` 独立审核（合并第三轮 PASS）。
- [x] 设计文档与 ADR，第十一轮审核 PASS；合并审核第三轮 PASS。
- [x] React/Tauri 壳层第五轮 PASS；Windows cargo build/test、NSIS 与 sidecar 资源断言在 Actions run 43252465016 全部通过。
- [ ] 安装包内 sidecar 启动/退出/卸载真机 QA（发布门槛）。
- [x] 23 人名单领域切片（31 项测试）第五轮审核 PASS；bench/显式多 GK/短名单规则闭环。
- [x] 存档对战退役最终 PASS；核心 career 入口、旧 UI、测试与文档已删除。
- [x] sidecar 基础切片：三轮审核 PASS；28 项测试；迁移/health/错误封套/连接/Origin/token repr/CLI env/入口/ACL 已闭环。
- [x] PyInstaller onedir sidecar 构建成功，并通过 ready/health/shutdown 冒烟测试（Linux）。
- [x] Rust 纯核心 crate：ready/token/backoff/connection，4 项 cargo test 通过。
- [x] Python 3.12 sidecar 可独立启动与自检；PyInstaller onedir 冒烟通过。
- [~] Tauri 2 壳、React 前端与打包链路：Windows cargo build/test 与 NSIS 已通过；sidecar 资源路径断言与新 CI run 待验证。

## Phase 0 基础设施

- [x] 锁定技术栈：Tauri 2 + Rust 桌面壳，Python 3.12 sidecar，React 19 + TypeScript + Vite。
- [x] 锁定存储边界：SQLite 空库启动，旧目录保留但不读取、不写入、不迁移。
- [x] 锁定名单边界：只允许 23 人。
- [x] README 增加独立维护声明。
- [x] 建立 DESIGN.md、TODO.md、ADR 与设计系统文档。
- [x] 修复设计审核 findings 并复审 PASS。
- [x] Rust 工具链与纯核心 crate（ready/token/backoff/connection），4 项 cargo test 通过。
- [~] CI：Linux Python/前端/Rust core 与 Windows sidecar 构建、`cargo build/test`、`tauri build --bundles nsis` 工作流已写入；等待 GitHub Actions 首次运行。
- [ ] Rust 核心 crate 补齐 sidecar 进程监督测试。
- [ ] Windows sidecar 打包、Tauri 安装包构建与真机验证。
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
- [~] 替换映射：`library import/status/club/load/pool-import` 的旧服务仍有存档战术库实现，v2 sidecar 尚未暴露；旧 career 入口已删除。
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
- [~] 每个模块的单元测试与性质测试：setpieces、编码器、客队池与对比均已覆盖，性质测试待补。
- [x] 独立审核 PASS。

## Phase 2 存储与引擎

- [x] SQLite 连接、迁移与仓储：settings、pool_entries、drafts、jobs/job_runs、saves/save_leagues/save_clubs、artifacts、idempotency 与 `/api/pools`、`/api/drafts`、`/api/jobs`、`/api/saves`、`/api/results`、`/api/artifacts`、`/api/settings` 均已实现并通过独立审核。
- [~] 空库启动已实现；只读旧目录探测与存档读取端口已接入 fmsave 适配器。
- [~] 原生宿主适配器与 counted-session 能力协商：能力解析、运行时计划与文件协议适配器已实现并通过审核；真实 Windows 宿主联调待后续。
- [~] 1–256 路调度、取消、续跑、磁盘/内存预检：并发预检、串行调度与引擎分道（1/4/8 路身份一致）已实现并 PASS，1/8/256 真机验收待后续。
- [x] 实验提交接线：草案与客队战术池按种子物化为 FM27CFG1 场景、A/B 共用同一次抽签、提交持锁与失败清理、删除任务清理物化目录；已通过独立审核。
- [x] 原生引擎生产接线：create_app 按注入 engine、engine_root 惰性宿主、未配置占位的顺序解析，运行时计划在启动时按能力协商，派发前按任务并行数配置宿主分道；已通过独立审核。
- [x] 宿主资源探测：CPU、可用内存、空闲磁盘与推荐并行数，CLI 自动预填；已通过独立审核。
- [~] 旧宿主回退到 64 场或执行力隔离模式，并记录 provenance：运行时计划与 provenance 进行中。
- [ ] 并发验收矩阵：1、8、256 路提交、取消、续跑、结果身份一致。
- [ ] 真实引擎 Windows 验证脚本。
- [ ] 独立审核 PASS。

## Phase 3 接口

- [~] FastAPI 路由、错误封套、分页、幂等：路由模块化、`/api/jobs`、`/api/saves`、结果/产物/设置接口与 Idempotency-Key 已实现；注册表统一生成待后续。
- [x] 草案写入的双阶段战术校验：创建与更新按运行时目录校验位置、角色阶段、资格上下文、职责与 2×11 结构，目录缺失或不可解析时跳过；已通过独立审核。
- [x] SSE 进度推送：事件发布器、SSE 流、任务与实验事件接线，以及前端事件订阅（指数退避重连、断线提示、300ms 合并刷新）已实现并通过独立审核；断线时以手动刷新降级，未实现自动轮询。
- [~] 命令注册表，HTTP/CLI/MCP 全部由同一份定义生成：registry.py 已声明 51 项能力，三入口双向契约测试与漂移检测通过；由注册表生成代码待后续。
- [x] CLI 全功能命令与退出码：51 项能力对应命令、三个下载命令与 0/1/2 退出码已实现并 PASS。
- [x] MCP tools/resources/prompts 全功能同步：stdio 协议层、49 工具、4 个 resources、2 个 prompts 与 `fm27lab mcp` 命令已实现并通过审核。
- [x] 前端 API 类型统一到生成的 OpenAPI schema：40 项别名与 2 项派生复用生成接口、25 项保留手写并记录理由、前后端状态枚举按领域状态机收紧；已通过独立审核。
- [~] 契约测试：三入口能力对齐、错误码与幂等契约测试已覆盖；OpenAPI schema 快照尚未建立。
- [x] 独立审核 PASS：Phase 3 各切片由独立审核子代理给出 PASS，记录见 docs/REVIEWS.md。

## Phase 4 桌面壳

- [~] Tauri 2 窗口、单实例、sidecar supervisor 已实现；文件对话框、打开数据目录、外部链接、托盘与自动更新待 Phase 4。
- [~] sidecar PyInstaller 打包脚本与 Tauri resources 已接入；Windows 安装包构建待 CI。
- [~] sidecar 启动、ready 行、健康检查、重启、优雅退出（静态实现；shell 复审与 Windows CI 待通过）。
- [~] token 生成、endpoint.json、Tauri `get_connection`、事件刷新（静态实现；待复审）。
- [ ] 文件对话框、打开数据目录、外部链接：需要 tauri-plugin-dialog 与 tauri-plugin-opener 及 Rust 命令，本机无 Rust 工具链与 CI 运行记录，须在有 cargo 与 CI 可见的环境完成。
- [x] 文档与 v2 实现事实对齐：AGENT_QUICKSTART、AGENT_INTEGRATION、AGENT_VERIFICATION 已按真实 endpoint、关闭接口、命名空间与测试计数重写；已通过独立审核。
- [x] 删除 Launcher.cs 与旧 C# 构建入口，并从 scripts/export_source.py 的 TOP 移除；同步 `docs/AGENT_INTEGRATION.md`、`docs/AGENT_VERIFICATION.md` 与 `THIRD_PARTY_NOTICES.md` 中的 Launcher 描述；已通过独立审核。
- [ ] Windows 安装包与卸载清理；CI 需执行 `tauri build` 验证 sidecar resources。
- [ ] 独立审核 PASS。

## Phase 5 UI

本阶段只做应用骨架、设计系统、页面框架与通用组件；Issue 行为在 Phase 6 作为增量实现，避免同一功能重复实现。

- [x] React 应用骨架、路由、查询层与错误边界：骨架、路由与查询层已实现，页面错误边界提供回退、重试与按路由复位；已通过独立审核。
- [x] 设计 token、字体、组件库与 FM 配色。
- [x] 战术板双阶段：只读板、阶段切换与 catalog 中文标签，编辑模式与本地副本、拖拽与键盘交换首发、按阶段角色编辑、保存/放弃与脏态保护；已通过独立审核。
- [x] 球员属性与隐藏属性分组：只读分组页与批量编辑面板已实现并 PASS。
- [~] 存档战术库与真实 AI 生成：fmsave 读取、FMF 导入导出与战术库页面文件导入、名单与阵容同步已实现；AI 生成待后续。
- [x] 结果页、对比、历史与批量管理：结果页、跨任务对比与任务批量管理已实现；历史任务由任务页分页与状态筛选、结果页任务列表覆盖，未单设历史页面；已通过独立审核。
- [x] 实验提交页面：草案与基线选择、种子解析与总场数上限、并行数与超分配、主机资源探测与自动并发预检、提交与启动、启动结果独立展示；已通过独立审核。
- [x] 设置、说明、空/加载/错误状态：设置页含连接状态、版本与说明分区，空、加载与错误状态复用统一组件。
- [ ] Playwright 主流程与可访问性检查：本机缺少 Chrome 依赖的系统库，缓存浏览器无法启动，待具备浏览器运行依赖的环境补做。
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
- [~] 客队池统一属性使用同一策略；旧场景 schema 兼容：客队池统一属性已复用可见属性策略，旧场景 schema 兼容待后续。
- [~] 测试覆盖分组、复制、配对、撤销、旧方案与客队池：领域 51 项与客队池 66 项测试通过，旧方案待补。
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
- [~] 样本、存档、AI 生成、FMF、战术池与结果统计全部归一化：样本、存档、FMF、战术池与实验配置均经 `normalize_scenario` 归一化；AI 生成输入在 `fm27lab/adapters/engine_native/scenario_codec.py` 显式拒绝，待后续。
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

## Phase 7 收尾

- [x] 删除存档对战的残留引用与旧构建入口：C# Launcher 与 EXE 构建入口退役，代码、脚本、文档与清单同步；已通过独立审核。
- [x] README 中英文重写并同步升级说明：删除 v1 语义与旧截图引用，改写为 v2 架构、三入口、实验与结果流程、构建测试与版本状态；数字与常量逐条核对、双语对称；已通过独立审核。
- [x] DESIGN.md、DESIGN_SYSTEM.md、CHANGELOG.md、TODO.md 同步：按实现校准接口契约、事件流、注册表与测试章节。
- [x] 字体资产与 OFL 许可写入 THIRD_PARTY_NOTICES：Barlow 与 JetBrains Mono 的 OFL 1.1 说明已就位。
- [x] 性能基准：`scripts/benchmark.py` 与 `docs/PERFORMANCE.md` 覆盖 HTTP 只读路径、场景归一化、客队池展开与配对 bootstrap 成本，输出结构由测试锁定；已通过独立审核。
- [ ] 并发对比基准：真实引擎下的 1、8、256 路吞吐与结果身份对比，待 Windows 真机环境。
- [x] 安全与隐私检查：`docs/SECURITY.md` 与 22 条边界测试覆盖鉴权矩阵、令牌与 endpoint 权限、CORS、路径包含、输入上限、幂等与仓库隐私；修复数据目录 0755 缺陷；已通过独立审核。
- [ ] 最终独立审核 PASS。
- [ ] 发布候选构建与 Windows 真机验证。

## 发布门槛

- Windows x64 + FM27 27.0.1+2494687：原生兼容、单场、A/B、战术池、真实名单、取消/续跑。
- 并发 1、8、256 路的结果身份一致；资源预检与旧宿主回退有记录。
- 23 人名单在样本、存档、AI 生成、FMF 导入与结果统计中一致。
- Tauri 安装包可启动 sidecar，退出后无残留进程。
- CLI 与 MCP 在无桌面环境下可完成完整实验流程。
- 旧目录不被修改；新库为空启动。
- README 不再包含 `career_*` 或存档对战使用说明。

## 审核记录

见 [docs/REVIEWS.md](docs/REVIEWS.md)。
