# TODO

状态标记：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成，`[!]` 阻塞。完成必须附带独立审核 PASS。

## 当前

- [x] 开启 fork 的 Issues 功能。
- [x] 创建 `refactor/v2-modular` 分支。
- [x] 合并上游 v1112 的 worker 复用与 1–256 并行。
- [x] 合并提交 `0c24c66` 独立审核（合并第三轮 PASS）。
- [x] 设计文档与 ADR，第十一轮审核 PASS；合并审核第三轮 PASS。
- [~] React/Tauri 壳层第四轮 FAIL、第五轮待审；Windows cargo build/test 与 NSIS 已在 Actions run 43249250613 通过。
- [~] 23 人名单领域切片（8 项测试）已实现，待独立审核。
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
- [ ] 修复设计审核 findings 并复审 PASS。
- [x] Rust 工具链与纯核心 crate（ready/token/backoff/connection），4 项 cargo test 通过。
- [~] CI：Linux Python/前端/Rust core 与 Windows sidecar 构建、`cargo build/test`、`tauri build --bundles nsis` 工作流已写入；等待 GitHub Actions 首次运行。
- [ ] Rust 核心 crate 补齐 sidecar 进程监督测试。
- [ ] Windows sidecar 打包、Tauri 安装包构建与真机验证。
- [ ] Python 3.12 sidecar 打包与自检。
- [ ] 前端构建、字体资产与静态资源打包。
- [ ] OpenAPI、CLI、MCP 三入口契约测试骨架。
- [ ] 独立审核流程与 REVIEWS.md 记录规范。

## Phase 0.5 删除存档对战

目标：在新建接口与 UI 之前完成 delete-first，避免旧任务模型继续存活。

- [ ] 删除 UI：`save-mode.js` 的存档对战模式、`save-mode.css` 相关样式、页面入口与 i18n 文案；保留并拆出战术执行力实验控件。
- [ ] 删除 HTTP：`/api/save/load`、`/api/save/selection`、`/api/save/opponents`、`/api/save/preview`、`/api/save/run`、`/api/save/club`，以及 `/api/agent/v1/career/import`、`status`、`team`、`load`、`selection`、`opponents`、`preview`、`run`、`import/cancel`、`opponents/cancel` 及其任务准备路径。
- [ ] 删除 CLI：`fm27lab career *` 全部命令。
- [ ] 删除 MCP：`career_import`、`career_status`、`career_team`、`career_opponents`、`career_preview`、`career_cancel`、`career_run`。
- [ ] 提供替换映射：`career_import` → `library import`；`career_status` → `library status`；`career_team` → `library club`；`career_cancel` → `library cancel`；`career_opponents`、`career_preview`、`career_run` 删除；存档球队入池走 `library pool-import`；草案来源 `save` 改走 `library load`。
- [ ] 删除旧文档中的存档对战与 `career_*` 段落：`docs/AGENT_INTEGRATION.md`、`docs/AGENT_QUICKSTART.md`、`docs/AGENT_VERIFICATION.md`、README 截图说明；对 `docs/` 执行残留 grep 检查。
- [ ] 删除旧测试与 schema 快照中的 `career_*`，新增负向测试：`/api/save/*` 与 `/api/agent/v1/career/*` 旧路径返回 404、旧 MCP 工具不存在、旧 CLI 子命令不存在、旧 UI 入口不存在。
- [ ] 更新 ADR-0006、CHANGELOG 与 TODO 状态。
- [ ] 独立审核 PASS。

## Phase 1 领域模块

- [ ] catalog 与 scenario 纯领域模型。
- [ ] tactics 双阶段与职责校验。
- [ ] setpieces 模型与编码。
- [ ] pool 抽签、轮战、真实名单。
- [ ] roster 统一 23 人策略与确定性重映射。
- [ ] results 指标、配对、分布与 CSV。
- [ ] 每个模块的单元测试与性质测试。
- [ ] 独立审核 PASS。

## Phase 2 存储与引擎

- [ ] SQLite 连接、迁移与仓储：settings、saves、jobs、job_runs、drafts、pool_entries、artifacts、idempotency。
- [ ] 空库启动与只读旧目录探测。
- [ ] 原生宿主适配器与 counted-session 能力协商。
- [ ] 1–256 路调度、取消、续跑、磁盘/内存预检。
- [ ] 旧宿主回退到 64 场或执行力隔离模式，并记录 provenance。
- [ ] 并发验收矩阵：1、8、256 路提交、取消、续跑、结果身份一致。
- [ ] 真实引擎 Windows 验证脚本。
- [ ] 独立审核 PASS。

## Phase 3 接口

- [ ] FastAPI 路由、错误封套、分页、幂等。
- [ ] SSE 进度与轮询降级。
- [ ] 命令注册表，HTTP/CLI/MCP 全部由同一份定义生成。
- [ ] CLI 全功能命令与退出码。
- [ ] MCP tools/resources/prompts 全功能同步。
- [ ] OpenAPI 生成 TypeScript 类型与请求客户端。
- [ ] 契约测试：三入口能力对齐、schema 快照、错误码、幂等。
- [ ] 独立审核 PASS。

## Phase 4 桌面壳

- [~] Tauri 2 窗口、单实例、sidecar supervisor 已实现；文件对话框、打开数据目录、外部链接、托盘与自动更新待 Phase 4。
- [~] sidecar PyInstaller 打包脚本与 Tauri resources 已接入；Windows 安装包构建待 CI。
- [~] sidecar 启动、ready 行、健康检查、重启、优雅退出（静态实现；shell 复审与 Windows CI 待通过）。
- [~] token 生成、endpoint.json、Tauri `get_connection`、事件刷新（静态实现；待复审）。
- [ ] 文件对话框、打开数据目录、外部链接。
- [ ] 删除 Launcher.cs 与旧 C# 构建入口，并从 scripts/export_source.py 的 TOP 移除；同步 `docs/AGENT_INTEGRATION.md`、`docs/AGENT_VERIFICATION.md` 与 `THIRD_PARTY_NOTICES.md` 中的 Launcher 描述。
- [ ] Windows 安装包与卸载清理；CI 需执行 `tauri build` 验证 sidecar resources。
- [ ] 独立审核 PASS。

## Phase 5 UI

本阶段只做应用骨架、设计系统、页面框架与通用组件；Issue 行为在 Phase 6 作为增量实现，避免同一功能重复实现。

- [ ] React 应用骨架、路由、查询层、错误边界。
- [ ] 设计 token、字体、组件库与 FM 配色。
- [ ] 战术板双阶段与拖拽/键盘。
- [ ] 球员属性与隐藏属性分组。
- [ ] 存档战术库与真实 AI 生成。
- [ ] 结果页、对比、历史与批量管理。
- [ ] 设置、说明、空/加载/错误状态。
- [ ] Playwright 主流程与可访问性检查。
- [ ] 独立审核 PASS。

## Phase 6 功能请求

本阶段只实现 Issue/PR 的增量行为与验收；Phase 5 已完成的基础组件不重复开发。

### Issue #5 隐藏属性

上游：https://github.com/lqf0624/fm-tactics-lab/issues/5

- [ ] 批量设置默认只改可见能力属性；隐藏属性与左右脚默认保留。
- [ ] 技术/精神/身体/门将与隐藏/倾向分组，可分别启用与设值。
- [ ] 从参考球员复制隐藏属性与左右脚到全队/首发/当前球员。
- [ ] 左右脚按惯用脚与逆足配对，避免两脚同值。
- [ ] 提供撤销或恢复原值。
- [ ] 客队池统一属性使用同一策略；旧场景 schema 兼容。
- [ ] 测试覆盖分组、复制、配对、撤销、旧方案与客队池。
- [ ] 独立审核 PASS。

### Issue #6 批量管理

上游：https://github.com/lqf0624/fm-tactics-lab/issues/6

- [ ] `DELETE /api/jobs` 支持 `ids` 数组，返回 `{deleted, failed:[{id,error}]}`。
- [ ] 运行中或排队任务跳过并报告原因；单条失败不影响其余。
- [ ] 结果页与实验列表多选、全选、按状态筛选、删除所选。
- [ ] 二次确认列出名称/ID/场数；删除后刷新历史与当前选择。
- [ ] 旧单条删除接口回归或明确退役。
- [ ] 测试覆盖部分失败、运行中跳过、空选择、目录校验。
- [ ] 独立审核 PASS。

### Issue #7 统一 23 人

上游：https://github.com/lqf0624/fm-tactics-lab/issues/7

- [ ] `MATCH_ROSTER_SIZE = 23` 单点定义，移除 23/26 分支。
- [ ] 样本、存档、AI 生成、FMF、战术池与结果统计全部归一化。
- [ ] 确定性截断与重映射，覆盖首发、替补、门将、队长、主罚与定位球优先级。
- [ ] 不足 23 人的占位策略与 UI 提示。
- [ ] 旧 26 人方案加载兼容与提示。
- [ ] 测试矩阵覆盖 26→23、23→23、<23、只有 1 名门将、0 名门将、全部首发为 generated、引用被移除。
- [ ] 独立审核 PASS。

### PR #10 遗留功能

上游：https://github.com/lqf0624/fm-tactics-lab/pull/10

- [ ] 人类经理阵容自动读取：识别 managed club，读取当前/上一场 selection。
- [ ] 首发 11 人与替补按存档 selection 覆盖，保留战术与定位球；提供撤销。
- [ ] 导入存档后自动检测并提示；自动覆盖策略必须可配置或有明确确认。
- [ ] 结果页客队战术池卡片可折叠，显示条目数、模式、名单来源。
- [ ] 折叠状态在会话内保留；移动端/窄屏可用。
- [ ] 测试覆盖自动检测、首发/替补覆盖、撤销、折叠状态。
- [ ] 独立审核 PASS。

## Phase 7 收尾

- [ ] 删除存档对战的残留引用与旧构建入口。
- [ ] README 中英文重写并同步升级说明。
- [ ] DESIGN.md、DESIGN_SYSTEM.md、CHANGELOG.md、TODO.md 同步。
- [ ] 字体资产与 OFL 许可写入 THIRD_PARTY_NOTICES。
- [ ] 性能基准与并发对比。
- [ ] 安全与隐私检查。
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
