import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { invoke } from "@tauri-apps/api/core";

const { listeners, jobsPage } = vi.hoisted(() => ({
  listeners: {} as Record<string, (event: { payload: unknown }) => void>,
  jobsPage: { shouldThrow: false },
}));

vi.mock("./pages/JobsPage", () => ({
  JobsPage: () => {
    if (jobsPage.shouldThrow) throw new Error("jobs page render failed");
    return "任务页占位";
  },
}));

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke: vi.fn(async () => undefined),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name: string, handler: (event: { payload: unknown }) => void) => {
    listeners[name] = handler;
    return () => {};
  }),
}));

vi.mock("./lib/connection", () => ({
  loadConnection: vi.fn(async () => ({
    url: "http://127.0.0.1:43210",
    token: "test-token",
    api: "fm27lab/v2",
  })),
}));

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    apiJson: vi.fn(async () => ({
      status: "ok",
      api: "fm27lab/v2",
      version: "2.0.0.dev0",
      database: "ready",
    })),
  };
});

import { App } from "./App";
import { loadConnection } from "./lib/connection";

function renderApp(initial = "/tactics") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App shell", () => {
  beforeEach(() => {
    for (const key of Object.keys(listeners)) delete listeners[key];
    vi.mocked(invoke).mockClear();
    vi.mocked(loadConnection).mockResolvedValue({
      url: "http://127.0.0.1:43210",
      token: "test-token",
      api: "fm27lab/v2",
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the sidecar status and navigation", async () => {
    renderApp();
    expect(await screen.findByText("sidecar 正常")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /战术板/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /实验结果/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "帮助" })).toBeInTheDocument();
  });

  it("navigates to the help page from navigation", async () => {
    renderApp();
    await screen.findByText("sidecar 正常");

    fireEvent.click(screen.getByRole("link", { name: "帮助" }));

    expect(await screen.findByRole("heading", { level: 1, name: "帮助" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "三步上手" })).toBeInTheDocument();
  });

  it("does not render the run settings footer", async () => {
    renderApp();
    await screen.findByText("sidecar 正常");

    expect(screen.queryByLabelText("运行设置")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "运行比赛" })).not.toBeInTheDocument();
  });

  it("navigates to the results page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: true,
            status: 200,
            json: async () => ({ items: [], total: 0, next_offset: null }),
          }) as unknown as Response,
      ),
    );
    renderApp();
    await screen.findByText("sidecar 正常");
    fireEvent.click(screen.getByRole("link", { name: /实验结果/ }));
    await waitFor(() => {
      expect(screen.getByText("尚无实验结果")).toBeInTheDocument();
    });
  });

  it("shows a retry action when the connection fails", async () => {
    vi.mocked(loadConnection).mockRejectedValue(new Error("offline"));
    renderApp();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(), { timeout: 4000 });
    expect(screen.getByRole("alert").textContent).toContain("offline");
    const restart = screen.getByRole("button", { name: "重启 sidecar" });
    expect(restart).toBeEnabled();
    fireEvent.click(restart);
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("restart_sidecar"));
  });

  it("clears the connection after a sidecar-down event", async () => {
    renderApp();
    await waitFor(() => expect(listeners["sidecar-down"]).toBeDefined());
    await screen.findByText("sidecar 正常");
    listeners["sidecar-down"]({ payload: "crashed" });
    await waitFor(() => expect(screen.getAllByText("sidecar 未连接").length).toBeGreaterThan(0));
  });

  it("clears the connection after a sidecar-error event", async () => {
    renderApp();
    await waitFor(() => expect(listeners["sidecar-error"]).toBeDefined());
    await screen.findByText("sidecar 正常");
    listeners["sidecar-error"]({ payload: "spawn failed" });
    await waitFor(() => expect(screen.getAllByText("sidecar 未连接").length).toBeGreaterThan(0));
    expect(screen.getByText("spawn failed")).toBeInTheDocument();
  });

  it("does not restart a connected sidecar when checking again", async () => {
    renderApp();
    await screen.findByText("sidecar 正常");
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
    await waitFor(() => expect(invoke).not.toHaveBeenCalled());
  });

  it("applies a sidecar-ready event to the connection cache", async () => {
    renderApp();
    await waitFor(() => expect(listeners["sidecar-ready"]).toBeDefined());
    await screen.findByText("sidecar 正常");
    listeners["sidecar-ready"]({
      payload: { url: "http://127.0.0.1:55555", token: "new-token", api: "fm27lab/v2" },
    });
    fireEvent.click(screen.getByRole("link", { name: /设置/ }));
    await waitFor(() => {
      expect(screen.getByText("http://127.0.0.1:55555")).toBeInTheDocument();
    });
  });
});

describe("App error boundary", () => {
  beforeEach(() => {
    jobsPage.shouldThrow = false;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    jobsPage.shouldThrow = false;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows the fallback when a route page throws and keeps navigation", async () => {
    jobsPage.shouldThrow = true;
    renderApp("/jobs");
    await screen.findByText("sidecar 正常");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("页面渲染失败");
    expect(alert).toHaveTextContent("当前页面遇到错误，可以重试或切换页面");
    expect(screen.getByRole("link", { name: /战术板/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /设置/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "任务管理" })).toBeInTheDocument();
  });

  it("resets the boundary after navigating to another route", async () => {
    jobsPage.shouldThrow = true;
    renderApp("/jobs");
    await screen.findByText("sidecar 正常");
    expect(screen.getByText("页面渲染失败")).toBeInTheDocument();
    jobsPage.shouldThrow = false;
    fireEvent.click(screen.getByRole("link", { name: /设置/ }));
    await waitFor(() => expect(screen.queryByText("页面渲染失败")).not.toBeInTheDocument());
    expect(screen.getByRole("link", { name: /战术板/ })).toBeInTheDocument();
  });

  it("recovers through the retry action when the page renders again", async () => {
    jobsPage.shouldThrow = true;
    renderApp("/jobs");
    await screen.findByText("sidecar 正常");
    const retry = screen.getByRole("button", { name: "重试" });
    jobsPage.shouldThrow = false;
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("任务页占位")).toBeInTheDocument());
    expect(screen.queryByText("页面渲染失败")).not.toBeInTheDocument();
  });
});
