import { expect, test, type Page } from "@playwright/test";

import { MockApi } from "./support/mock-api";
import { browserBlocker } from "./support/readiness";

const blocker = browserBlocker();
test.skip(blocker !== null, blocker ?? "");

async function openApp(page: Page, path = "/"): Promise<MockApi> {
  const api = await MockApi.install(page);
  await page.goto(path);
  return api;
}

test("应用加载后展示连接状态与主导航", async ({ page }) => {
  await openApp(page);

  await expect(page).toHaveURL(/\/tactics$/);
  await expect(page.getByRole("heading", { level: 1, name: "战术板" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "sidecar 正常" })).toBeVisible();
  await expect(page.getByText("SQLite 就绪")).toBeVisible();
  await expect(page.getByText("v2.0.0.dev0")).toBeVisible();

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav).toBeVisible();
  for (const label of ["战术板", "定位球", "球员属性", "存档战术库", "实验", "实验结果", "任务管理", "设置", "帮助"]) {
    await expect(nav.getByRole("link", { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByText("sidecar 已连接")).toBeVisible();
});

test("导航切换页面并高亮当前页", async ({ page }) => {
  await openApp(page);
  const nav = page.getByRole("navigation", { name: "主导航" });

  await nav.getByRole("link", { name: "实验", exact: true }).click();
  await expect(page).toHaveURL(/\/experiments$/);
  await expect(page.getByRole("heading", { level: 1, name: "实验" })).toBeVisible();
  await expect(page.getByRole("form", { name: "实验提交" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "实验", exact: true })).toHaveAttribute("aria-current", "page");

  await nav.getByRole("link", { name: "任务管理", exact: true }).click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByRole("heading", { level: 1, name: "任务管理" })).toBeVisible();
  await expect(page.getByRole("table", { name: "任务列表" })).toBeVisible();

  await nav.getByRole("link", { name: "战术板", exact: true }).click();
  await expect(page).toHaveURL(/\/tactics$/);
  await expect(page.getByRole("heading", { level: 1, name: "战术板" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "战术板", exact: true })).toHaveAttribute("aria-current", "page");
});

test("键盘可进入页面且焦点轮廓可见", async ({ page }) => {
  await openApp(page);

  const styles: string[] = [];
  for (let index = 0; index < 4; index += 1) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const element = document.activeElement;
      if (element === null) return null;
      const style = getComputedStyle(element);
      return {
        tag: element.tagName,
        label: element.getAttribute("aria-label") ?? element.textContent?.trim().slice(0, 20) ?? "",
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
      };
    });
    expect(focused).not.toBeNull();
    expect(focused?.outlineStyle).not.toBe("none");
    expect(Number.parseFloat(focused?.outlineWidth ?? "0")).toBeGreaterThanOrEqual(2);
    styles.push(`${focused?.tag}:${focused?.label}`);
  }
  expect(styles.length).toBe(4);
});

test("健康检查失败时提示 sidecar 未连接", async ({ page }) => {
  const api = await MockApi.install(page);
  api.failAlways("GET", "/api/health", 500, "sidecar 健康检查失败");
  await page.goto("/tactics");

  const alert = page.locator(".connection-error");
  await expect(alert).toBeVisible();
  await expect(alert).toHaveAttribute("role", "alert");
  await expect(alert).toContainText("sidecar 健康检查失败");
  await expect(page.getByRole("status").filter({ hasText: "sidecar 未连接" })).toBeVisible();
  await expect(page.locator(".rail-footer").getByText("sidecar 未连接")).toBeVisible();
});