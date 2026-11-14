# Agent 集成验证

状态：按 v2 实现核对，核对日期 2026-11-14。当前版本 fm27lab 2.0.0.dev0，接口版本 fm27lab/v2。历史 v1 agent-runtime 的验收记录保留在第 7 节并标注版本与日期，不作为当前契约依据。

## 1. 目的与范围

- 验证 HTTP 契约、CLI、MCP、数据目录与关闭流程是否与代码一致。
- 验证自动化测试当前的通过情况与计数口径。
- 归档历史验收记录，避免与现网实现混淆。

不覆盖：FM27 原生引擎的模拟质量与战术收益评估；该类结论由实验批次数据给出，不属于接入契约验证。

## 2. 环境矩阵

| 环境 | 用途 | 当前状态 |
| --- | --- | --- |
| Linux WSL2，Python 3.12 虚拟环境 .venv | 运行 legacy unittest、v2 pytest、HTTP 契约脚本 | 已执行 |
| Node 20 与 pnpm | 运行 web Vitest 与两个 Node 脚本测试 | 已执行 |
| Windows 11 与 FM27 客户端 | Tauri 壳、sidecar 启动、引擎工作区端到端 | 部分项目未执行，见第 6 节 |

前置条件

- 仓库根目录创建 Python 3.12 虚拟环境并安装项目依赖，虚拟环境路径为 .venv。
- web 依赖已安装，可用 pnpm --dir web 执行。
- HTTP 契约验证需要一个运行中的 sidecar 与可读的发现文件。

## 3. 自动化测试

### 3.1 legacy 回归测试

```bash
.venv/bin/python -m unittest discover -s tests
```

期望输出包含 Ran 281 tests 与 OK；本机实测耗时约 19 秒。

覆盖范围：tests 目录为 v1 时期的回归测试，用例风格为 unittest。包括 test_agent_cli、test_agent_client、test_agent_contract、test_agent_drafts、test_agent_mcp、test_agent_server、test_career_retirement、test_execution、test_game_db_names、test_league_catalog、test_locale、test_opponent_scope、test_pool_pairing、test_release、test_save_export、test_tactic_pool、test_tactics_server_queue、test_worker_sessions，以及辅助模块 agent_mock。

注意：legacy 用例验证 v1 模块与发布导出，不构成 v2 HTTP 契约的证据；v2 契约证据见 3.2 与第 4 节。

### 3.2 v2 单元与接口测试

```bash
.venv/bin/python -m pytest
```

配置来自 pyproject.toml，testpaths 为 fm27lab/tests，收集 2158 项，全部通过时退出码为 0。

覆盖范围：fm27lab/tests 下的 pytest 风格用例，包含 HTTP 路由、应用服务、领域规则、SQLite 适配器、MCP 协议与引擎宿主适配。

### 3.3 前端测试

```bash
cd web && npx vitest run
```

期望输出包含 Test Files 9 passed 与 Tests 228 passed；测试文件为 App、RunBar 与 7 个页面测试。

### 3.4 Node 脚本测试

```bash
node tests/test_i18n.cjs
node tests/test_workspace_scripts.cjs
```

期望输出分别为

```text
OS language, dynamic rendering, native values, names and transition labels verified
workspace scripts compile and squad selection is declared
```

### 3.5 计数口径

| 测试集 | 命令 | 当前计数 |
| --- | --- | --- |
| legacy unittest | .venv/bin/python -m unittest discover -s tests | 281 |
| v2 pytest | .venv/bin/python -m pytest | 2158 |
| web Vitest | cd web && npx vitest run | 319，共 13 个文件 |
| Node 脚本 | node tests/test_i18n.cjs 与 node tests/test_workspace_scripts.cjs | 2 个脚本 |

口径说明

- unittest 只收集 tests 目录下的 unittest 用例；pytest 的 testpaths 限定 fm27lab/tests，不收集 tests 目录。
- 两类计数不可相加；报告总量时必须注明测试集。
- 任一命令的通过数以实跑结果为准，不引用历史数字。

## 4. HTTP 契约验证

准备工作：从发现文件读取地址与 token。以下命令假定已导出 DATA 为数据目录绝对路径。

```bash
DATA=/absolute/path/data
URL=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['url'])" "$DATA/agent/endpoint.json")
TOKEN=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['token'])" "$DATA/agent/endpoint.json")
```

### 4.1 免鉴权与鉴权

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 健康检查免鉴权 | curl -s "$URL/api/health" | 200，字段 status 为 ok、api 为 fm27lab/v2、version 为 2.0.0.dev0、database 为 ready |
| 版本接口免鉴权 | curl -s "$URL/api/version" | 200，capabilities 为空数组，limits 含 max_workers 256 与 max_seeds 10000 |
| 业务接口需要 token | curl -s -o /dev/null -w '%{http_code}' "$URL/api/jobs" | 401 |
| 缺失 token 的错误体 | curl -s "$URL/api/jobs" | 封套 code 为 unauthorized，message 为 missing bearer token |
| 错误 token | curl -s -H "Authorization: Bearer wrong" "$URL/api/jobs" | 401，message 为 invalid bearer token |
| 正常 token | curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$URL/api/jobs" | 200 |

证据 fm27lab/interfaces/http/routes/system.py、fm27lab/interfaces/http/common.py:38-51。

### 4.2 来源校验

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 非白名单 Origin | curl -s -H "Origin: http://evil.example" "$URL/api/health" | 403，code 为 forbidden_origin，message 为 origin is not allowed |
| 桌面壳 Origin | curl -s -H "Origin: tauri://localhost" "$URL/api/health" | 200 |

证据 fm27lab/interfaces/http/app.py:149-169。

### 4.3 旧命名空间

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| v1 清单端点不存在 | curl -s -o /dev/null -w '%{http_code}' "$URL/api/agent/v1/manifest" | 404 |
| 旧命名空间错误体 | curl -s "$URL/api/agent/v1/manifest" | code 为 not_found |

### 4.4 发现文件字段

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 字段集合 | python -c "import json,sys;print(sorted(json.load(open(sys.argv[1]))))" "$DATA/agent/endpoint.json" | 恰好包含 schema、api、url、port、token、pid、data_dir、engine_root、created_at |
| 接口版本 | python -c "import json,sys;print(json.load(open(sys.argv[1]))['api'])" "$DATA/agent/endpoint.json" | fm27lab/v2 |

不存在 game_root、versions、capabilities、limits 字段。证据 fm27lab/sidecar.py:19-30。

### 4.5 文档端点

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| OpenAPI 文档 | curl -s -o /dev/null -w '%{http_code}' "$URL/api/openapi.json" | 200 |
| Swagger UI | curl -s -o /dev/null -w '%{http_code}' "$URL/api/docs" | 200 |
| 路径数与操作数 | python -c "import json,urllib.request,sys;d=json.load(urllib.request.urlopen(sys.argv[1]));ops=sum(len([k for k in v if k in ('get','post','put','patch','delete')]) for v in d['paths'].values());print(len(d['paths']),ops)" "$URL/api/openapi.json" | 39 条路径，55 个操作 |
| 组件模型数 | python -c "import json,urllib.request,sys;d=json.load(urllib.request.urlopen(sys.argv[1]));print(len(d['components']['schemas']))" "$URL/api/openapi.json" | 63 |

证据 fm27lab/interfaces/http/app.py:107-113。

### 4.6 关闭流程

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 无 token 关闭 | curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/api/shutdown" | 401 |
| 有 token 关闭 | curl -s -X POST -H "Authorization: Bearer $TOKEN" "$URL/api/shutdown" | 202，body 为 shutting_down |
| 关闭后清理 | 进程退出后检查发现文件 | agent 目录下 endpoint.json 不存在 |

证据 fm27lab/interfaces/http/routes/system.py:90-94、fm27lab/sidecar.py:62-66。

## 5. CLI 与 MCP 验证

### 5.1 CLI

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 版本 | .venv/bin/python -m fm27lab version | 输出 2.0.0.dev0 fm27lab/v2，退出码 0 |
| 缺少 sidecar | .venv/bin/python -m fm27lab --data-dir /tmp/fm27lab-empty drafts list | 退出码 1，标准错误含 endpoint_missing |
| 全局选项位置 | .venv/bin/python -m fm27lab drafts list --data-dir /tmp/fm27lab-empty | 退出码 2，提示没有该选项 |
| MCP 缺少 sidecar | .venv/bin/python -m fm27lab --data-dir /tmp/fm27lab-empty mcp | 退出码 1，标准错误含「无法启动 MCP 服务」 |

证据 fm27lab/cli.py:47-57、fm27lab/cli.py:121-148。

### 5.2 MCP 握手

先启动 sidecar 并确保 MCP 使用同一数据目录，然后向标准输入发送初始化请求

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}
```

期望响应包含

- protocolVersion 为 2024-11-05。
- capabilities 含 tools、resources、prompts，且各自 listChanged 为 false。
- serverInfo 的 name 为 fm27lab。

随后发送 tools/list，期望工具数为 49；发送 resources/list，期望 4 个静态资源。证据 fm27lab/interfaces/mcp/protocol.py:198-225、fm27lab/interfaces/mcp/tools.py、fm27lab/interfaces/mcp/resources.py。

## 6. Windows 桌面端验收

| 编号 | 项目 | 期望 | 状态 |
| --- | --- | --- | --- |
| W1 | 启动桌面应用 | 壳进程存活，数据目录出现 agent/endpoint.json | 待执行 |
| W2 | 连接信息 | get_connection 返回 url、token 与 api fm27lab/v2；ui 可以调用 /api/health | 待执行 |
| W3 | sidecar 日志 | 数据目录 logs 下出现 sidecar-<pid>.stderr.log | 待执行 |
| W4 | 关闭应用 | sidecar 收到 POST /api/shutdown 返回 202 后退出，发现文件被删除 | 待执行 |
| W5 | 重启应用 | 新 token 与旧 token 不同 | 待执行 |
| W6 | 引擎未接线 | POST /api/experiments/start 返回 503 engine_unavailable | 已由接口测试间接确认 |

证据 src-tauri/src/lib.rs:209-300、src-tauri/src/lib.rs:433-463。

## 7. 历史验收记录

以下记录来自 v1 agent-runtime 与 fm27lab/v1 接口，路径 /api/agent/v1 与相关发现在现版本已不存在，保留仅用于追溯。当前契约以第 3 至 6 节为准。

### 7.1 2026-11-08 WSL2 与 Windows FM27 实测

- 引擎校验通过，引擎包 SHA256 以 252ff8fb 开头，状态 verified 与 can_simulate 为真。
- Windows Python 3.12.12，payload 版本 v1108.5。
- 自由推演 2 场，失败 0，吞吐约 23.8 场每分钟。
- 对比实验 2 个种子、A/B 共 4 场，paired 差值 0.5。
- 存档导入构建 27.0.0+2493426，读到 32 个一线队与 74 名可解析球员，原存档保持只读。
- FMF 导出 1728 字节且 native_roundtrip_verified，导入 1376 字节、records 369。
- 定位球文件 451 字节。
- MCP initialize 返回协议 2025-06-18，serverInfo 为 fm27lab-mcp，21 个工具，含 manifest 资源，2 个 prompt。
- 鉴权 401、403、200 与 Cookie 访问 /api/catalog 返回 200。
- UI 根路径与 app.js 返回 200。
- 取消 8 场批次后状态为 cancelled。
- shutdown 返回 202，进程退出且 endpoint.json 删除。
- Tauri 壳在 Windows 构建测试通过，NSIS 打包与 sidecar 资源断言通过。
- 未覆盖：安装包安装后启动、完整 UI 走查。

### 7.2 2026-11-10 A16 至 A18 实机记录

- 环境：Windows 实机，agent-runtime 与 v1109.3 宿主。
- lab_status 返回 server_version 1109.3。
- 36 套客队战术池 inline 往返成功。
- 同一任务 A/B 使用 8 个种子且抽签一致。
- 两批次提交后状态为 queued，排队位置为 2。
- draws、entry 与 CSV 抽签列符合预期。
- 两条池任务比较返回 comparable 为 false。
- 200 场批次失败数为 0。
- WSL 访问 UNC 路径读取 match.pkm 时进程退出码 104。

注意：以上记录中的接口、工具数、协议版本与 Cookie 鉴权均属 v1，当前 v2 的对应事实为 49 个工具、协议 2024-11-05、仅 Bearer 鉴权、无 /api/agent/v1 命名空间。

## 8. 已知限制

- 本机 Linux 无 FM27Simulator 可执行文件，保持原生引擎未启动时实验启动返回 503 engine_unavailable；配置 engine_root 后由惰性宿主在首次使用时构造。
- Windows 桌面端 W1 至 W5 尚未执行。
- 数据目录 exports 子目录当前无写入使用方。
- 池条目库与实验解耦，实验只读草案内嵌 away_tactic_pool。
- CLI 单次请求超时 30 秒，长批次 start 会本地超时，服务端继续执行。
- MCP 无进度通知与协议层取消，只能轮询。

## 9. 维护规则

- 改动端点、参数、状态码或发现文件字段时，同步更新本文与 AGENT_INTEGRATION.md、AGENT_QUICKSTART.md。
- 文档与代码冲突时以代码为准，并在核对日期列更新日期。
- 测试计数只写实跑结果，并注明测试集与命令。
- 历史记录只追加，不修改既有条目；被取代的接口需标注版本与失效说明。
