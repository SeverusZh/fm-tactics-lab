# ADR-0007 能力注册表的生成边界

- 状态：已接受
- 日期：2026-11-15
- 决策者：仓库维护者
- 修订：ADR-0003 关于“三入口从同一份定义生成”的表述

## 背景

ADR-0003 要求每个能力在 registry 定义一次，HTTP 路由、CLI 命令与 MCP 工具全部从同一份定义生成。实现过程中注册表按域拆分为 `fm27lab/registry/` 包，单一事实来源是能力声明 `Capability(name, description, http, cli, mcp)`；三入口适配层仍为手写：HTTP 使用 FastAPI 路由与 Pydantic 模型，CLI 使用 Typer 命令，MCP 使用显式 schema 的工具表。

完全由注册表生成三入口需要把输入/输出模型、鉴权、错误映射、流式响应与副作用语义一并数据化，成本远高于收益，且会削弱类型检查与可读性。契约一致性仍需强保证。

## 决策

- 单一事实来源保持为 `fm27lab/registry/parts/*.py` 的能力声明，能力名称、HTTP 方法与路径、CLI 命令、MCP 工具名只在这里定义。
- 三入口适配层保持手写并保持薄；业务逻辑不得进入接口层。
- 一致性由契约测试锁定：能力集合与 OpenAPI 业务操作完全一致、CLI 叶子命令集合一致、MCP 工具名集合一致、命名与路径参数规则一致、重复与漂移检测为空。
- 业务路由只允许在 `fm27lab/interfaces/http/routes/` 模块声明；系统路由登记在 `SYSTEM_PATHS` 与 `SYSTEM_CLI_COMMANDS`，不占用能力。
- 输入/输出 schema 以 OpenAPI 快照 `docs/openapi.json` 锁定，快照由 `scripts/generate_openapi_snapshot.py` 生成并由测试校验同步。
- 新增能力必须同时补齐三入口并更新注册表与快照，任何一处缺失由契约测试拒绝。

## 后果

- 注册表不承担代码生成，不会出现生成器与手写代码双 owner。
- 一致性依赖测试而非生成，新增能力需要手写三处适配，但每处都有类型检查与显式契约。
- OpenAPI 快照成为后端对外契约的可审计基线。

## 备选

- 注册表生成三入口：需要把输入/输出模型与错误语义全部数据化，成本高且可读性差。
- 取消注册表，三入口各自维护：会重新引入漂移，ADR-0003 已否决。

## 实现状态

- `fm27lab/registry/` 由 `model.py` 与 13 个域分片组成，聚合 61 项能力。
- `fm27lab/tests/test_registry_contract.py` 覆盖集合一致性、命名规则、重复与漂移检测。
- `docs/openapi.json` 快照与 `fm27lab/tests/test_openapi_snapshot.py` 校验一致。
