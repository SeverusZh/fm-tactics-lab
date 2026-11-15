import { expect, test } from "@playwright/test";

import { CONCURRENCY_CHECK } from "./support/fixtures";
import { MockApi } from "./support/mock-api";
import { browserBlocker } from "./support/readiness";

const blocker = browserBlocker();
test.skip(blocker !== null, blocker ?? "");

async function openExperiments(
  page: import("@playwright/test").Page,
  options: Parameters<typeof MockApi.install>[1] = {},
): Promise<MockApi> {
  const api = await MockApi.install(page, options);
  await page.goto("/experiments");
  await expect(page.getByRole("form", { name: "实验提交" })).toBeVisible();
  return api;
}

async function selectDraft(page: import("@playwright/test").Page): Promise<void> {
  const select = page.getByRole("combobox", { name: "草案", exact: true });
  await select.selectOption("draft-1");
  await expect(select).toHaveValue("draft-1");
  await expect(page.getByRole("spinbutton", { name: "并行数" })).toHaveValue("6");
}

test("资源配置自动填充并通过资源预检", async ({ page }) => {
  await openExperiments(page);
  await selectDraft(page);

  await expect(page.getByRole("spinbutton", { name: "CPU 核数" })).toHaveValue("8");
  await expect(page.getByRole("spinbutton", { name: "可用内存（GiB）" })).toHaveValue("8");
  await expect(page.getByRole("spinbutton", { name: "空闲磁盘（GiB）" })).toHaveValue("100");
  await expect(page.getByRole("spinbutton", { name: "场数" })).toHaveValue("100");
  await expect(page.locator(".experiment-precheck-pass")).toContainText(
    "资源预检通过，推荐并行数 6",
  );
  await expect(page.getByText("总场数 = 100 场")).toBeVisible();
  await expect(page.getByRole("button", { name: "开始实验（100 场）" })).toBeEnabled();
});

test("提交实验后跳转任务列表并看到新任务", async ({ page }) => {
  const api = await openExperiments(page);
  await selectDraft(page);

  await page.getByRole("button", { name: "开始实验（100 场）" }).click();

  const outcome = page.getByRole("status", { name: "启动结果" });
  await expect(outcome).toBeVisible();
  await expect(outcome).toContainText("实验已启动：新实验");
  await expect(outcome).toContainText("总场数 100");

  const submitted = api.requestsFor("POST", "/api/experiments");
  expect(submitted).toHaveLength(1);
  expect(submitted[0].body?.["draft_id"]).toBe("draft-1");
  expect((submitted[0].body?.["seeds"] as unknown[]).length).toBe(100);
  expect(api.requestsFor("POST", "/api/experiments/start")).toHaveLength(1);

  await outcome.getByRole("link", { name: "查看任务" }).click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByRole("row").filter({ hasText: "新实验" })).toBeVisible();
});

test("资源预检未通过时阻塞提交", async ({ page }) => {
  await openExperiments(page, {
    concurrency: {
      ...CONCURRENCY_CHECK,
      allowed: false,
      code: "insufficient_memory",
      warnings: ["可用内存不足"],
      recommended_workers: 2,
    },
  });
  await selectDraft(page);

  await expect(page.locator(".experiment-precheck-fail")).toContainText(
    "资源预检未通过：可用内存不足",
  );
  await expect(page.getByRole("button", { name: "开始实验（100 场）" })).toBeDisabled();
  const problems = page.getByRole("list", { name: "阻塞原因" });
  await expect(problems).toContainText("资源预检未通过");
});

test("实验提交失败时展示错误与重试入口", async ({ page }) => {
  const api = await openExperiments(page);
  api.failAlways("POST", "/api/experiments", 500, "实验提交失败，请稍后重试");
  await selectDraft(page);

  await page.getByRole("button", { name: "开始实验（100 场）" }).click();

  const alert = page.getByRole("alert").filter({ hasText: "实验提交失败，请稍后重试" });
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "重试" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始实验（100 场）" })).toBeEnabled();
});

test("没有草案时提示先创建战术", async ({ page }) => {
  await openExperiments(page, { drafts: [] });

  await expect(page.locator(".experiment-empty")).toContainText("还没有草案");
  await expect(page.getByRole("link", { name: "前往战术板新建" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^开始实验/ })).toBeDisabled();
});

test("任务列表支持两步取消任务", async ({ page }) => {
  const api = await MockApi.install(page);
  await page.goto("/jobs");
  const row = page.getByRole("row").filter({ hasText: "进行中的实验" });
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: "取消", exact: true }).click();
  await row.getByRole("button", { name: "确认取消" }).click();

  await expect(page.locator(".jobs-notice")).toHaveText("已取消任务「进行中的实验」");
  expect(api.requestsFor("POST", "/api/jobs/job-1003/cancel")).toHaveLength(1);
  await expect(page.getByRole("row").filter({ hasText: "进行中的实验" })).toContainText("已取消");
});

test("任务列表支持两步删除任务", async ({ page }) => {
  const api = await MockApi.install(page);
  await page.goto("/jobs");
  const row = page.getByRole("row").filter({ hasText: "失败实验" });
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: "删除", exact: true }).click();
  await row.getByRole("button", { name: "确认删除" }).click();

  await expect(page.locator(".jobs-notice")).toHaveText("已删除任务「失败实验」");
  expect(api.requestsFor("DELETE", "/api/jobs/job-1004")).toHaveLength(1);
  await expect(page.getByRole("row").filter({ hasText: "失败实验" })).toBeHidden();
});

test("任务列表批量删除可删除任务", async ({ page }) => {
  const api = await MockApi.install(page);
  await page.goto("/jobs");
  await expect(page.getByRole("table", { name: "任务列表" })).toBeVisible();

  await page.getByRole("checkbox", { name: "全选当前页任务" }).check();
  await expect(page.locator(".jobs-bulk")).toContainText("已选 3 个任务");

  await page.getByRole("button", { name: "删除所选" }).click();
  const dialog = page.getByRole("alertdialog", { name: "确认批量删除" });
  await expect(dialog).toContainText("将删除 3 个任务");
  await dialog.getByRole("button", { name: "确认删除" }).click();

  const result = page.locator("[aria-label='批量删除结果']");
  await expect(result).toContainText("已删除 3 个任务");
  const batch = api.requestsFor("DELETE", "/api/jobs");
  expect(batch).toHaveLength(1);
  expect((batch[0].body?.["ids"] as string[]).sort()).toEqual(
    ["job-1001", "job-1002", "job-1004"].sort(),
  );
});

test("任务状态筛选携带 status 查询", async ({ page }) => {
  const api = await MockApi.install(page);
  await page.goto("/jobs");
  await expect(page.getByRole("table", { name: "任务列表" })).toBeVisible();

  await page.getByRole("combobox", { name: "状态筛选" }).selectOption("completed");

  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(page.getByRole("table", { name: "任务列表" })).not.toContainText("进行中的实验");
  const filtered = api.requests.find(
    (entry) => entry.method === "GET" && entry.path === "/api/jobs" && entry.query["status"] === "completed",
  );
  expect(filtered).toBeDefined();
});