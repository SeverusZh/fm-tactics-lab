# 性能基准

Phase 7 的性能基线，覆盖 sidecar 只读 HTTP 路径与纯领域辅助函数。测量脚本 scripts/benchmark.py 只使用标准库与已安装依赖，不依赖原生引擎二进制。

## 测量方法

基准在进程内顺序执行，每项指标先预热 2 次，再逐次用 time.perf_counter 记录每次调用耗时并汇总。输出字段的含义如下。

- total_ms：全部计时调用耗时之和。
- per_op_ms：total_ms 除以 iterations。
- p50_ms 与 p95_ms：逐次耗时的分位数，采用线性插值。
- throughput_per_s：每秒可完成的调用次数，由 iterations 与 total_ms 推算。
- quick 模式用于测试与快速自查，迭代次数少；full 模式用于本文档的基线数字。

HTTP 只读路径通过 fastapi.testclient.TestClient 在进程内调用，数据目录为临时目录，用仓储层单事务预置数据后构造应用，不启动 Uvicorn，不涉及真实网络。场景与战术池使用合成的 23 人阵容，对比成本使用 200 个合成配对差值。

## 环境

- 测量日期：2026-11-14。
- Python：3.12.16。
- 平台：Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43。
- 逻辑 CPU：32。
- 依赖：仓库 .venv 中已安装的 fastapi、httpx、pytest 等，无额外安装。

## 复现

仓库根目录执行。

~~~bash
.venv/bin/python scripts/benchmark.py --quick
.venv/bin/python scripts/benchmark.py --quick --json
.venv/bin/python scripts/benchmark.py --json
~~~

full 模式即省略 --quick。--json 输出结构化报告到标准输出，人类模式输出表格。

## 实测结果

full 模式运行 .venv/bin/python scripts/benchmark.py --json，2026-11-14 本机一次运行，表内数字为这次运行的输出，复跑会有波动。数据规模：50 个任务，其中一个任务含 100 条运行记录，50 组同种子 A/B 配对；每队 23 人；客队池 8 条；对比数据 200 个配对差值，bootstrap 重抽样 2000 次。

| 指标 | 单位 | 迭代 | 总耗时 ms | 单次 ms | p50 ms | p95 ms | 吞吐每秒 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| http.jobs_list | request | 50 | 237.712 | 4.754 | 4.726 | 5.232 | 210.34 |
| http.job_runs | request | 50 | 286.002 | 5.720 | 5.418 | 5.934 | 174.82 |
| http.jobs_summary | request | 50 | 253.074 | 5.061 | 5.032 | 5.493 | 197.57 |
| scenario.normalize | scenario | 200 | 235.196 | 1.176 | 1.171 | 1.224 | 850.36 |
| pool.expand_away | seed | 100 | 71.822 | 0.718 | 0.714 | 0.767 | 1392.33 |
| compare.bootstrap_ci | call | 30 | 1280.104 | 42.670 | 42.164 | 45.582 | 23.44 |

任务列表请求 GET /api/jobs?limit=50 返回满页 50 条；比赛列表请求 GET /api/jobs/bench-summary-job/runs?limit=100 返回 100 条；结果汇总请求 GET /api/jobs/bench-summary-job/summary 覆盖 100 条运行记录。任务契约中的 /api/results/{id}/summary 在当前实现中不存在，实际只读汇总路由是 GET /api/jobs/{job_id}/summary，基准按真实路由测量。

## 局限

- 本机没有原生引擎二进制，基准不覆盖引擎编译、加载与执行路径，只覆盖不依赖引擎的 Python 路径。
- TestClient 在进程内直接调用应用，省去了真实网络的 socket、协议栈与 Uvicorn 开销，结果不能等同于真实回环 HTTP 的延迟。
- 计时受 WSL2 调度、CPU 频率与后台负载影响，单次运行存在波动；quick 模式迭代次数少，数字仅用于自查，不作为基线。
- 预置数据为合成数据，场景、池与配对差值不来自真实比赛，分布与访问热点不代表实际使用情况。
- 基准为单进程串行测量，不反映并发请求下的吞吐与尾延迟。

## 结论

- 只读 HTTP 路径在进程内单次约 4.7 到 5.7 毫秒，列表、运行分页与结果汇总处于同一量级，读取 100 条运行记录的汇总没有明显放大。
- 场景归一化单次约 1.2 毫秒，战术池每个种子展开约 0.7 毫秒，二者适合在一次实验提交中批量调用。
- bootstrap 重抽样 2000 次单次约 42 毫秒，是纯 Python 路径中成本最高的操作；对比大量候选时应控制重抽样次数或复用结果。
