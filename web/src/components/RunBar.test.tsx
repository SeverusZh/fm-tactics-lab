import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppContext } from "../app-context";
import { RunBar } from "./RunBar";

const health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

function renderRunBar() {
  return render(
    <AppContext.Provider
      value={{
        connection: null,
        health,
        connectionError: null,
        refreshing: false,
        refresh: vi.fn(),
      }}
    >
      <RunBar />
    </AppContext.Provider>,
  );
}

describe("RunBar", () => {
  it("rejects an empty seed and an out-of-range worker count", () => {
    renderRunBar();
    const seed = screen.getByLabelText("起始种子");
    fireEvent.change(seed, { target: { value: "" } });
    expect(seed).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(seed, { target: { value: "42" } });

    const workers = screen.getByLabelText("并行数");
    fireEvent.change(workers, { target: { value: "257" } });
    expect(workers).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("并行数需为 1–256 的整数")).toBeInTheDocument();
  });

  it("reflects the oversubscription choice", () => {
    renderRunBar();
    fireEvent.click(screen.getByLabelText("允许资源覆盖"));
    expect(screen.getByText("资源覆盖已允许")).toBeInTheDocument();
  });
});
