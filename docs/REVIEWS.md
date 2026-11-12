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
| 2026-11-12 | React/Tauri 壳层第五轮 | 同上 | 待审 | 等待 shell-reviewer 第五轮结果。 |
| 2026-11-12 | Windows 构建门槛 | GitHub Actions run 43249250613 | PASS（构建） | sidecar PyInstaller、Python 28 项、cargo build、cargo test、tauri build --bundles nsis 全部成功，安装包 18.68 MiB；frontend 仅 Post cache 失败，已移除缓存；sidecar 资源路径断言待新 run。 |
| 2026-11-12 | 23 人名单领域 | fm27lab/domain/roster.py、tests | FAIL | 首轮：索引用作 uid、位置分组偏离 ADR、首发可含 2 GK、GK 未按熟练度、generated 全判 GK/隐藏值错误、ability 含隐藏属性、uid 排序/唯一性、默认主罚缺位置资格、测试恒真断言。已重写。 |
| 2026-11-12 | 23 人名单领域第二轮 | 同上 | 待审 | 等待 roster-reviewer 第二轮结果。 |

## 审核规则

- 审核者不得修改文件、不得执行 Git 写操作。
- 审核范围必须明确到提交、工作树或文件集合。
- 先列 findings，再列已验证项，最后给结论。
- Critical 或 Important 未闭环时不得标记 PASS。
- 审核通过不等于整体发布就绪；发布仍需最终验收与 Windows 真机验证。
- 现有 276 项 Python 测试来自旧 `tests/` 基线，不是 v2 架构证据；新 `fm27lab/tests` 当前 28 项测试，覆盖包版本、CLI 环境继承、配置/路径边界、SQLite 迁移/事务、HTTP 健康、鉴权、错误封套、Origin、ACL 失败清理与 sidecar serve 集成；Vitest 当前 9 项。
- 新 `fm27lab/tests` 当前 43 项（含 15 项 23 人名单领域测试）。
- Tauri sidecar supervisor 的静态实现已存在，但 Linux 无 WebKitGTK，Windows CI 的 `cargo build`/`cargo test`/安装包构建是唯一编译证据。PyInstaller onedir sidecar 已在 Linux 构建并通过 ready/health/shutdown 冒烟测试。
- Rust 核心 crate 当前 4 项 cargo test 通过；React 壳当前 9 项 Vitest 通过、类型检查与生产构建通过。Tauri 壳在 Linux 无 WebKit 依赖，Windows 构建仍是发布门槛。
