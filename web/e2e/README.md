# Playwright 端到端测试

浏览器测试位于 `web/e2e`，使用 chromium 驱动真实渲染，并通过 `page.route` 拦截全部 `/api/**` 请求返回固定夹具，不依赖 sidecar 进程。

## 运行方式

```bash
cd web
pnpm exec playwright install --with-deps chromium   # 首次安装浏览器与系统依赖
pnpm test:e2e
```

配置项见 `web/playwright.config.ts`：

- `webServer` 自行拉起 `vite --port 4310 --strictPort`，并注入 `VITE_API_URL=""` 使前端以同源 `/api/**` 发起请求，便于路由拦截。
- 失败时保留截图与 trace，HTML 报告输出到 `web/playwright-report`，原始结果输出到 `web/test-results`。
- 用例文件统一使用 `.e2e.ts` 后缀，避免被 vitest 的默认匹配规则收集。

## 断网或缺少系统库的环境

启动前会探测 `chromium.executablePath()` 是否存在，并在 Linux 上检查 `ldd` 是否报告缺失的系统库。探测到缺失时整组用例标记为跳过并给出安装提示，不会把环境问题误报成失败。安装方式：

```bash
pnpm exec playwright install --with-deps chromium
```

无法安装系统包时，可把缺失库所在目录加入 `LD_LIBRARY_PATH`，例如本机已缓存依赖的目录：

```bash
LD_LIBRARY_PATH="$PWD/../.agents/e2e/deps/usr/lib/x86_64-linux-gnu" pnpm test:e2e
```

容器或 root 受限环境下 chromium 需要关闭沙箱，配置已默认传入 `--no-sandbox`。

## 夹具与拦截

`e2e/support/fixtures.ts` 提供战术场景、目录、草案、任务、指标、逐场记录、战术池等固定数据；`e2e/support/mock-api.ts` 记录请求并提供 `failNext`/`failAlways` 注入失败响应，断言时可直接读取 `api.requests`。`/api/events` 请求保持挂起，避免前端按秒重连造成请求噪声。

## 覆盖范围

- `app-shell.e2e.ts`：应用加载、连接状态、主导航、键盘焦点可见性、健康检查失败提示。
- `tactics.e2e.ts`：两阶段战术板、编辑与保存草稿、放弃确认、键盘选位交换、新建战术对话框焦点管理、保存失败提示。
- `experiments-jobs.e2e.ts`：资源配置自动填充、资源预检、提交实验、启动结果、任务列表取消与删除、批量删除、状态筛选。
- `results.e2e.ts`：指标卡片、逐场记录、客队战术池展开、任务对比、统计视角、摘要错误与批量删除。
- `accessibility.e2e.ts`：战术板、实验、任务、结果、设置五个主要页面的 axe 扫描，serious 与 critical 违规必须为零。

## CI

`.github/workflows/ci.yml` 的 `playwright` job 在 ubuntu-latest 上安装 chromium 与系统依赖后执行全部用例，并在失败或成功时上传 `playwright-report` 与 `test-results`。
