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
| 2026-11-13 | CLI HTTP 客户端与命令面 | client.py、cli.py、tests | FAIL | urllib 重定向把 Bearer 转发到任意主机；URL 错误回显 secret、userinfo 未拒、路径未编码。 |
| 2026-11-13 | CLI 修复轮 | 同上 | PASS | 拒绝全部重定向且不产生第二跳、URL 脱敏、userinfo 拒绝、路径 quote 与本地异常转 SidecarError、serve data-dir 优先级、jobs summary 切结果路由；100 项测试。 |
| 2026-11-13 | MCP stdio 协议层 | interfaces/mcp/protocol.py、tests | PASS | initialize/tools/list/tools/call、错误码、stdout 纯净与 handler 异常隔离闭合；修复轮补 RecursionError、严格 UTF-8 与 allow_nan。 |
| 2026-11-13 | MCP 工具面 | interfaces/mcp/tools.py、tests | PASS | 22 工具 schema 与路由契约一致、本地校验、路径编码、错误透传；77 项测试。 |
| 2026-11-13 | 结果与产物 HTTP | routes/results.py、artifacts.py、tests | FAIL | 下载端点无容器校验，DB 篡改或符号链接可读根外任意文件。 |
| 2026-11-13 | 结果与产物 HTTP 修复 | 同上 | PASS | 下载前容器 resolve、符号链接与相对路径拒绝；ETag 带引号、CSV 字节断言；负向测试四类。 |
| 2026-11-13 | 实验调度与并发预检 | domain/concurrency.py、application/experiments.py、tests | PASS | 1–256 校验、推荐值与资源预检、串行队列、逐场回写、取消/续跑与缺失场次过滤；124 项测试。 |
| 2026-11-13 | 前端结果页与存档库 | ResultsPage、LibraryPage、api.ts、tests | PASS | 指标/逐场/CSV 与存档 CRUD/导入/删除、状态齐全；56 项 Vitest、typecheck 与 build 通过。 |
| 2026-11-13 | SSE 事件流 | application/events.py、routes/system.py、tests | PASS | 发布器 id/历史/重放、SSE ready 与实时去重、keepalive、断连清理与鉴权闭合；断连测试恒真与重叠去重已修；9 项 MINOR 记录。 |
| 2026-11-13 | 设置与并发预检 HTTP | application/settings.py、routes/settings.py、tests | FAIL | 新增 PUT 路由未被 CORS allow_methods 覆盖，浏览器预检 400；另有 8 项 MINOR。 |
| 2026-11-13 | 设置修复轮 | 同上 | PASS | allow_methods 加 PUT 并补预检测试；字节上限度量口径统一；surrogate 与旧值保留补测；PUT 三 Origin 预检矩阵通过。 |
| 2026-11-13 | 幂等键中间件 | application/idempotency.py、interfaces/http/idempotency.py、tests | FAIL | 截断流式响应被缓存污染键；并发同键双执行副作用。 |
| 2026-11-13 | 幂等修复轮 | 同上 | PASS | Content-Length/204 完整判定、在途 asyncio 锁、鉴权前置、重复头保真与线程池执行；38 项测试；8 项 MINOR 记录。 |
| 2026-11-13 | MCP stdio 命令接线 | cli.py mcp、test_cli_mcp.py | PASS | 22 工具、stdout 纯净、启动失败退出码 1、health 就绪探测与 data-dir 优先级；11 项 MINOR。 |
| 2026-11-13 | 前端设置页 | SettingsPage、api.ts、tests | PASS | 设置 CRUD、JSON 校验、删除确认、并发预检面板；77 项 Vitest、typecheck 与 build 通过；11 项 MINOR。 |
| 2026-11-13 | 任务批量操作 HTTP | routes/jobs.py、test_http_jobs.py | PASS | 批量 cancel/delete、失败明细与顺序、边界与 OpenAPI；17 项 jobs HTTP 测试。 |
| 2026-11-13 | Issue 5 属性分组领域 | domain/attributes.py、tests | PASS | 六类分组互斥完整、half-up 对齐 Math.round、默认只改可见属性、快照精确恢复与参考复制、脚配对参数化；51 项测试；多轮 MINOR 收口。 |
| 2026-11-13 | Issue 6 批量删除与多选 | application/jobs.py、routes/jobs.py、JobsPage、tests | FAIL | 批删 get→delete 非原子可删运行中任务；确认框缺焦点与键盘语义。 |
| 2026-11-13 | Issue 6 修复轮 | 同上 | PASS | 服务层事务内 get→delete、DI 恢复、真实并发回归、焦点/Esc/结果聚焦与勾选收敛；后端 58 与前端 90 测试。 |
| 2026-11-13 | PR 10 客队战术池摘要 | application/results.py、routes/results.py、tests | PASS | enabled 语义、draws 零填充与 A/B 去重、优先级与 400/404 契约；69 项相关测试。 |
| 2026-11-13 | MCP 资源与提示词 | mcp/protocol.py、resources.py、prompts.py、cli.py、tests | PASS | capabilities 声明、resources/prompts 四方法、-32602 中文错误、通知静默与 stdout 纯净；提示词字段已按 v2 数据模型修正。 |
| 2026-11-13 | 实验调度 HTTP | routes/experiments.py、app.py、tests | PASS | submit/start/cancel/resume 状态码矩阵、引擎未配置 503、注入路径与 OpenAPI；17 项测试。 |
| 2026-11-13 | 球员属性页 | web PlayersPage、api.ts 草稿函数、tests | PASS | 六组索引与标签逐项对齐、显示换算、两段请求与缓存、隐藏开关与空/错态；116 项 Vitest。 |
| 2026-11-13 | 原生引擎适配器 | engine_native/host.py、capabilities.py、fake_simulator、tests | FAIL | 回调异常重复交付；原生 counted 能力分支零测试覆盖。 |
| 2026-11-13 | 原生引擎修复轮 | 同上 | FAIL | 兼容诊断中途失败绕过取消/终止，可无限阻塞并残留宿主进程。 |
| 2026-11-13 | 原生引擎终轮 | 同上 | PASS | 回调消费先记账、native 能力矩阵与 65 场 DW2 测试、兼容校验前置、_force_stop 清理与停滞宿主回归；131 项引擎测试。 |
| 2026-11-13 | 引擎并发分道 | host.py、test_engine_host.py | PASS | workers 1–256 分道、回调互斥、取消全道、跨道失败隔离、1/4/8 路结果身份一致；74 项引擎测试。 |
| 2026-11-13 | 三入口契约注册表 | registry.py、test_registry_contract.py | PASS | 41 能力与 OpenAPI/Typer/MCP 双向对齐、detect_drift 四类漂移、穷举删除/改名验证；7 项契约测试。 |
| 2026-11-13 | 运行时目录接口 | catalog_native、application/catalog.py、routes/catalog.py、tests | PASS | 三处查找顺序、损坏语义、字段裁剪、available=false 与 Bearer；42 项相关测试。 |
| 2026-11-13 | 战术板只读页 | TacticsPage、api.ts、tests | FAIL | 槽位重叠遮挡；指令与角色显示原生代码不可读。 |
| 2026-11-13 | 战术板修复轮 | 同上 | FAIL | 新引入 possession_phase 契约错配，有球阶段丢失 3 条指令。 |
| 2026-11-13 | 战术板终轮 | 同上 + catalog 接口 | PASS | 560px 球场与紧凑槽位消除重叠、catalog 中文标签与降级提示、possession_phase 过滤与 phase 回退回归测试；136 项 Vitest。 |
| 2026-11-14 | 存档读取适配器 | ports/save_reader.py、adapters/save_fmsave、tests | PASS | fmsave 惰性加载、69 属性布局与左右脚、personality 7 键、selection uid 映射、stat 变化拒绝；51 项测试；12 个变异被杀。 |
| 2026-11-14 | FMF 导入导出 | ports/fmf.py、adapters/fmf、routes/fmf.py、tests | FAIL | decode 对 KeyError/RecursionError 未收口，损坏文件返回 500。 |
| 2026-11-14 | FMF 修复轮 | 同上 | PASS | 异常收口统一 FMF 文件无效、非有限数拒绝、encode 保留 domain 语义、真实场景回归测试经变异验证；51 项相关测试。 |
| 2026-11-14 | 草稿属性批量编辑 | application/draft_attributes.py、routes、tests | PASS | scope/side 语义、bulk/position/copy/pair_feet/undo 复用领域、单槽快照与持久化；33 项相关测试；22 变异 18 被杀。 |
| 2026-11-14 | 存档导入与阵容同步 | save_import.py、routes、domain/roster.py、tests | FAIL | starters/bench 在含 generated 占位球员的草案下必然 400；写阶段回滚无测试；不可读路径 500；replace 清空联赛。 |
| 2026-11-14 | 存档导入修复轮 | 同上 | PASS | 新增 apply_roster_selection 按槽位保占位与重映射、触发器回滚测试、错误收口 400、leagues 保留、uid-only 身份索引；81 项相关测试，变异验证有效。 |
| 2026-11-14 | 属性批量编辑前端 | PlayersPage、api.ts、tests | PASS | bulk/position/copy/undo 参数与后端一致、失效刷新、错误展示、aria-live；142 项 Vitest；12 变异 11 被杀。 |
| 2026-11-14 | OpenAPI TypeScript 类型 | scripts/generate_web_types.py、api-schema.ts、tests | FAIL | 字节一致性测试在 CRLF checkout 下会失败。 |
| 2026-11-14 | 类型生成修复轮 | 同上 + .gitattributes | PASS | .ts/.tsx/.json/.yml 固定 LF、补排序与缺文件测试、重生成 56 schema；1425 项全量。 |
| 2026-11-14 | CLI 全量命令 | cli.py、client.py、registry.py、tests | PASS | 26 命令与 49 能力逐一对应、路径/方法/query/body 与路由一致、三个下载命令按 --output 写文件、退出码 0/1/2 与 token 脱敏；196 项定向测试、1631 项全量、11 个变异全被杀；3 项 MINOR 为下载原子性与测试结构建议。 |
| 2026-11-14 | MCP 工具面补齐 | interfaces/mcp/tools.py、tests | PASS | 48 工具与 OpenAPI 逐项对齐、下载工具 base64 封套往返、本地校验中文错误、路径编码与 SidecarError 透传；175 项定向、1631 项全量、13 个变异被杀；4 项 MINOR 为可空 body 与上界覆盖缺口。 |
| 2026-11-14 | 存档库导入与阵容面板 | LibraryPage、api.ts、tests | PASS | 文件导入/覆盖导入/俱乐部与名单展示/阵容同步与撤销全链路，409 与错误态、aria 状态；157 项 Vitest、typecheck 与 build 通过；3 项测试覆盖 MINOR 已补。 |
| 2026-11-14 | 结果对比后端 | domain/compare.py、application/results.py、routes/results.py、cli.py、mcp/tools.py、registry.py、tests | FAIL | 首轮 CompareInput 缺严格模型导致字符串数字与未知字段被静默接受；ID 边界 128 与仓储 64 不一致并返回错域文案；alpha 行为、entries 权重与名单差异、HTTP 不可比响应缺测试。 |
| 2026-11-14 | 结果对比后端修复轮 | 同上 | PASS | strict+extra=forbid 与 additionalProperties=false 断言、ID 统一 1–64 且 MCP baseline 对齐、alpha 区间性质、entries weight/roster 判别、HTTP 不可比 paired=null 与非默认参数透传；1746 项全量、5 变异全部被杀。 |
| 2026-11-14 | 结果对比前端 | ResultsPage.tsx、api.ts、extra.css、tests | FAIL | 参数变化清空与陈旧响应防护缺少判别性测试，删除请求守卫或 clearCompare 后 35 项仍全过；另有禁用态、区间格式与长文本 MINOR。 |
| 2026-11-14 | 结果对比前端修复轮 | 同上 | PASS | 补迟到旧响应不覆盖新一轮状态、切变体清空且切回不复活两个用例，守卫与 clearCompare 变异均被杀；禁用候选视觉、区间括号格式与换行修复；169 项 Vitest、typecheck 与 build 通过。 |
| 2026-11-14 | 原生场景编码器与定位球领域 | domain/setpieces.py、engine_native/scenario_assets.py、scenario_codec.py、tests | FAIL | relative 编码只断言等于基线，缺少任何差量；对方战术 (20)/(21) 两模式未测发射，差量作用域变异存活。 |
| 2026-11-14 | 编码器测试修复 | tests/test_scenario_codec.py | PASS | 补 12 项 relative 精确差量与对方战术双模式测试，18 项旧测试逐字保留；12 个等效变异全部被杀，实现未改。 |
| 2026-11-14 | 客队池 schema 与整批展开 | domain/pool.py、tests | FAIL | 只支持单 seed 展开，轮战恒抛错；24–26 人名单在校验层接受但应用层拒绝，与 ADR-0005 归一化冲突。 |
| 2026-11-14 | 客队池修复轮 | domain/pool.py、tests | PASS | 整批 expand_away_scenarios 一次抽签逐场展开并委托单 seed；24–26 走 normalize_roster 裁剪附 roster_trim、generated 占位保留、缺门将中文提示；6 变异全杀。 |
| 2026-11-14 | 结果页批量管理与池折叠 | ResultsPage.tsx、ResultsPage.test.tsx、extra.css | FAIL | 删除后切换与重置缺少判别性测试，测试从未先选中任务；aria-busy 与池折叠损坏容错有缺口。 |
| 2026-11-14 | 结果页修复轮 | 同上 | PASS | 补显式查看任务后删除并断言切换首个、分页归零、对比候选与对比表清空；aria-busy、sessionStorage 损坏容错；185 项 Vitest，7 变异 6 杀且 clearCompare 判等价。 |
| 2026-11-14 | 实验链路接线 | application/experiment_material.py、application/experiments.py、application/jobs.py、routes/experiments.py、app.py、cli.py、mcp/tools.py、tests | FAIL | submit 物化窗口内并发 start/cancel/delete 会让任务在无 materialized config 时以默认场景静默运行并产出错误结果；set_config 不在清理路径内导致 job 与物化目录残留；配置 materializer 时缺配置仍回退空场景；任务删除不清理物化目录；MCP seeds 缺 maxItems/uniqueItems。 |
| 2026-11-14 | 实验接线修复轮 | application/experiments.py、jobs.py、experiment_material.py、app.py、mcp/tools.py、tests | PASS | submit 持锁覆盖 create→物化→set_config→summary；异常路径删 job 与物化目录后原样重抛；缺 materialized 配置显式报错不回退空场景；JobService cleanup 回调只对成功删除生效；root containment 与 MCP seeds 约束到位；6 变异全杀、1977 项全量；2 Important 与 3 Minor 为测试判别力缺口。 |
| 2026-11-14 | 实验接线测试缺口修复 | tests/test_experiment_material.py、test_experiments_service.py | PASS | 补同前缀兄弟目录、discard 符号链接逃逸、BaseException 清理、清理异常不掩盖原异常、summary 返回 None 共 8 用例；5 条存活变异全部被杀，实现未改；1990 项全量。 |
| 2026-11-14 | 实验接线测试缺口复核 | 同上 | PASS | 5 条存活变异全部被新用例杀死（前缀兄弟目录、discard 符号链接、BaseException 清理、清理异常不掩盖、summary 返回 None），逐字节恢复；旧用例未被削弱，实现零改动；1990 项全量。 |
| 2026-11-14 | 宿主资源探测 | adapters/host_resources.py、routes/system.py、registry.py、cli.py、tests | PASS | CPU/内存/磁盘三策略与中文错误、503 封套 resource_probe_failed、51 能力注册与 CLI system resources、CLI 自动预填三资源；7 核心变异被杀、1977 项全量；4 项 Minor 为测试判别力缺口。 |
| 2026-11-14 | 宿主资源测试缺口修复 | tests/test_host_resources.py、test_cli_commands.py | PASS | 补 meminfo 负值不回退、负值转 sysconf、非对象探测响应、cpu_count=0、缺字段共 5 用例；M8–M11 四条存活变异全部被杀、实现未改；1982 项全量。 |
| 2026-11-14 | 实验提交页面 | ExperimentsPage.tsx、ExperimentsPage.test.tsx、App.tsx、Rail.tsx、api.ts、extra.css | FAIL | 启动结果展示的是最早排队任务却挂在刚提交任务卡片内且不显示任务身份，会误导；手改并行数不被回填、预检随 workers/资源变化触发均无判别性测试；另有名称上限、aria 关联、复选框样式与 warnings 展示等 MINOR。 |
| 2026-11-14 | 实验提交页面修复轮 | ExperimentsPage.tsx、ExperimentsPage.test.tsx、extra.css | PASS | 启动结果改为独立同级区域并展示任务名、ID、总场数与更早任务提示；名称上限纳入提交禁用、草案选择框 aria 关联、复选框移出 field、预检 warnings 常显；12 变异全杀、36 项用例、221 项 Vitest。 |
| 2026-11-14 | 实验提交页面结构断言补强 | ExperimentsPage.test.tsx | PASS | 新增启动结果与实验任务区同级不嵌套的结构断言、仅磁盘变化重新预检、提示全文锁定、重提交清空启动结果、草案 select 空错误路径共 5 用例；5 变异全杀、实现零改动、226 项 Vitest。 |
| 2026-11-14 | 实验提交页面补强复核 | 同上 | PASS | 独立重做 5 条必杀变异与 4 条自设结构变异全部被杀，旧 36 条套件对同类缺陷仍全绿；反向删除还原原始 sha256、纯增量；226 项 Vitest、typecheck 与 build 通过；3 项 MINOR 为同类单字段缺口与断言过严。 |
| 2026-11-14 | Launcher 退役 | Launcher.cs、scripts/build_exe.py、export_source.py、test_workspace_scripts.cjs、docs/DEVELOPMENT.md、docs/AGENT_INTEGRATION.md、docs/AGENT_VERIFICATION.md、THIRD_PARTY_NOTICES.md | PASS | 删除 C# Launcher 与 csc 构建入口，导出白名单、构建文档、代理集成与第三方声明同步为 Tauri 壳与 sidecar；unittest 281 项与两个 node 测试通过、导出 368 文件不含被删入口、变异证明残留断言仍具判别力；越界 v1 残留列入后续文档切片。 |
| 2026-11-14 | 实验提交页面预检单字段补测 | ExperimentsPage.test.tsx | PASS | 补 CPU 与可用内存各一条单字段用例，三条 queryKey 字段变异分别被对应用例杀死、基线 41 条在同变异下全绿；反向删除还原原始 sha256、纯增量；228 项 Vitest、typecheck 与 build 通过；MINOR 为子串断言可被超串满足与连接字段既有盲区。 |
| 2026-11-14 | 文档对齐 v2 事实 | docs/AGENT_QUICKSTART.md、docs/AGENT_INTEGRATION.md、docs/AGENT_VERIFICATION.md、src/desktop_locale.py、src/fm27_agent_contract.py、src/tactics_ui/i18n-en.js | FAIL | 三份接入文档整体重写并与代码逐条核对，25 条抽样断言与 12 条 v1 退场结论成立；唯一 IMPORTANT 为幂等风险表把 SQLite 持久化记录误写为进程内、重启失效，另有 7 项 MINOR 为引擎目录错误混同、MCP 启动文案标点、工具分组计数、token 格式、系统接口归类与证据行号。 |
| 2026-11-14 | 文档对齐修复轮 | 同上 | PASS | I-1 改为持久化幂等（主键唯一、payload 指纹校验、跨重启有效、同库多进程共享、单进程 asyncio.Lock），并补真实剩余风险“无定时 prune”；7 项 MINOR 全部逐条修正并经复审实测确认；标题无括号、无未发生审核声称、node 测试与 281 项 unittest 通过；遗留 MINOR 为种子错误文案与证据区间。 |
| 2026-11-14 | 前端 API 类型统一到生成 schema | web/src/lib/api.ts、web/src/lib/api-schema.ts、web/src/lib/api-types.test.ts、fm27lab/interfaces/http/routes/jobs.py、routes/saves.py、fm27lab/tests/test_http_output_status_enums.py | PASS | 67 个类型中 40 项改为生成接口别名、2 项派生、25 项保留手写并记录理由；JobOutput 与 SaveOutput 收紧为 Literal 且与 TRANSITIONS/SAVE_STATUSES 联动，输入模型保持 str 以防 400 文案变化；页面零改动、37 个函数签名与路径字节不变、api-schema diff 恰 2 行；10 变异 8 杀，2 条存活为刻意构造且无实际语义危害；234 项 Vitest。 |
| 2026-11-14 | 前端类型测试补强 | web/src/lib/api-types.test.ts | PASS | 新增剥 `//` 注释后断言别名、`from "./api-schema"` 子句与 import 组各恰 1 且 specifier 集合严格相等；注释伪造别名与额外导入两条变异由存活转为被杀；残留 MINOR 为块注释伪造仍可存活。 |
| 2026-11-14 | 原生引擎生产接线与按任务并行数配置 | fm27lab/adapters/engine_native/lazy.py、host.py、fm27lab/application/experiments.py、fm27lab/interfaces/http/app.py、fm27lab/tests/test_lazy_engine.py、test_engine_host.py、test_experiments_service.py、test_http_experiments.py | PASS | 引擎解析顺序为注入 engine > engine_root 惰性宿主 > 未配置占位；LazyNativeEngine 双检锁构造且 factory 失败不缓存；运行时计划兼容零参可调用并在创建任务前解析；start_next 置 running 后、run_batch 前调用 configure_workers；HTTP 端到端以 fake_simulator 完成草案提交到 4 场结果且 config 为绝对路径 FM27CFG1 文件；16 变异 14 杀，2 条判定等价；2037 项 pytest。 |
| 2026-11-14 | 接线测试补强 | fm27lab/tests/test_experiments_service.py、test_lazy_engine.py | PASS | 新增 configure_workers 回调内读取任务状态断言 running 且序列早于 run_batch、factory 前两次失败不留半初始化缓存且第三次成功两条判别用例；对应两处变异被杀；2039 项 pytest、ruff 与类型生成检查通过。 |
| 2026-11-14 | 双阶段战术校验接线 | adapters/catalog_native/catalog.py、application/tactics_validation.py、application/drafts.py、interfaces/http/app.py、tests | FAIL | load_document 保留原始节与候选顺序、目录缺失或不可解析时跳过、双队与 create/update 覆盖均正确，真实 create_app 47 项探针通过且 OpenAPI 与 /api/catalog 逐字节不变；3 项 Important 全为测试判别力缺口：校验修改入参、PATCH 被拒后草案未变、POST 被拒未落库三个变异存活，22 变异 19 杀。 |
| 2026-11-14 | 双阶段战术校验测试修复轮 | tests/test_tactics_validation.py、test_http_drafts.py | PASS | 客队计划改为可区分并断言顺序不变、PATCH 被拒后场景深相等、POST 被拒后 total 为 0、坏目录跳过校验参数化用例；四变异全杀，实现零改动，2074 项 pytest。 |
| 2026-11-14 | 战术板编辑与键盘操作 | web/src/pages/TacticsPage.tsx、TacticsPage.test.tsx、styles/extra.css | PASS | 编辑模式与本地深拷贝、拖拽与键盘交换首发、roving tabindex 与坐标导航、按阶段角色编辑、保存/放弃/脏态保护与 aria-live 播报；22 变异 19 个有效变异全杀，252 项 Vitest 连跑两次、typecheck 与 build 通过；Minor 为触屏拖拽、真实浏览器布局与 catalog 角色 phase 类型滞后。 |

## 审核规则

- 审核者不得修改文件、不得执行 Git 写操作。
- 审核范围必须明确到提交、工作树或文件集合。
- 先列 findings，再列已验证项，最后给结论。
- Critical 或 Important 未闭环时不得标记 PASS。
- 审核通过不等于整体发布就绪；发布仍需最终验收与 Windows 真机验证。
- 旧 `tests/` 当前 281 项通过，覆盖 legacy UI/HTTP/CLI/MCP、存档战术库、池与名单；新 `fm27lab/tests` 当前 2074 项通过，覆盖包版本、CLI 环境继承、配置/路径边界、SQLite 迁移/事务与池/草案/任务/存档/产物/幂等仓储、HTTP 健康/池/草案/任务 CRUD、鉴权、错误封套、Origin、ACL 失败清理、sidecar serve、23 人名单、真实名单应用、scenario 归一化、原生场景编码与定位球记录、场景物化与实验接线、原生宿主按需构造与按任务并行配置、宿主资源探测、catalog/双阶段战术与草案写入校验、客队战术池选择与整批展开、结果指标与跨任务对比、任务状态机与输出状态枚举、存档状态机与应用服务；Vitest 当前 252 项。
- Tauri sidecar supervisor 的静态实现已存在，但 Linux 无 WebKitGTK，Windows CI 的 `cargo build`/`cargo test`/安装包构建是唯一编译证据。PyInstaller onedir sidecar 已在 Linux 构建并通过 ready/health/shutdown 冒烟测试。
- Rust 核心 crate 当前 4 项 cargo test 通过；前端当前 252 项 Vitest（10 个文件）通过、类型检查与生产构建通过。Windows CI 已通过 cargo build/test、NSIS 安装包与 sidecar 资源断言；Linux 本机仍无 WebKitGTK。合并、设计、sidecar、壳层、名单五个审核门均已 PASS。
