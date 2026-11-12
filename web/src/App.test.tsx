import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

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
});
