import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { MockApi } from "./support/mock-api";
import { browserBlocker } from "./support/readiness";

const blocker = browserBlocker();
test.skip(blocker !== null, blocker ?? "");

type PageCase = {
  name: string;
  path: string;
  ready: (page: Page) => Promise<void>;
};

const PAGES: PageCase[] = [
  {
    name: "战术板",
    path: "/tactics",
    ready: async (page) => {
      await expect(page.getByRole("group", { name: "有球战术板" })).toBeVisible();
    },
  },
  {
    name: "实验",
    path: "/experiments",
    ready: async (page) => {
      await expect(page.getByRole("form", { name: "实验提交" })).toBeVisible();
      await expect(page.locator(".experiment-precheck-pass")).toBeVisible();
    },
  },
  {
    name: "任务管理",
    path: "/jobs",
    ready: async (page) => {
      await expect(page.getByRole("table", { name: "任务列表" })).toBeVisible();
    },
  },
  {
    name: "实验结果",
    path: "/results",
    ready: async (page) => {
      await expect(page.locator(".metric-grid")).toBeVisible();
    },
  },
  {
    name: "设置",
    path: "/settings",
    ready: async (page) => {
      await expect(page.getByTestId("settings-engine")).toBeVisible();
      await expect(page.getByRole("form", { name: "引擎与游戏目录配置" })).toBeVisible();
    },
  },
];

for (const pageCase of PAGES) {
  test(`${pageCase.name}页面没有 serious 与 critical 可访问性违规`, async ({ page }) => {
    await MockApi.install(page);
    await page.goto(pageCase.path);
    await pageCase.ready(page);

    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        targets: violation.nodes.map((node) => node.target.join(" ")),
      }));

    expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
  });
}
