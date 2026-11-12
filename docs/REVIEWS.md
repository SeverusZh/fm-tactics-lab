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
| 2026-11-12 | 设计文档第九轮 | 同上 | 待审 | 等待 design-reviewer 第九轮结果。 |
| 2026-11-12 | sidecar 基础切片复审 | 同上 | FAIL | 复审：CLI 丢弃 FM27LAB_DEV、空 FM27LAB_DATA 落到 CWD、迁移拆分不支持一行多语句、wheel 无 fm27lab 入口；另有 upsert/错误封套测试不足。已修复。 |
| 2026-11-12 | sidecar 基础切片第三轮 | 同上 | PASS | 27 项测试通过；I1-I4 全闭环；剩余路径别名/CLI host-port/迁移排序/测试超时等 Minor，已继续修复。 |

## 审核规则

- 审核者不得修改文件、不得执行 Git 写操作。
- 审核范围必须明确到提交、工作树或文件集合。
- 先列 findings，再列已验证项，最后给结论。
- Critical 或 Important 未闭环时不得标记 PASS。
- 审核通过不等于整体发布就绪；发布仍需最终验收与 Windows 真机验证。
- 现有 276 项 Python 测试来自旧 `tests/` 基线，不是 v2 架构证据；新 `fm27lab/tests` 当前 28 项测试，覆盖包版本、CLI 环境继承、配置/路径边界、SQLite 迁移/事务、HTTP 健康、鉴权、错误封套、Origin、ACL 失败清理与 sidecar serve 集成。
- Tauri sidecar supervisor 的静态实现已存在，但 Linux 无 WebKitGTK，Windows CI 的 `cargo build`/`cargo test`/安装包构建是唯一编译证据。PyInstaller onedir sidecar 已在 Linux 构建并通过 ready/health/shutdown 冒烟测试。
- Rust 核心 crate 当前 4 项 cargo test 通过；React 壳当前 2 项 Vitest 通过、类型检查与生产构建通过。Tauri 壳在 Linux 无 WebKit 依赖，Windows 构建仍是发布门槛。
