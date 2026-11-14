# 安全与隐私基线

## 适用范围与威胁模型

本项目是单机运行的 FM27 战术实验工具，Python sidecar 由 Tauri 桌面壳拉起，前端经回环 HTTP 调用 sidecar。信任边界为本机同一用户会话内的进程与 Tauri WebView；不可信面包括本机其他用户、外部网络、浏览器页面以及写入数据目录或仓库的外部文件。sidecar 强制只监听回环地址，配置层拒绝非回环 host（fm27lab/config.py:11、fm27lab/config.py:40-41），socket 由 sidecar 自建后交给 uvicorn（fm27lab/sidecar.py:83-94）。

## 审计结论

| 面 | 结论 | 证据 |
| --- | --- | --- |
| 监听范围 | 仅回环监听，端口由系统分配，uvicorn 不自行监听额外地址 | fm27lab/sidecar.py:83-94、fm27lab/config.py:11、fm27lab/config.py:40-41 |
| API 鉴权 | 当前 55 个 /api operation 中 53 个要求 Bearer，仅 2 个探活公开 | fm27lab/interfaces/http/common.py:38-55、test_api_authentication_matrix、test_openapi_declares_bearer_security |
| 公开路由白名单 | GET /api/health 与 GET /api/version；文档路由单独列为已知边界 | fm27lab/interfaces/http/routes/system.py:40、fm27lab/interfaces/http/routes/system.py:55、test_documentation_routes_are_public_boundary |
| 未授权响应 | 统一 401 封套 code=unauthorized、WWW-Authenticate: Bearer、不回显令牌 | fm27lab/interfaces/http/common.py:38-55、fm27lab/interfaces/http/app.py:191-217、test_unauthorized_responses_do_not_leak_token |
| 令牌生成与存储 | secrets.token_hex(32) 生成，Settings 的 repr 不包含令牌，endpoint.json 为 0600 | fm27lab/config.py:30、fm27lab/config.py:68、fm27lab/sidecar.py:33-61、test_endpoint_file_permissions |
| endpoint 描述符 | 9 个固定字段，schema 与 api 版本正确，token 存在，写入失败时清理临时文件并保留既有描述符 | fm27lab/sidecar.py:19-49、test_endpoint_descriptor_contract、test_endpoint_write_failure_leaves_no_temporary_file、test_endpoint_replace_failure_preserves_previous_descriptor |
| 数据目录权限 | POSIX 下 data_dir、agent、exports 为 0700 | fm27lab/config.py:14-17、fm27lab/config.py:105-110、test_data_directories_are_owner_only |
| SQLite 文件权限 | 默认 umask 022 下库文件为 0644，依赖 0700 父目录隔离；WAL 文件位于同目录 | fm27lab/adapters/storage_sqlite/db.py:44-55 |
| 日志与错误信息 | 访问日志关闭；未处理异常只回通用 500；校验失败不回显请求体 | fm27lab/sidecar.py:91、fm27lab/interfaces/http/app.py:219-232、fm27lab/tests/test_http_health.py:93-106 |
| CORS 与 Origin | 仅 Tauri 来源与 dev 前端来源，allow_credentials=False，非白名单 Origin 返回 403 | fm27lab/interfaces/http/app.py:49-50、fm27lab/interfaces/http/app.py:171-189、fm27lab/tests/test_http_health.py:123-156 |
| 文档路由暴露 | /api/docs 与 /api/openapi.json 公开，不含业务数据与令牌，列为已知边界 | fm27lab/interfaces/http/app.py:106-111、test_documentation_routes_are_public_boundary |
| 产物路径边界 | 文件名与 kind 白名单、根目录 resolve 包含检查、符号链接拒绝、临时文件原子替换 | fm27lab/application/artifacts.py:14-15、fm27lab/application/artifacts.py:24-66、fm27lab/application/artifacts.py:156-167、fm27lab/interfaces/http/routes/artifacts.py:82-96 |
| 实验目录边界 | job_id 白名单、experiments 根包含检查、staging 目录原子替换 | fm27lab/application/experiment_material.py:27、fm27lab/application/experiment_material.py:61-187、fm27lab/application/experiment_material.py:189-203 |
| 存档导入路径 | source_path 只校验是否为普通文件，无目录包含检查，需持有令牌 | fm27lab/application/save_import.py:201-208、fm27lab/interfaces/http/routes/save_import.py:91-100 |
| 输入边界 | 输入模型 strict 且 extra=forbid，内容、分页与批量均有上限 | fm27lab/interfaces/http/routes/artifacts.py:17-22、test_oversized_artifact_payload_returns_413_envelope、test_oversized_fmf_payload_returns_400_envelope、test_invalid_query_bounds_return_400_envelope |
| 幂等缓存 | 先鉴权后读 body、非 2xx 不缓存、快照上限 1 MiB、键白名单 | fm27lab/interfaces/http/idempotency.py:34-75、fm27lab/adapters/storage_sqlite/idempotency.py:13、fm27lab/adapters/storage_sqlite/idempotency.py:15 |
| SSE | /api/events 需 Bearer，Last-Event-ID 校验，断连注销订阅 | fm27lab/interfaces/http/routes/system.py:96-123、fm27lab/tests/test_http_events.py:194 |
| 静态文件 | 无 StaticFiles 与 mount，sidecar 不服务前端资源 | 全仓 grep StaticFiles 与 app.mount 无命中，web 资源由 Tauri 加载 |
| 仓库隐私 | 无真实令牌、私钥与个人路径入库，示例路径为占位 | 仓库隐私一节、test_gitignore_covers_private_and_runtime_data、test_source_manifest_excludes_private_runtime_files |
| 客户端令牌处理 | 只接受回环 endpoint、拒绝重定向、repr 掩码、错误文本不含令牌 | fm27lab/client.py:52-56、fm27lab/client.py:77-98、fm27lab/client.py:170-171、fm27lab/tests/test_cli_client.py:142 |

## 监听与网络暴露

sidecar 在 fm27lab/sidecar.py:83-94 自建 TCP socket 并绑定 settings.host 与 settings.port，端口为 0 时由系统分配并回读实际端口（fm27lab/config.py:33、fm27lab/config.py:42-43）。uvicorn 使用传入的 listener 运行，access_log=False、log_level=warning、lifespan=off（fm27lab/sidecar.py:91），退出时删除 endpoint.json 并关闭 listener（fm27lab/sidecar.py:64-68、fm27lab/sidecar.py:95-97）。不存在 0.0.0.0 监听路径。

HTTP 为明文且没有 TLS。令牌以 Bearer 头在 127.0.0.1 回环链路上传输，同机特权进程可通过流量嗅探或读取 endpoint.json 获取令牌，因此传输层防护依赖操作系统用户隔离而非加密。

CORS 只允许 tauri://localhost、http://tauri.localhost，dev 模式追加 http://localhost:1420（fm27lab/interfaces/http/app.py:49-50、fm27lab/interfaces/http/app.py:171-179）；allow_credentials=False，允许方法与请求头均为显式列表。另有 Origin 中间件对携带非白名单 Origin 的请求直接返回 403 forbidden_origin（fm27lab/interfaces/http/app.py:181-189）。CORS 只约束浏览器，不构成鉴权，鉴权由 Bearer 令牌承担。

当前没有速率限制、Host 头校验与全局请求体上限，防线是回环监听加令牌；各端点自身上限见输入边界一节。

## 鉴权与令牌

鉴权矩阵测试遍历 app.routes 中全部 /api 方法，去掉 HEAD、OPTIONS 与文档路由，断言除公开白名单外的每个端点未携带 Authorization 时返回 401、错误码为 unauthorized、响应头含 WWW-Authenticate: Bearer（fm27lab/tests/test_security_boundaries.py:114-128）。公开白名单只包含 GET /api/health 与 GET /api/version，理由分别是客户端启动探活与 API 版本握手，两者都不返回任务或存档数据（fm27lab/interfaces/http/routes/system.py:40-62）。新增公开面必须先修改测试白名单与本文档。

令牌校验在 fm27lab/interfaces/http/common.py:38-55：HTTPBearer 以 auto_error=False 注入（fm27lab/interfaces/http/common.py:11），缺失或非 Bearer 时返回 missing bearer token 的 401 封套；否则对提交值 strip、检查 ASCII，并用 hmac.compare_digest 与配置令牌比较，失败返回 invalid bearer token 的 401。两份 401 都带 WWW-Authenticate: Bearer。

令牌来源有三处：Settings.token 字段以 field(repr=False) 避免打印（fm27lab/config.py:30），Settings.create 缺省使用 secrets.token_hex(32)（fm27lab/config.py:68），from_env 支持 FM27LAB_TOKEN 注入（fm27lab/config.py:82）。endpoint.json 以 0600 创建并原子替换，写入阶段失败时清理临时文件并保留既有描述符，ACL 收紧失败时删除新目标（fm27lab/sidecar.py:33-49）；Windows 用 icacls 去继承并只授权当前用户（fm27lab/sidecar.py:52-61），对应测试见 fm27lab/tests/test_serve.py:61-67、fm27lab/tests/test_endpoint.py:9-19、test_endpoint_write_failure_leaves_no_temporary_file 与 test_endpoint_replace_failure_preserves_previous_descriptor。

令牌不泄漏的回归覆盖三类响应面：401 响应体与响应头不含配置令牌，且不回显请求提交的错误令牌（test_unauthorized_responses_do_not_leak_token）；OpenAPI 文档不含令牌且声明 HTTPBearer 安全方案（test_openapi_declares_bearer_security）；500 只返回 internal server error 通用消息（fm27lab/interfaces/http/app.py:226-232、fm27lab/tests/test_http_health.py:93-106）。校验失败的 400 封套同样不回显请求体（fm27lab/interfaces/http/app.py:219-224）。

客户端侧只发现回环 endpoint，拒绝包含用户信息、query、fragment 或非回环主机的地址（fm27lab/client.py:77-98、fm27lab/client.py:101-129）；连接层拒绝一切重定向，避免 Bearer 头被转发到其他主机（fm27lab/client.py:52-56、fm27lab/client.py:237-248）；SidecarClient 的 repr 将令牌显示为 ***（fm27lab/client.py:170-171），错误文本不拼接令牌（fm27lab/client.py:200-258）。

## 文件系统边界

产物服务对 kind 与 filename 使用字符白名单（fm27lab/application/artifacts.py:14-15），拒绝 . 与 ..（fm27lab/application/artifacts.py:170-180），拒绝 kind 目录本身是符号链接（fm27lab/application/artifacts.py:37-40），对根目录与目标目录 resolve 后做包含检查（fm27lab/application/artifacts.py:42、fm27lab/application/artifacts.py:156-167），写入采用临时文件加 os.replace。HTTP 下载读取时要求记录路径为绝对路径且非符号链接，resolve 后必须位于产物根目录内（fm27lab/interfaces/http/routes/artifacts.py:82-96）。本文件的路径回归覆盖穿越文件名、外部路径记录污染、下载时符号链接替换与删除时外部符号链接目标保护（fm27lab/tests/test_security_boundaries.py:253-317），既有用例见 fm27lab/tests/test_artifacts_service.py:207-345 与 fm27lab/tests/test_http_artifacts.py:315-382。

实验物化先校验 job_id 白名单（fm27lab/application/experiment_material.py:27、fm27lab/application/experiment_material.py:189-196），在 data_dir 内 experiments 根目录 resolve 后检查是否仍位于 data_dir 之下（fm27lab/application/experiment_material.py:198-203），物化使用 staging 目录再 os.replace（fm27lab/application/experiment_material.py:61-187）。本文件覆盖 agent 目录被符号链接到外部时拒绝删除、以及穿越型 job_id 被忽略（fm27lab/tests/test_security_boundaries.py:318-344），既有用例见 fm27lab/tests/test_experiment_material.py:436-575。

存档导入的 source_path 只校验字符串非空且是普通文件，没有目录包含检查或扩展名白名单（fm27lab/application/save_import.py:201-208），HTTP 路由直接把该路径交给导入服务（fm27lab/interfaces/http/routes/save_import.py:91-100）。结果是持有令牌的调用者可以让 sidecar 读取任意可读文件；该路径来自本机原生文件对话框，属信任边界内的设计选择，列为已知边界而非缺陷。

引擎任务路径由内部 ExperimentService 构造，host 层校验类型、空值与换行并支持相对路径拼接（fm27lab/adapters/engine_native/host.py:895-907、fm27lab/adapters/engine_native/host.py:923-938），不做根目录包含检查，因为输入来自受信内部组件。

数据目录在 POSIX 下由 ensure_dirs 收紧为 0700（fm27lab/config.py:14-17、fm27lab/config.py:105-110）；Windows 保持既有目录语义。SQLite 连接层只创建父目录并使用 WAL（fm27lab/adapters/storage_sqlite/db.py:44-55），默认 umask 022 下库文件为 0644，隔离依赖 0700 父目录。

## 输入边界

| 入口 | 上限或校验 | 证据 |
| --- | --- | --- |
| 产物内容 | base64 解码后不超过 16 MiB，超限 413 payload_too_large，非法 base64 为 400 | fm27lab/interfaces/http/routes/artifacts.py:14、fm27lab/interfaces/http/routes/artifacts.py:138-148 |
| FMF 文件 | base64 字符数与解码字节均不超过 4 MiB，超限为 400 validation_failed | fm27lab/interfaces/http/routes/fmf.py:19-20、fm27lab/interfaces/http/routes/fmf.py:51-58 |
| 所有 JSON 输入模型 | strict 且 extra=forbid，未知字段与类型错误返回 400 | fm27lab/interfaces/http/routes/artifacts.py:17-22、fm27lab/interfaces/http/routes/experiments.py:18-19、fm27lab/interfaces/http/routes/settings.py:35-38 |
| 分页 | jobs 列表 limit 1 到 256，任务逐场结果 limit 1 到 200，offset 0 到 2^31-1，非整数返回 400 | fm27lab/interfaces/http/routes/jobs.py:136-149、fm27lab/interfaces/http/routes/jobs.py:361-373 |
| 实验提交 | seeds 最多 10000 且不得重复，workers 1 到 256，单批总场次不超过 10000 | fm27lab/interfaces/http/routes/experiments.py:13-23、fm27lab/interfaces/http/routes/experiments.py:27-38、fm27lab/application/experiments.py:20、fm27lab/application/experiments.py:170 |
| 结果比较 | candidate_job_ids 最多 32 个，reps 1 到 20000 | fm27lab/interfaces/http/routes/results.py:73-76 |
| 设置写入 | value 最多 65536 字节且深度不超过 64，note 最多 200 字符 | fm27lab/application/settings.py:14-16 |
| 错误封套 | 非法 JSON、未知字段、非法分页均返回 400 封套而非 500 | test_malformed_json_returns_400_envelope、test_unknown_input_fields_are_rejected、test_invalid_query_bounds_return_400_envelope |

不存在全局请求体上限，超大 JSON 在进入路由校验前会被框架读取；当前依赖各端点的解码上限与回环暴露面控制该风险（遗留风险一节）。

## 幂等与 SSE

幂等中间件只处理 POST、PATCH、DELETE 且路径以 /api/ 开头（fm27lab/interfaces/http/idempotency.py:18-19、fm27lab/interfaces/http/idempotency.py:126-127）。无幂等键直接放行；有键时先鉴权再读取请求体，未授权请求不会消耗 body（fm27lab/interfaces/http/idempotency.py:34-43、fm27lab/interfaces/http/idempotency.py:130-155）；请求指纹由方法、路径、query 与 body 组成，同一键用 asyncio 锁串行；只有 2xx 响应写入缓存，键非法返回 400 invalid_idempotency_key，同键不同载荷返回 409 idempotency_conflict。快照响应体上限 1 MiB、键为 128 字符白名单（fm27lab/adapters/storage_sqlite/idempotency.py:13、fm27lab/adapters/storage_sqlite/idempotency.py:15）。仓储层提供 prune（fm27lab/adapters/storage_sqlite/idempotency.py:71-76），但在生产代码中没有调用方，幂等响应表会随写入持续增长，属遗留风险。

SSE 端点 /api/events 要求 Bearer（fm27lab/interfaces/http/routes/system.py:96-100），Last-Event-ID 必须为非负整数否则 400（fm27lab/interfaces/http/routes/system.py:102-112），响应为 text/event-stream 并禁用缓存（fm27lab/interfaces/http/routes/system.py:113-123）；事件循环在客户端断开后注销订阅，既有测试见 fm27lab/tests/test_http_events.py:194。

## 仓库隐私

扫描方法如下：以 git ls-files 的跟踪清单为输入，检索私钥块、令牌赋值、Authorization Bearer 字面值、邮箱与绝对用户路径；检查 private 与 data 工作树目录是否存在被跟踪文件；读取 SOURCE_MANIFEST.json 检查键集合；检索 .gitignore 的覆盖规则。结论是无真实令牌、私钥与个人信息入库：唯一命中为文档示例占位路径 /home/user/.fm27lab（docs/AGENT_INTEGRATION.md:79-80、docs/AGENT_QUICKSTART.md:103）与文档中的错误令牌示例 wrong（docs/AGENT_VERIFICATION.md:106）。扫描把测试与文档中的占位令牌字面值排除在泄漏判定之外，例如 fm27lab/tests/test_http_health.py 的测试令牌与 docs/AGENT_VERIFICATION.md:106 的示例值。

git ls-files 结果中不存在 private/、endpoint.json、*.db、*.jsonl、*.fm、*.fmf、*.pkm 与 .env。SOURCE_MANIFEST.json 共 394 个条目，不含 private 前缀、*.db 与 endpoint.json，由 test_source_manifest_excludes_private_runtime_files 守护。.gitignore 覆盖 /private/、/data/、*.jsonl、*.fm、*.fmf、*.pkm、.env、*.db 与 endpoint.json（.gitignore:4-5、.gitignore:7、.gitignore:10、.gitignore:16-21），由 test_gitignore_covers_private_and_runtime_data 守护；该用例同时用 git ls-files 校验跟踪清单不含对应模式，git 不可用时跳过跟踪检查并保留忽略规则断言。

*.db 与 endpoint.json 已单列为忽略规则（.gitignore:20-21）。默认数据目录位于用户主目录（fm27lab/config.py:20-24），仓库内数据目录由 /data/ 覆盖；若把 FM27LAB_DATA 指向仓库内其他目录，仍可能通过 git add -f 强制跟踪，保持默认数据目录即可。

本文件与 fm27lab/tests/test_security_boundaries.py 均纳入提交前统一重建的 SOURCE_MANIFEST.json；清单由发布流程重建并在发布检查中校验。

## 已知边界与遗留风险

1. endpoint.json 含明文令牌，同机同用户进程可读；0600 与 0700 目录只隔离其他用户，不防同一用户下的恶意进程。
2. 无 TLS，令牌以明文经回环 HTTP 传输，同机特权进程可嗅探。
3. 引擎二进制按路径信任，engine_root 指向外部 FM 安装后 native host 直接执行，没有签名或完整性校验（fm27lab/adapters/engine_native/host.py:895-938）。
4. 存档导入 source_path 无目录包含检查，持有令牌者可让 sidecar 读取任意可读文件（fm27lab/application/save_import.py:201-208）。
5. 无速率限制、无 Host 头校验、无全局请求体上限，防线依赖回环监听与令牌。
6. 幂等响应表 prune 无调用方，长期使用会增长（fm27lab/adapters/storage_sqlite/idempotency.py:71-76）。
7. 默认 umask 022 下 SQLite 文件为 0644，只依赖父目录 0700；若用户放宽目录权限，任务与存档元数据可被同机用户读取。
8. /api/docs 与 /api/openapi.json 公开可读，只含接口结构，不含数据与令牌；保持现状以避免改变公共契约。
9. Tauri WebView 内的前端脚本可通过 invoke 获取连接信息，WebView 内的 XSS 等价于令牌泄露；前端转义规范属于 web 目录，本次未审计。
10. data_dir 的父目录权限由用户环境决定，sidecar 只收紧自身创建的三级目录。

## 修复记录

审计发现一个真实缺陷并已最小修复：sidecar 的 data_dir、agent、exports 原先按 umask 默认值创建为 0755，SQLite 文件为 0644，同机其他用户可以读取任务与存档元数据，与 endpoint.json 0600 的既有意图不一致。修复方式是在 fm27lab/config.py:14-17 新增私有函数，在 POSIX 下把目录 chmod 为 0700，并在 ensure_dirs 中对三个目录调用（fm27lab/config.py:105-110）；Windows 不做改动，继续依赖 icacls。

判别测试为 test_data_directories_are_owner_only（fm27lab/tests/test_security_boundaries.py:243-252）：修复前该用例断言 0755 目录失败，修复后通过。本次修复不涉及请求契约、配置字段或 OpenAPI 输出。

本次审计未发现其他需要修复的缺陷。

## 回归测试与变异验证

新增测试文件 fm27lab/tests/test_security_boundaries.py，共 22 条。鉴权覆盖矩阵与文档边界 2 条；令牌不泄漏与 OpenAPI Bearer 声明 2 条；endpoint 描述符、endpoint 文件权限、写入失败清理与数据目录权限 5 条；路径逃逸 6 条，其中产物 4 条、实验目录 2 条；输入边界 5 条；仓库隐私 2 条。既有安全覆盖继续由 fm27lab/tests/test_http_health.py、fm27lab/tests/test_http_events.py、fm27lab/tests/test_http_artifacts.py、fm27lab/tests/test_artifacts_service.py、fm27lab/tests/test_experiment_material.py、fm27lab/tests/test_serve.py、fm27lab/tests/test_endpoint.py、fm27lab/tests/test_cli_client.py 与 fm27lab/tests/test_http_idempotency.py 承担。后端全量用例在本次修复后为 2096 条全部通过，ruff 检查通过。

对新增与扩展测试做了 11 个变异，全部被杀死：

| 变异 | 改法 | 结果 | 杀死用例 |
| --- | --- | --- | --- |
| M1 | require_token 首行直接 return None | killed | test_api_authentication_matrix |
| M2 | 401 消息拼接 expected 令牌 | killed | test_unauthorized_responses_do_not_leak_token |
| M3 | endpoint.json 打开模式由 0o600 改为 0o644 | killed | test_endpoint_file_permissions |
| M4 | 删除产物下载的 resolved.is_relative_to 检查 | killed | test_artifact_content_rejects_paths_outside_root |
| M5 | 删除实验根的 root.is_relative_to 检查 | killed | test_experiment_discard_rejects_symlinked_agent_dir |
| M6 | 目录权限函数直接 return | killed | test_data_directories_are_owner_only |
| M7 | 删除产物 16 MiB 上限判断 | killed | test_oversized_artifact_payload_returns_413_envelope |
| M8 | endpoint_payload 删除 token 字段 | killed | test_endpoint_descriptor_contract |
| M9 | write_endpoint 去掉临时文件 finally 清理 | killed | test_endpoint_write_failure_leaves_no_temporary_file、test_endpoint_replace_failure_preserves_previous_descriptor |
| M10 | CORSMiddleware allow_credentials 改为 True | killed | test_cors_and_origin_enforcement |
| M11 | .gitignore 删除 *.db 规则 | killed | test_gitignore_covers_private_and_runtime_data |

## 维护约定

新增 /api 路由必须挂 Depends(require_token)；确需公开时必须同步修改 fm27lab/tests/test_security_boundaries.py:33 的白名单并更新本文档。新增产物、实验物化或文件导入入口必须做 resolve 后的目录包含检查与字符白名单，并在 test_security_boundaries.py 增加判别测试。修改 endpoint 载荷字段必须同步 test_endpoint_descriptor_contract 与本文档。发布流程需要重新生成 SOURCE_MANIFEST.json 以纳入本文档。
