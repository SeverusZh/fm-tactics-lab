import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listeners } = vi.hoisted(() => ({
  listeners: {} as Record<string, (event: { payload: unknown }) => void>,
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
    vi.mocked(loadConnection).mockResolvedValue({
      url: "http://127.0.0.1:43210",
      token: "test-token",
      api: "fm27lab/v2",
    });
  });

  it("shows the sidecar status and navigation", async () => {
    renderApp();
    expect(await screen.findByText("sidecar 正常")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /战术板/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /实验结果/ })).toBeInTheDocument();
  });

  it("navigates to the results page", async () => {
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
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toBeEnabled();
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
