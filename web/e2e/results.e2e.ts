import { expect, test, type Page } from "@playwright/test";

import { MockApi } from "./support/mock-api";
import { browserBlocker } from "./support/readiness";

const blocker = browserBlocker();
test.skip(blocker !== null, blocker ?? "");

async function openResults(page: Page, api: MockApi): Promise<void> {
  await page.goto("/results");
  await expect(page.getByRole("region", { name: "实验任务" })).toBeVisible();
  await expect(page.locator(".metric-grid")).toBeVisible();
  expect(api.requestsFor("GET", "/api/jobs").length).toBeGreaterThan(0);
}

function metricCard(page: Page, label: string) {
  return page.locator(".metric").filter({
    has: page.locator(".metric-label", { hasText: new RegExp("^" + label + "$") }),
  });
}

test("结果页展示指标卡片与逐场记录", async ({ page }) => {
  const api = await MockApi.install(page);
  await openResults(page, api);

  await expect(page.getByRole("button", { name: "测试实验", exact: true })).toHaveAttribute(
    "aria-current",
    "true",
  );
  const meta = page.locator(".results-meta").first();
  await expect(meta).toContainText("测试实验");
  await expect(meta).toContainText("完成 100 / 100");

  await expect(metricCard(page, "场次").locator(".metric-value")).toHaveText("6");
  await expect(metricCard(page, "胜 / 平 / 负").locator(".metric-value")).toHaveText("3 / 1 / 2");
  await expect(metricCard(page, "胜率").locator(".metric-value")).toHaveText("50.0%");
  await expect(metricCard(page, "胜率").locator(".metric-hint")).toHaveText(
    "95% 区间 20.0%–80.0%",
  );
  await expect(metricCard(page, "场均进球").locator(".metric-value")).toHaveText("1.50");
  await expect(metricCard(page, "场均失球").locator(".metric-value")).toHaveText("1.20");
  await expect(metricCard(page, "场均积分").locator(".metric-value")).toHaveText("1.66");
  await expect(metricCard(page, "xG").locator(".metric-value")).toHaveText("1.80");
  await expect(metricCard(page, "xGA").locator(".metric-value")).toHaveText("1.10");
  await expect(metricCard(page, "控球率").locator(".metric-value")).toHaveText("52.4%");
  await expect(metricCard(page, "场均射门").locator(".metric-value")).toHaveText("9.5");
  await expect(metricCard(page, "传球成功率").locator(".metric-value")).toHaveText("84.0%");
  await expect(metricCard(page, "配对场次").locator(".metric-value")).toHaveText("6");
  await expect(metricCard(page, "净胜球差").locator(".metric-value")).toHaveText("+0.50");

  const runs = page.getByRole("table", { name: "逐场记录" });
  await expect(runs).toBeVisible();
  const rows = runs.getByRole("row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(1)).toContainText("2–1");
  await expect(rows.nth(1)).toContainText("已验证");
  await expect(rows.nth(2)).toContainText("1–1");
  await expect(rows.nth(2)).toContainText("未验证");
  await expect(page.locator(".jobs-pager")).toContainText("共 2 场");
  expect(api.requestsFor("GET", "/api/jobs/job-1001/runs").length).toBe(1);
});

test("客队战术池可展开查看明细", async ({ page }) => {
  const api = await MockApi.install(page);
  await openResults(page, api);

  const pool = page.getByRole("region", { name: "客队战术池" });
  await expect(pool).toBeVisible();
  await expect(pool).toContainText("共 2 套");

  const toggle = pool.getByRole("button", { name: "展开" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(pool.getByRole("button", { name: "折叠" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  const table = page.getByRole("table", { name: "客队战术池明细" });
  await expect(table).toBeVisible();
  const rows = table.getByRole("row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(1)).toContainText("高位压迫 4-2-3-1");
  await expect(rows.nth(1)).toContainText("真实名单");
  await expect(rows.nth(2)).toContainText("低位防守 5-3-2");

  await pool.getByRole("button", { name: "折叠" }).click();
  await expect(table).toBeHidden();
  expect(api.requestsFor("GET", "/api/jobs/job-1001/pool-summary").length).toBeGreaterThan(0);
});

test("任务对比展示配对结果", async ({ page }) => {
  const api = await MockApi.install(page);
  await openResults(page, api);

  await page.getByRole("checkbox", { name: "候选任务 对照实验（job-1002）" }).check();
  const comparePanel = page.getByRole("region", { name: "任务对比" });
  await expect(comparePanel).toContainText("基线");
  await expect(comparePanel).toContainText("测试实验");

  await comparePanel.getByRole("button", { name: "开始对比" }).click();
  const resultTable = page.getByRole("table", { name: "任务对比结果" });
  await expect(resultTable).toBeVisible();

  const request = api.lastRequest("POST", "/api/results/compare");
  expect(request?.body).toMatchObject({
    baseline_job_id: "job-1001",
    candidate_job_ids: ["job-1002"],
    variant: "B",
    side: 0,
  });

  const row = resultTable.getByRole("row").nth(1);
  await expect(row).toContainText("对照实验");
  await expect(row).toContainText("可比");
  await expect(row).toContainText("同种子 6 场");
  await expect(row).toContainText("+10.0%");
  await expect(row.locator(".compare-ci")).toHaveText("95% 区间 [2.0%, 18.0%]");
  await expect(row).toContainText("+0.30");
});

test("统计视角切换后按客队请求摘要", async ({ page }) => {
  const api = await MockApi.install(page);
  await openResults(page, api);

  const view = page.getByRole("group", { name: "统计视角" });
  await view.getByRole("button", { name: "客队" }).click();
  await expect(view.getByRole("button", { name: "客队" })).toHaveAttribute("aria-pressed", "true");

  await expect
    .poll(() => api.requestsFor("GET", "/api/jobs/job-1001/summary").length)
    .toBeGreaterThanOrEqual(2);
  const sides = api
    .requestsFor("GET", "/api/jobs/job-1001/summary")
    .map((entry) => entry.query["side"]);
  expect(sides).toContain("1");
  await expect(page.locator(".metric-grid")).toBeVisible();
});

test("任务摘要加载失败时展示错误与重试", async ({ page }) => {
  const api = await MockApi.install(page);
  api.failAlways("GET", "/api/jobs/job-1001/summary", 500, "摘要读取失败，请稍后重试");
  await page.goto("/results");

  const alert = page.getByRole("alert").filter({ hasText: "摘要读取失败，请稍后重试" });
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "重试" })).toBeVisible();
  expect(api.requestsFor("GET", "/api/jobs/job-1001/summary").length).toBeGreaterThan(0);
});

test("结果页按状态筛选后可批量删除任务", async ({ page }) => {
  const api = await MockApi.install(page);
  await openResults(page, api);

  await page.getByRole("combobox", { name: "状态筛选" }).selectOption("completed");
  await expect(page.getByRole("button", { name: "测试实验", exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "全选当前筛选结果" }).check();
  await expect(page.locator(".jobs-bulk-count")).toHaveText("已选 2 个任务");

  await page.getByRole("button", { name: "删除所选" }).click();
  const dialog = page.getByRole("alertdialog", { name: "确认批量删除" });
  await expect(dialog).toContainText("将删除 2 个任务");
  await dialog.getByRole("button", { name: "确认删除" }).click();

  const feedback = page.locator("[aria-label='批量删除结果']");
  await expect(feedback).toContainText("已删除 2 个任务");
  const request = api.lastRequest("DELETE", "/api/jobs");
  expect((request?.body as { ids?: string[] } | null)?.ids?.sort()).toEqual([
    "job-1001",
    "job-1002",
  ]);
});
