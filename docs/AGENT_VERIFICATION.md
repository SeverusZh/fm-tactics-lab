# Agent 接入验收说明

状态：随 Agent 接入实现一起提供
适用范围：Windows x64 目标机；开发机可为 Linux

## 1. 目的与边界

本说明区分两类验证：

- 可在 Linux 开发机自动运行的契约与适配器测试。
- 必须在装有 FM27 的 Windows 目标机执行的原生端到端验收。

自动化测试不启动原生引擎，不验证足球结果；原生一致性仍以现有工具链与 [SIMULATION_FIDELITY.md](SIMULATION_FIDELITY.md) 的范围为准。

## 2. 环境矩阵

| 环境 | 可验证内容 |
| --- | --- |
| Linux，Python 3.12 及以上 | 契约助手、HTTP 客户端、草案、CLI、MCP、mock 服务端 |
| Windows，Python 3.12，无游戏 | 服务端导入与语法、CLI/MCP 启动、发现与鉴权错误路径 |
| Windows，FM27 已安装 | 引擎预检、自由推演、存档对战、FMF 往返、取消与恢复 |

## 3. 自动化测试

在仓库根目录执行：

@@@bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_agent_*.py' -v
python3 -m unittest discover -s tests -v
@@@

覆盖：

- test_agent_contract：token、Host、Cookie、错误封套、分页、幂等、发现文件与启动脚本。
- test_agent_client：发现、请求、错误映射、任务等待、分页、种子展开。
- test_agent_drafts：六种来源、语义编辑、校验回滚、列表与删除。
- test_agent_server：路由、清单、分页、幂等、忙碌冲突、shutdown。
- test_agent_cli：命令行参数、JSON 输出、退出码、等待、CSV、career 与 FMF。
- test_agent_mcp：stdio 初始化、工具列表、工具调用、资源、prompt、错误。

Mock 服务端位于 tests/agent_mock.py，只实现协议形状，不实现业务校验。

## 4. Windows 端到端验收

前置：

1. 按 [DEVELOPMENT.md](DEVELOPMENT.md) 准备 private 资产并构建 FM27Simulator.exe。
2. 启动源码版或桌面版，确认 /api/status 显示引擎兼容可模拟。
3. 生成 Agent 发现文件：服务启动后应存在 <dataDir>/agent/endpoint.json。
4. 生成入口脚本：<dataDir>/agent/fm27lab.cmd 与 mcp.json。

逐项验收：

| 编号 | 步骤 | 通过标准 |
| --- | --- | --- |
| A1 | 无 token 访问 /api/agent/v1/manifest；用错误 Host 访问 | 401 与 403，UI 页面仍正常 |
| A2 | 调用 manifest 与 schemas | 字段齐全，主版本为 fm27lab/v1，schema 可解析 |
| A3 | draft create default；edit mentality；validate；delete | 草案文件生成、编辑生效、校验通过、删除后不可读 |
| A4 | 用 CLI 与 MCP 各跑一次 A/B 对比，每方案 2 场 | 任务完成，metrics 含 A/B，paired 存在 |
| A5 | career import、team、opponents、preview、run | 存档导入可取消；对手报告生成；count 口径为每对手总场数 |
| A6 | job list、job get、cancel、resume、rename、delete、export | 分页正确；取消后状态 cancelled；重启后可 resume 未完成任务 |
| A7 | results summary、matches、match、csv | 指标、逐场、事件、CSV 列与规格 7.4 一致 |
| A8 | fmf import、export、setpiece export | 导出文件可被原版解析器回读；report 中回读校验为真 |
| A9 | 触发 validation_failed、engine_busy、not_found、app_unavailable | 错误码、HTTP 状态、retriable 与本说明一致 |
| A10 | 同一 Idempotency-Key 重复提交 runs | 第二次返回同一 job id 且带 Idempotency-Replayed |
| A11 | 启动 headless 实例并调用 shutdown | 进程优雅退出；活动任务被取消 |
| A12 | 运行 UI 主流程 | 页面加载、草案编辑、批次运行、结果展示不回归 |
| A13 | 用绝对路径或越界路径调用导出 | 被拒绝；不写入 dataDir 之外 |
| A14 | 运行中重启 App，重新打开任务列表 | 任务标记 interrupted；已完成结果仍可读 |
| A15 | 记录 4 场、8 场、16 场批次耗时 | 得到单场耗时与吞吐基线，用于预算校准 |

## 5. 安全验证

- 不带 Authorization 且不带 Cookie 访问 Agent 端点应返回 401。
- Host 改为其他域名应返回 403。
- 浏览器 UI 首次打开后，后续请求应携带 fm27_session Cookie。
- 导出接口只写 <dataDir>/agent/exports。
- 日志与结果不包含 token、Cookie 或完整存档内容。

## 6. 故障排查

- 找不到 endpoint.json：确认 App 已启动，或检查 FM27LAB_DATA 是否指向正确数据目录。
- 401：确认调用方读取的是当前实例的 endpoint.json；App 重启后 token 会轮换。
- 409 engine_busy：控制面操作读取返回中的 active_job，等待或取消后再提交；自由模式 /runs 会进入队列。
- 引擎不兼容：按现有引擎设置选择游戏根目录，或按 TROUBLESHOOTING.md 检查构建匹配。
- MCP 无响应：确认 sidecar 的 stderr 日志；stdout 只承载协议消息。

## 7. 本机实测记录

记录时间：2026-11-08，WSL2 开发环境 + Windows FM27 实机。

| 项目 | 结果 |
| --- | --- |
| 引擎 | 安装目录 game_plugin.dll SHA256 与适配器参考值 252ff8fb... 一致，状态为 verified、can_simulate |
| 运行时 | Windows Python 3.12.12；使用官方 v1108.5 发布 payload 的引擎工作区与本地临时数据目录 |
| 自由推演 | 2 场完成，0 失败；单场吞吐约 23.8 场/分钟 |
| 对比推演 | 2 种子 × A/B 共 4 场完成；A 与 B 指标独立；paired 差值为 0.5 |
| 存档导入 | 用户提供的 FM27 存档，构建 27.0.0+2493426，导入完成；32 名一线队球员，74 名可解析球员；原存档只读未修改 |
| 存档球队 | 载入 managed club 的存储战术与 23 人比赛名单，草案校验通过 |
| 对手扫描 | 同联赛 23 个可用教练预设对手；预览生成 23 人名单 |
| 存档批次 | 1 个对手 × 主客场 2 场完成；xg 2.37，xga 1.01，控球 43.7%，传球成功率 83.8% |
| FMF | 导出 1728 字节，native_roundtrip_verified 为真；导入消耗 1376 字节，records 369 |
| 定位球 | 导出 451 字节，native_roundtrip_verified 为真 |
| MCP | initialize 协商 2025-06-18，serverInfo 为 fm27lab-mcp，26 个工具，lab_status 无错误，manifest 资源可读，3 个 prompt |
| 鉴权 | 无 token 401，错误 Host 403，正确 token 200；Cookie 访问旧 /api/catalog 200，无凭证 401 |
| UI | GET / 与 /app.js 均 200，Set-Cookie 正常返回 |
| 取消 | 8 场批次取消后状态 cancelled，已完成 0 |
| 关闭 | shutdown 返回 202，进程退出，endpoint.json 删除 |
| Launcher | 修改后的 Launcher.cs 通过 Windows csc x64 编译 |
| 未覆盖 | headless 启动只做编译验证；浏览器完整 UI 流程未跑；存档测试只用了一份 FM27 存档 |

说明：源码运行在 WSL 文件系统时，原生宿主若经 UNC 路径读取 match.pkm 会退出 104；本次验收将引擎工作区与数据目录放在 Windows 本地路径下完成。打包版使用 Windows 本地路径，不受影响。存档导入、球队载入、对手扫描与存档批次均在实机完成；导入数据与测试结果保存在 Windows 临时目录，验收后已清理。

## 8. 已知限制

- A4、A5、A8 已在 Windows 实机完成；A15 的 4/8/16 场完整基线仍未单独测量。
- 存档读取依赖 fmsave 0.9.0；不同构建或损坏存档仍需按 TROUBLESHOOTING.md 排查。
- MCP 协议版本支持 2025-06-18 与 2024-11-05；其他版本按客户端协商处理。
- 首期不提供定位球片段实验、实验执行力与原生 AI 生成对手的 Agent 工具。
- 多 Agent 自由模式提交进入串行队列，由引擎逐个执行；引擎切换、存档与控制面操作仍要求空闲。
- 队列、MCP 紧凑文本与新增工具已在源码测试集验证；Windows 实机复验需在重新打包后执行。
