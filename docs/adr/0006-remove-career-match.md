# ADR-0006 删除存档对战并收敛存档入口

- 状态：已接受
- 日期：2026-11-12
- 决策者：仓库维护者

## 背景

“存档对战”与“存档战术库”都要求用户导入 .fm 存档，形成两个入口与两套任务模型。客队战术池的轮战模式与真实名单模式已经覆盖“用存档球队和名单做对手”的核心价值。维护者明确要求删除存档对战。

## 决策

- 删除存档对战的 UI、HTTP 路由、CLI 命令、MCP 工具、测试与文档。
- 保留“存档战术库”作为唯一 .fm 导入入口，提供联赛战术库、真实 AI 生成、导出、入池与我的球队同步。
- 删除在 Phase 0.5 执行，早于新 HTTP/CLI/MCP 与 UI 建设；不保留隐藏入口或兼容别名。
- 旧任务与旧缓存不迁移，只读保留。

## 替换映射

| 旧入口 | 新入口 |
| --- | --- |
| `career_import` | `library import` |
| `career_status` | `library status` |
| `career_team` | `library club` |
| `career_cancel` | `library cancel` |
| `career_opponents` | 删除；由 `library leagues` 与真实 AI 生成取代 |
| `career_preview` | 删除；由 `library load` / 真实 AI 生成预览取代 |
| `career_run` | 删除；由自由推演 + 客队战术池 + 真实名单取代 |
| `draft_create source=save` | `library load` 取回场景，再以 `draft_create source=inline/draft` 创建 |
| UI 存档对战模式 | 删除；存档战术库是唯一入口 |

## 后果

- 用户不再能选择多个对手、按主客场批量生成存档对战任务。
- 战术池 + 真实名单 + 23 人名单成为对手测试的统一路径。
- 删除必须伴随残留引用检查、负向测试与文档更新。
- 这是内部代码退役，采用 delete-first；不保留兼容入口。

## 备选

- 保留隐藏入口：违背单一入口与解耦目标。
- 保留 CLI/MCP 兼容别名：会延长双 owner 生命周期，维护者明确不需要。

## 实现状态

- UI 的存档对战模式、HTTP 的存档批次路由、CLI 的 career 子命令、MCP 的 career_* 工具与 schema、旧 Agent 文档段落已删除。
- `/api/save/selection` 保留为通用比赛名单选择能力，供存档战术库名单编辑使用；它不是 career 批次入口。
- `/api/save/apply-roster`、存档战术库导入/联赛/真实战术/入池、FMF 与自由推演保留。
- 负向契约：旧 career 路径返回 404，旧 MCP 工具为未知工具，旧 CLI 子命令不可用，旧 UI 资源不再提供。
- 战术执行力实验控件已拆到 `workspace-controls.js`，不再依赖存档对战状态。
