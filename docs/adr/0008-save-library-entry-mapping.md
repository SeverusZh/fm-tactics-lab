# ADR-0008 存档库旧入口在 v2 的映射

- 状态：已接受
- 日期：2026-11-15
- 决策者：仓库维护者
- 修订：ADR-0006 替换映射的落地状态

## 背景

ADR-0006 删除了存档对战，并约定 `library import`、`library status`、`library club`、`library load`、`library pool-import` 作为存档战术库入口。v2 重建后，这些能力分布在 `/api/saves` 系列系统路由、草案名单接口与前端存档页中，没有以 `library_*` 名称出现，导致旧映射看起来“未暴露”。

需要明确：能力已存在且以 v2 语义暴露，不引入 `library_*` 别名。

## 决策

- 不保留 `library_*` 名称，也不新增兼容别名；能力以 v2 资源语义暴露。
- 映射如下。

| 旧入口 | v2 HTTP | v2 CLI | v2 UI |
| --- | --- | --- | --- |
| `library import` | `POST /api/saves/import` | `saves import-file` | 存档页导入存档文件 |
| `library status` | `GET /api/saves`、`GET /api/saves/{save_id}` | `saves list`、`saves get` | 存档页列表与状态 |
| `library club` | `GET /api/saves/{save_id}/squad` | `saves squad` | 存档页名单与选人 |
| `library load` | `POST /api/saves/{save_id}/tactics/{tactic_index}/import` 建草案；`POST /api/drafts/{draft_id}/apply-roster` 应用名单 | 无对应命令，走 HTTP | 存档页导入到战术板 |
| `library pool-import` | `POST /api/saves/{save_id}/tactics/{tactic_index}/pool` | 无对应命令，走 HTTP | 存档页加入客队战术池 |
| `library export` | `GET /api/saves/{save_id}/tactics/{tactic_index}/export.fmf` | 无对应命令，走 HTTP | 存档页导出 FMF |

- 存档战术相关路径登记为系统路由，不占用能力注册表。
- 真实 AI 生成不在存档库范围，见 ADR-0009。

## 后果

- 旧映射以 v2 语义闭合，不再需要 `library_*` 名称。
- 部分能力仅 HTTP，CLI 与 MCP 不覆盖存档战术导出与入池；这是系统路由的既有边界。
- 文档与 UI 不得再宣称未实现的能力。

## 备选

- 恢复 `library_*` 命名：与 v2 资源语义冲突，且会形成双 owner。
- 为每个存档战术动作补齐三入口：收益低，压缩能力注册表边界。

## 实现状态

- `/api/saves/import`、`/api/saves`、`/api/saves/{save_id}`、`/api/saves/{save_id}/squad` 已存在。
- `/api/saves/{save_id}/tactics`、`/tactics/{tactic_index}/import` 已存在。
- `/tactics/{tactic_index}/export.fmf` 与 `/tactics/{tactic_index}/pool` 本轮新增。
