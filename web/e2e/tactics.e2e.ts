import { expect, test } from "@playwright/test";

import { MockApi } from "./support/mock-api";
import { browserBlocker } from "./support/readiness";

const blocker = browserBlocker();
test.skip(blocker !== null, blocker ?? "");

const SLOT_01 = /^槽位 01，主01，GK，门将组织$/;

async function openTactics(page: import("@playwright/test").Page): Promise<MockApi> {
  const api = await MockApi.install(page);
  await page.goto("/tactics");
  await expect(page.getByRole("button", { name: "编辑阵型" })).toBeEnabled();
  return api;
}

test("战术板展示两阶段阵型与球队指令", async ({ page }) => {
  await openTactics(page);

  await expect(page.getByRole("heading", { level: 2, name: "双阶段战术板" })).toBeVisible();
  await expect(page.getByRole("toolbar", { name: "草稿工具栏" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");

  const pitch = page.getByRole("group", { name: "有球战术板" });
  await expect(pitch).toBeVisible();
  await expect(pitch.getByRole("listitem")).toHaveCount(11);
  await expect(pitch.locator("li.tactics-slot").first()).toHaveAttribute(
    "title",
    "01 · 主01 · GK · 门将组织",
  );

  await page.getByRole("button", { name: "无球", exact: true }).click();
  const awayPitch = page.getByRole("group", { name: "无球战术板" });
  await expect(awayPitch).toBeVisible();
  await expect(awayPitch.locator("li.tactics-slot").first()).toHaveAttribute(
    "title",
    "01 · 主01 · GK · 门将防守",
  );

  await expect(page.getByText("球队指令对两个阶段共用")).toBeHidden();
  await expect(page.getByRole("heading", { level: 2, name: "球队指令" })).toBeVisible();
});

test("编辑阵型后保存草稿并提交场景", async ({ page }) => {
  const api = await openTactics(page);

  await page.getByRole("button", { name: "编辑阵型" }).click();
  await expect(page.locator(".tactics-dirty-note")).toHaveText("编辑阵型中，修改后请保存或放弃");

  const pitch = page.getByRole("group", { name: "有球战术板" });
  await expect(pitch.getByRole("button")).toHaveCount(11);

  await page.getByRole("button", { name: /^槽位 09，/ }).click();
  const roleSelect = page.getByRole("combobox", { name: "角色" });
  await expect(roleSelect).toBeVisible();
  await roleSelect.selectOption({ label: "中锋支点" });
  await expect(page.locator(".tactics-dirty-note")).toContainText("有未保存修改");
  await expect(page.getByRole("combobox", { name: "球队指令：传球方式" })).toHaveValue("1");

  await page.getByRole("button", { name: "保存", exact: true }).click();

  await expect(page.locator(".tactics-save-notice")).toHaveText("已保存");
  await expect(page.getByRole("button", { name: "编辑阵型" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeHidden();

  const saved = api.lastRequest("PATCH", "/api/drafts/draft-1");
  expect(saved).toBeDefined();
  const scenario = saved?.body?.["scenario"] as {
    teams: { phases: { role: string }[][] }[];
  };
  expect(scenario.teams[0].phases[0][8].role).toBe("ST_ROLE_1");
});

test("放弃修改需要二次确认且不提交请求", async ({ page }) => {
  const api = await openTactics(page);

  await page.getByRole("button", { name: "编辑阵型" }).click();
  await page.getByRole("button", { name: /^槽位 02，/ }).click();
  await page.getByRole("combobox", { name: "角色" }).selectOption({ label: "边卫前插" });

  await page.getByRole("button", { name: "放弃", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "放弃修改" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "确认放弃" }).click();

  await expect(page.getByRole("button", { name: "编辑阵型" })).toBeVisible();
  expect(api.requestsFor("PATCH", "/api/drafts/draft-1")).toHaveLength(0);
});

test("键盘可选槽位、交换位置并取消选择", async ({ page }) => {
  const api = await openTactics(page);

  await page.getByRole("button", { name: "编辑阵型" }).click();
  const announcement = page.locator("p.sr-only[aria-live='polite']");

  await page.getByRole("button", { name: /^槽位 01，/ }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("button", { name: /^槽位 11，/ })).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(announcement).toHaveText("已选择槽位 11");

  await page.keyboard.press("Home");
  await expect(page.getByRole("button", { name: SLOT_01 })).toBeFocused();
  const focusedStyle = await page.evaluate(() => {
    const element = document.activeElement;
    if (element === null) return null;
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(focusedStyle?.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(focusedStyle?.outlineWidth ?? "0")).toBeGreaterThanOrEqual(2);

  await page.keyboard.press("Enter");
  await expect(announcement).toHaveText("已与槽位 01 交换");

  await page.keyboard.press("Enter");
  await expect(announcement).toHaveText("已选择槽位 01");
  await page.keyboard.press("Escape");
  await expect(announcement).toHaveText("已取消选择");

  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".tactics-save-notice")).toHaveText("已保存");
  const saved = api.lastRequest("PATCH", "/api/drafts/draft-1");
  const scenario = saved?.body?.["scenario"] as { teams: { lineup: number[] }[] };
  expect(scenario.teams[0].lineup[0]).toBe(10);
  expect(scenario.teams[0].lineup[10]).toBe(0);
});

test("新建战术对话框自动聚焦且 Escape 关闭后焦点回到触发按钮", async ({ page }) => {
  const api = await openTactics(page);

  const trigger = page.getByRole("button", { name: "新建战术" }).first();
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "新建战术" });
  await expect(dialog).toBeVisible();
  const nameInput = dialog.getByRole("textbox", { name: "草案名称" });
  await expect(nameInput).toBeFocused();
  expect(api.requestsFor("GET", "/api/tactics/template")).toHaveLength(1);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.click();
  await expect(dialog).toBeVisible();
  await nameInput.fill("客队反击");
  await dialog.getByRole("button", { name: "创建" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2");
  const created = api.lastRequest("POST", "/api/drafts");
  expect(created?.body?.["name"]).toBe("客队反击");
});

test("保存失败时展示错误并保留编辑状态", async ({ page }) => {
  const api = await openTactics(page);
  api.failNext("PATCH", "/api/drafts/draft-1", 500, "保存失败，请稍后重试");

  await page.getByRole("button", { name: "编辑阵型" }).click();
  await page.getByRole("button", { name: /^槽位 03，/ }).click();
  await page.getByRole("combobox", { name: "角色" }).selectOption({ label: "中卫出球" });

  await page.getByRole("button", { name: "保存", exact: true }).click();

  const alert = page.locator("section.panel").getByRole("alert").first();
  await expect(alert).toContainText("保存失败，请稍后重试");
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeVisible();
  await expect(page.locator(".tactics-dirty-note")).toContainText("有未保存修改");
});