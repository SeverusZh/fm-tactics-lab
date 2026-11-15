import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HelpPage } from "./HelpPage";

const desktopMocks = vi.hoisted(() => ({
  openExternalUrlMock: vi.fn(async (url: string) => url.length > 0),
}));

vi.mock("../lib/desktop", () => ({ openExternalUrl: desktopMocks.openExternalUrlMock }));

const PAGE_NAMES = [
  "战术板",
  "球员属性",
  "存档战术库",
  "实验",
  "实验结果",
  "任务管理",
  "定位球",
  "设置",
  "帮助",
];

const WITHOUT_ENGINE = [
  "导入 .fm 存档：查看俱乐部、球员名单与球队阵容。",
  "阵容同步：把存档阵容写入草案球队。",
  "战术板草案：编辑阵型、指令与球员属性并保存。",
  "任务与实验结果：查看状态、汇总与逐场记录。",
];

const WITH_ENGINE = [
  "导入真实 FMF 战术文件：由游戏自身的序列化器解析归档内容。",
  "运行模拟比赛与批量实验：需要可用的 FM27 宿主与游戏目录。",
  "引擎诊断：校验宿主与游戏版本是否匹配。",
];

function renderHelp() {
  return render(
    <MemoryRouter>
      <HelpPage />
    </MemoryRouter>,
  );
}

describe("HelpPage", () => {
  beforeEach(() => {
    desktopMocks.openExternalUrlMock.mockReset();
    desktopMocks.openExternalUrlMock.mockImplementation(async (url: string) => url.length > 0);
  });

  it("提供三步上手与各页面用途", () => {
    renderHelp();

    expect(screen.getByRole("heading", { name: "帮助" })).toBeInTheDocument();
    const steps = screen.getByRole("region", { name: "三步上手" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(3);

    const pages = screen.getByRole("region", { name: "页面用途" });
    expect(within(pages).getAllByRole("term").map((term) => term.textContent)).toEqual(
      PAGE_NAMES,
    );
    expect(within(pages).getAllByRole("definition")).toHaveLength(PAGE_NAMES.length);
  });

  it("把每条能力归入正确的引擎需求分组", () => {
    renderHelp();

    const capabilities = screen.getByRole("region", { name: "能力边界" });
    expect(
      within(capabilities).getByRole("heading", { name: "无需游戏与引擎" }),
    ).toBeInTheDocument();
    const withoutEngine = within(capabilities).getByTestId("help-without-engine");
    expect(
      within(withoutEngine).getAllByRole("listitem").map((item) => item.textContent),
    ).toEqual(WITHOUT_ENGINE);

    expect(
      within(capabilities).getByRole("heading", { name: "需要配置游戏与引擎" }),
    ).toBeInTheDocument();
    const withEngine = within(capabilities).getByTestId("help-with-engine");
    expect(
      within(withEngine).getAllByRole("listitem").map((item) => item.textContent),
    ).toEqual(WITH_ENGINE);
  });

  it("不宣称未实现的联赛战术库与真实 AI 计划", () => {
    renderHelp();

    const capabilities = screen.getByRole("region", { name: "能力边界" });
    expect(capabilities.textContent).not.toMatch(/联赛战术库/);
    expect(capabilities.textContent).not.toMatch(/真实 AI 计划/);
    expect(capabilities.textContent).not.toMatch(/AI 计划/);
  });

  it("说明存档与阵容同步不需要引擎", () => {
    renderHelp();

    const withoutEngine = screen.getByTestId("help-without-engine");
    expect(withoutEngine.textContent).toMatch(/存档/);
    expect(withoutEngine.textContent).toMatch(/阵容同步/);

    const withEngine = screen.getByTestId("help-with-engine");
    expect(withEngine.textContent).not.toMatch(/存档导入/);
    expect(withEngine.textContent).not.toMatch(/阵容同步/);
  });

  it("常见问题覆盖导入失败与引擎未配置", () => {
    renderHelp();

    const faq = screen.getByRole("region", { name: "常见问题" });
    for (const question of ["FMF 导入失败", "存档导入失败", "引擎未配置"]) {
      expect(within(faq).getByText(question)).toBeInTheDocument();
    }
    expect(within(faq).getByText(/引擎目录未配置/)).toBeInTheDocument();
  });

  it("外部链接交给系统浏览器打开", async () => {
    renderHelp();

    const section = screen.getByRole("region", { name: "外部链接" });
    const repo = within(section).getByRole("link", { name: "项目仓库" });
    expect(repo).toHaveAttribute("href", "https://github.com/SeverusZh/fm-tactics-lab");
    expect(within(section).getByRole("link", { name: "问题反馈" })).toHaveAttribute(
      "href",
      "https://github.com/SeverusZh/fm-tactics-lab/issues",
    );

    fireEvent.click(repo);

    await waitFor(() =>
      expect(desktopMocks.openExternalUrlMock).toHaveBeenCalledWith(
        "https://github.com/SeverusZh/fm-tactics-lab",
      ),
    );
    expect(within(section).queryByRole("alert")).toBeNull();
  });

  it("外部链接打开失败时提示手动复制", async () => {
    desktopMocks.openExternalUrlMock.mockResolvedValue(false);
    renderHelp();

    fireEvent.click(screen.getByRole("link", { name: "问题反馈" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("手动复制地址");
  });

  it("提供页面跳转按钮", () => {
    renderHelp();

    const nav = screen.getByRole("navigation", { name: "页面跳转" });
    expect(within(nav).getByRole("link", { name: "前往战术板" })).toHaveAttribute(
      "href",
      "/tactics",
    );
    expect(within(nav).getByRole("link", { name: "前往存档战术库" })).toHaveAttribute(
      "href",
      "/library",
    );
    expect(within(nav).getByRole("link", { name: "前往实验" })).toHaveAttribute(
      "href",
      "/experiments",
    );
    expect(within(nav).getByRole("link", { name: "前往设置" })).toHaveAttribute(
      "href",
      "/settings",
    );
  });
});
