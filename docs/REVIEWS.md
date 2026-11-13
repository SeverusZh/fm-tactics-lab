# 独立审核记录

每个任务必须由独立审核子代理只读审查，并给出明确 PASS 或 FAIL。FAIL 的必须修复后复审。

| 日期 | 任务 | 审查范围 | 结论 | 主要发现 |
| --- | --- | --- | --- | --- |
| 2026-11-12 | 合并上游 v1112 | 提交 `0c24c66` | FAIL | 首轮：Agent 并行上限仍为 4、APP_VERSION 仍为 1111.2、i18n 重复键、文档漂移、SOURCE_MANIFEST 过期。 |
| 2026-11-12 | 设计文档与 ADR | DESIGN、TODO、README、CHANGELOG、ADR、设计系统 | FAIL | 首轮：CHANGELOG 把计划写成完成；三入口契约矛盾；删除存档对战未前置；导出脚本不覆盖 v2；端口、23 人、并发、Issue 验收、设计 token、字体与前端契约不足。 |
| 2026-11-12 | 设计文档第二轮 | 同上 | FAIL | 第二轮：Phase 0.5 遗漏 Agent career 路由与 AGENT_VERIFICATION；导出二进制校验会读文本；无桌面 CLI/MCP 与系统路由未定义；1–256 与 409 冲突；23 人门将/占位/位置边界；pyproject 缺 fmsave；Launcher 文档；若干 Minor。 |
| 2026-11-12 | 合并第二轮 | 工作树 vs `0c24c66` | FAIL | 第二轮：Agent 文档 adapter 版本仍为 27.0.0+2493426；mock manifest max_workers 仍为 4；README 版本语义需说明。 |
| 2026-11-12 | 设计文档第三轮 | 同上 | FAIL | 第三轮：资源预检措辞、开发 CORS、SSE Bearer 鉴权、pyproject 入口、README 英文预检、系统路由例外、审核记录；已修复。 |
| 2026-11-12 | 设计文档第四轮 | 同上 | FAIL | 第四轮：`rust/` 工作区未纳入 DESIGN/TODO/导出 allowlist；Rust 模块当时缺失；未忽略 target；第四轮未记录。已修复。 |
| 2026-11-12 | 合并第三轮 | 工作树 vs `0c24c66` | PASS | adapter 版本、mock 清单、README 版本语义与 SOURCE_MANIFEST 已闭环；仅剩计数与 i18n 断言健壮性等 Minor。 |
| 2026-11-12 | 设计文档第五轮 | 同上 | FAIL | 第五轮：`/api/version` 与 `/api/docs` 未纳入系统路由规则；401 错误封套缺 `details`/`retry_after_seconds`；SSE 占位未说明。已修复。 |
| 2026-11-12 | 设计文档第六轮 | 同上 | FAIL | 第六轮：`/api/version`/`/api/docs` 与错误封套已闭环；但 `test_serve.py` 未进入 manifest、React 窄屏导航无可访问名称、pnpm 缓存未忽略、设计 token 缺口。已修复。 |
| 2026-11-12 | sidecar 基础切片 | fm27lab/ 与 pyproject.toml | FAIL | 首轮：迁移非原子、health 误报空库、404/405/500 错误封套缺失、SQLite 连接未确定性关闭、缺少服务端 Origin 校验、测试覆盖不足、Settings repr 泄露 token。已修复。 |
| 2026-11-12 | 设计文档第七轮 | 同上 | FAIL | 第七轮：`::1` 合法但 sidecar 只绑定 IPv4；Windows endpoint ACL 未收紧；radius-tag/text-wrap/数字输入等 Minor。已修复。 |
| 2026-11-12 | 设计文档第八轮 | 同上 | FAIL | 第八轮：Tauri 安装包无 sidecar 资源/构建；supervisor 无健康检查/自动重启/退出清理；window minWidth 与 1024 断点冲突；CSP null；无 Cargo.lock 与 src-tauri 测试；ACL 失败残留。已修复，待第九轮复审。 |
| 2026-11-12 | 设计文档第九轮 | 同上 | FAIL | 第九轮：manifest 仍缺 5 个新文件；React 未监听 Tauri 事件；重复 ready/计数；src-tauri 进程测试不足；Windows CI 未运行。已修复/待复审。 |
| 2026-11-12 | 设计文档第十轮 | 同上 | FAIL | 第十轮：tauri.conf.json 重复 frontendDist 导致无效 JSON；文档声称文件对话框已实现但代码无插件/权限；minWidth 1000 与 1024 不一致；测试计数滞后；Windows CI 未运行。已修复。 |
| 2026-11-12 | 设计文档第十一轮 | 同上 | PASS | JSON/CI/manifest/React 事件/supervisor/CSP/资源/构建命令/ACL 均闭环；无 Critical/Important。Windows CI 与 Tauri 编译/NSIS/真机仍为发布门槛。 |
| 2026-11-12 | sidecar 基础切片复审 | 同上 | FAIL | 复审：CLI 丢弃 FM27LAB_DEV、空 FM27LAB_DATA 落到 CWD、迁移拆分不支持一行多语句、wheel 无 fm27lab 入口；另有 upsert/错误封套测试不足。已修复。 |
| 2026-11-12 | sidecar 基础切片第三轮 | 同上 | PASS | 27 项测试通过；I1-I4 全闭环；剩余路径别名/CLI host-port/迁移排序/测试超时等 Minor，已继续修复；当前 28 项。 |
| 2026-11-12 | React/Tauri 壳层 | web/、src-tauri/、CI | FAIL | 首轮：CSP 阻断 IPC、Child 移出共享状态、退出不等待、前端未监听事件、before 命令工作目录、resources 映射、启动超时、运行期健康、stderr、CI 与前端测试不足。 |
| 2026-11-12 | React/Tauri 壳层第二轮 | 同上 | FAIL | 第二轮：CSP IPC 与前端事件已修；但 stop_sidecar 有确定的 Rust 编译错误、stopping/restart 竞态、健康检查误杀新 child、启动失败 endpoint 残留、TopBar 无条件重启、双重启动、minWidth 与测试缺口。已修复。 |
| 2026-11-12 | React/Tauri 壳层第三轮 | 同上 | FAIL | 第三轮：stop 编译错误已修、stopping/健康误杀/TopBar/minWidth/CSP/endpoint 主路径已闭环；但 dead-child 上限仍 return、restart 与 monitor backoff 仍可能双启、supervisor 竞态测试与 Windows 编译证据缺失。已修复并发问题，待复审。 |
| 2026-11-12 | React/Tauri 壳层第四轮 | 同上 | FAIL | 第四轮：dead-child paused 与 stop 编译已修；但 should_start 与 start_sidecar 仍有 TOCTOU、restart/backoff 双启、supervisor 竞态测试与 Windows 证据缺失。已修复 start_allowed 锁内门禁。 |
| 2026-11-12 | React/Tauri 壳层第五轮 | 同上 | PASS | start_allowed 锁内门禁、dead-child paused、stop/health 竞态、endpoint 清理、TopBar/RunBar、CSP/minWidth/resources 均闭环；Windows CI run 43252465016 全绿，NSIS artifact 已生成。剩余仅显式 restart 覆盖 monitor 的罕见顺序与安装后真机 QA，作为 Minor/发布门槛。 |
| 2026-11-12 | Windows 构建门槛 | GitHub Actions run 43252465016 | PASS | 全 job success：sidecar PyInstaller、Python、cargo build、cargo test、tauri build --bundles nsis、sidecar 资源断言、NSIS artifact 上传；安装包约 19.6 MB。 |
| 2026-11-12 | 23 人名单领域 | fm27lab/domain/roster.py、tests | FAIL | 首轮：索引用作 uid、位置分组偏离 ADR、首发可含 2 GK、GK 未按熟练度、generated 全判 GK/隐藏值错误、ability 含隐藏属性、uid 排序/唯一性、默认主罚缺位置资格、测试恒真断言。已重写。 |
| 2026-11-12 | 23 人名单领域第二轮 | 同上 | FAIL | 第二轮：GK fill 仍可加入 2 名门将且未用熟练度；可见属性 41 漏算；测试仍有恒真断言与缺口。已修复并扩至 25 项测试。 |
| 2026-11-12 | 23 人名单领域第三轮 | 同上 | FAIL | 第三轮：短名单 fallback 仍可把第二 GK 加回首發；测试未覆盖短名单。已修并补测试。 |
| 2026-11-12 | 23 人名单领域第四轮 | 同上 | FAIL | 第四轮：bench fill 也限制 1 GK，23→23 时真实 GK 被 generated 替代；显式多 GK lineup 未归一化。已修。 |
| 2026-11-12 | 23 人名单领域第五轮 | 同上 | PASS | bench 不限 GK、显式多 GK 归一化、短名单/23+3GK 保留、starter padding 均闭环；31 项领域测试（复审时 29）+ full 59；仅剩 Minor 断言/策略说明。 |
| 2026-11-12 | 存档对战退役 | UI/HTTP/CLI/MCP/schema/docs | FAIL | 首轮：Launcher 自检仍请求 save-mode；workspace-controls 与 desktop-workspace 顶层 const 重名；squad 严格模式未声明赋值；根 tests 仍有 save 用例失败；文档残留。 |
| 2026-11-12 | 存档对战退役第二轮 | 同上 | FAIL | 第二轮：核心修复通过，但工作树 manifest 未同步且 CI 会失败。已重新生成 manifest。 |
| 2026-11-12 | 存档对战退役最终 | 同上 | PASS | Launcher/workspace 资源、跨脚本重声明、squad 严格模式、根 tests 281、v2 59、unittest 281、manifest 232、文档与死代码清理均闭环。 |
| 2026-11-12 | 客队战术池领域 | fm27lab/domain/pool.py、tests | FAIL | 首轮：轮战重复 seed 静默折叠、完成计数 seed 类型缺失、summary 契约不全、加权/A-B 测试恒真。 |
| 2026-11-12 | 客队战术池领域第二轮 | 同上 | FAIL | 第二轮：draws 绕过 128/10000 限制；加权测试仍无法区分 3:1 与 1:1。 |
| 2026-11-12 | 客队战术池领域第三轮 | 同上 | PASS | 128/10000 限制、重复 seed、加权 4000 seed 比例、summary profile/enabled/rounds/uniform、完成计数 seed 校验均闭环；15 项测试。 |
| 2026-11-12 | 真实名单应用 | fm27lab/domain/roster.py、tests | FAIL | 首轮：输出继承 host ability/generated/额外字段；truthy generated、UID 控制字符、unhashable lineup 未受控。 |
| 2026-11-12 | 真实名单应用第二轮 | 同上 | PASS | saved 球员为基座、仅附加 host native_id；23 人、generated/UID/lineup/ability/native_profile/引用组边界闭环；16 项测试。 |
| 2026-11-12 | 结果指标领域 | fm27lab/domain/results.py、tests | FAIL | 首轮：side=1 只换进球、未换胜平负/积分/Wilson；配对差无 side；测试方向恒真。 |
| 2026-11-12 | 结果指标领域第二轮 | 同上 | FAIL | 第二轮：传球字段部分缺失被伪造成 0.0；边界测试不足。 |
| 2026-11-12 | 结果指标领域第三轮 | 同上 | PASS | side 取向、Wilson、xG/xGA、配对方向、传球缺失/NaN/零值语义闭环；8 项测试。 |
| 2026-11-12 | Scenario 归一化 | fm27lab/domain/scenario.py、tests | FAIL | 首轮：非法球员条目崩溃、输出共享嵌套对象、引用测试恒等、roster_trim 缺失。 |
| 2026-11-12 | Scenario 归一化第二轮 | 同上 | PASS | 深拷贝、非恒等引用、非法输入、roster_trim、substitutes 重写闭环；9 项测试。 |
| 2026-11-12 | Catalog 与双阶段战术 | fm27lab/domain/tactics.py、tests | FAIL | 首轮：使用平面 role_eligibility，放行上下文不可用角色；畸形 catalog TypeError、完整性缺口。 |
| 2026-11-12 | Catalog 与双阶段战术第二轮 | 同上 | PASS | role_eligibility_context 四桶分桶、上下文覆盖、严格 catalog、2×11/职责/指令/盯防与归一化测试闭环；13 项测试。 |
| 2026-11-12 | SQLite 客队池仓储 | repositories.py、tests | FAIL | 首轮：NaN 可落库、事务接口不对称、128 上限未执行；第二轮：并发可突破上限。 |
| 2026-11-12 | SQLite 客队池仓储终轮 | 同上 | PASS | JSON allow_nan/UTF-8、事务读己之写、BEGIN IMMEDIATE 单条原子上限、rowid 排序与并发测试闭环；11 项测试。 |
| 2026-11-12 | Sidecar 池 HTTP | app.py、tests | FAIL | 首轮：路径 id 可创建不可寻址、OpenAPI 无 Bearer/响应模型、Pydantic 宽松转换；次轮：422/405/分页 schema/清单。 |
| 2026-11-12 | Sidecar 池 HTTP 终轮 | 同上 | PASS | URL-safe id、HTTPBearer、strict body、PoolService 注入、分页 items/total/next_offset、错误封套/422/405/OpenAPI defaults 闭环；12 项测试。 |
| 2026-11-12 | Drafts 仓储与服务 | repositories.py、application/drafts.py、tests | FAIL | 首轮：update 非原子、名称 surrogate、测试只验返回值、列表排序违约。 |
| 2026-11-12 | Drafts 仓储与服务终轮 | 同上 | PASS | BEGIN IMMEDIATE/rowcount、UTF-8 名称、updated_at 倒序、持久化/回滚/分页测试闭环；7 项测试。 |
| 2026-11-12 | Drafts HTTP | app.py、tests | FAIL | 首轮：CORS 缺 PATCH，预检 400；PATCH scenario/注入/OpenAPI 测试不足。 |
| 2026-11-12 | Drafts HTTP 终轮 | 同上 | PASS | CORS PATCH、严格 body、23 人 PATCH、分页、注入、OpenAPI security/错误封套闭环；6 项测试。 |
| 2026-11-12 | Jobs 仓储 | repositories.py、tests | FAIL | 首轮：created_at 假值、status 不可哈希、单边比分、回滚/重复键测试缺口。 |
| 2026-11-12 | Jobs 仓储终轮 | 同上 | PASS | 时间/状态/比分不变量、BEGIN IMMEDIATE 更新、runs 顺序/级联/回滚与测试闭环；7 项测试。 |
| 2026-11-13 | Saves 仓储 | saves.py、tests | PASS | 20+5 项测试；事务、级联、确定性重复映射与 UTC 时间规范化闭环；C1 与回滚覆盖 MINOR 已在修复轮补齐。 |
| 2026-11-13 | 产物与幂等仓储 | artifacts.py、idempotency.py、tests | FAIL | prune 以 ISO 字符串字典序比较，跨时区与等值输入会误删漏删；另有外键判定、C1 控制字符与排序 MINOR。 |
| 2026-11-13 | 产物与幂等仓储修复 | 同上 | PASS | prune 规范化 UTC 后比较并拒绝 naive；四类时区与等值场景独立复现通过；C1、sqlite_errorname、created_at 规范化与并发异 hash 补齐；仅 3 项 MINOR。 |
| 2026-11-13 | Jobs 仓储计数与服务 | repositories.py、application/jobs.py、tests | PASS | 状态机、时间戳、append_run 原子回滚与并发唯一序号闭环；36 项相关测试；3 项 MINOR 为既有契约与理论竞态。 |
| 2026-11-13 | Saves 应用服务 | application/saves.py、tests、count | PASS | 状态机、import_payload 四路回滚、分页信封与事务原子闭环；72 项相关测试；4 项 MINOR。 |
| 2026-11-13 | Jobs HTTP | app.py、test_http_jobs.py | PASS | 7 条路由鉴权、404/409/分页、OpenAPI 与 CORS 不回归；409 判定先于写入；4 项 MINOR。 |
| 2026-11-13 | 结果与产物应用服务 | application/results.py、artifacts.py、tests | FAIL | artifacts 的 kind 目录符号链接可逃逸 root；register_text 孤立代理项英文异常；另有两项测试缺口。 |
| 2026-11-13 | 结果与产物修复 | 同上 | PASS | kind 目录 resolve containment、root 内符号链接只删链接本身、UTF-8 错误转中文、CSV 非 JSON 字段转义与 all_runs 整页边界补齐；仅理论 TOCTOU 与目录 fsync 为可接受风险。 |
| 2026-11-13 | HTTP 路由模块化与存档接口 | app.py、common.py、routes/、test_http_saves.py | PASS | 旧新 OpenAPI 与响应快照对比行为不变；saves CRUD 与 import 分页、409/404/400 分界与回滚正确；2 项 MINOR 为超大 club_uid 500 与消息文案耦合。 |
| 2026-11-13 | 引擎能力协商与运行时计划 | ports/engine.py、engine_native/capabilities.py、tests | PASS | 能力缺省回退、四运行时矩阵、provenance 五键与 Protocol 结构均闭环；62 项测试。 |
| 2026-11-13 | 前端任务管理页 | web/src jobs 客户端与 JobsPage | PASS | 22 项 Vitest、类型检查与构建通过；列表/筛选/分页/取消/删除/创建与错误态齐全；MINOR 为手写类型与末页空页。 |

## 审核规则

- 审核者不得修改文件、不得执行 Git 写操作。
- 审核范围必须明确到提交、工作树或文件集合。
- 先列 findings，再列已验证项，最后给结论。
- Critical 或 Important 未闭环时不得标记 PASS。
- 审核通过不等于整体发布就绪；发布仍需最终验收与 Windows 真机验证。
- 旧 `tests/` 当前 281 项通过，覆盖 legacy UI/HTTP/CLI/MCP、存档战术库、池与名单；新 `fm27lab/tests` 当前 358 项通过，覆盖包版本、CLI 环境继承、配置/路径边界、SQLite 迁移/事务与池/草案/任务/存档/产物/幂等仓储、HTTP 健康/池/草案/任务 CRUD、鉴权、错误封套、Origin、ACL 失败清理、sidecar serve、23 人名单、真实名单应用、scenario 归一化、catalog/双阶段战术、客队战术池选择、结果指标、任务状态机、存档状态机与应用服务；Vitest 当前 9 项。
- Tauri sidecar supervisor 的静态实现已存在，但 Linux 无 WebKitGTK，Windows CI 的 `cargo build`/`cargo test`/安装包构建是唯一编译证据。PyInstaller onedir sidecar 已在 Linux 构建并通过 ready/health/shutdown 冒烟测试。
- Rust 核心 crate 当前 4 项 cargo test 通过；React 壳当前 9 项 Vitest 通过、类型检查与生产构建通过。Windows CI 已通过 cargo build/test、NSIS 安装包与 sidecar 资源断言；Linux 本机仍无 WebKitGTK。合并、设计、sidecar、壳层、名单五个审核门均已 PASS。
