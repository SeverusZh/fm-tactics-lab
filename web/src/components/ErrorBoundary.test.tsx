import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

let shouldThrow = true;

function UnstableChild() {
  if (shouldThrow) throw new Error("render failed");
  return <p>内容已恢复</p>;
}

function renderBoundary(children: ReactNode) {
  return render(<ErrorBoundary>{children}</ErrorBoundary>);
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("无错误时渲染子树且不显示回退", () => {
    renderBoundary(<p>正常内容</p>);
    expect(screen.getByText("正常内容")).toBeInTheDocument();
    expect(screen.queryByText("页面渲染失败")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("子组件抛错时用回退区域替换子树", () => {
    renderBoundary(<UnstableChild />);
    expect(screen.getByText("页面渲染失败")).toBeInTheDocument();
    expect(screen.queryByText("内容已恢复")).not.toBeInTheDocument();
  });

  it("回退区域提供告警语义与中文说明", () => {
    renderBoundary(<UnstableChild />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("页面渲染失败");
    expect(alert).toHaveTextContent("当前页面遇到错误，可以重试或切换页面");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("重试后子组件不再抛错时恢复正常渲染", () => {
    renderBoundary(<UnstableChild />);
    expect(screen.getByText("页面渲染失败")).toBeInTheDocument();
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(screen.getByText("内容已恢复")).toBeInTheDocument();
    expect(screen.queryByText("页面渲染失败")).not.toBeInTheDocument();
  });

  it("子组件仍抛错时重试保持回退", () => {
    renderBoundary(<UnstableChild />);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(screen.getByText("页面渲染失败")).toBeInTheDocument();
    expect(screen.queryByText("内容已恢复")).not.toBeInTheDocument();
  });

  it("key 变化后重建边界并清除错误状态", () => {
    const { rerender } = render(
      <ErrorBoundary key="first">
        <UnstableChild />
      </ErrorBoundary>,
    );
    expect(screen.getByText("页面渲染失败")).toBeInTheDocument();
    shouldThrow = false;
    rerender(
      <ErrorBoundary key="second">
        <UnstableChild />
      </ErrorBoundary>,
    );
    expect(screen.getByText("内容已恢复")).toBeInTheDocument();
    expect(screen.queryByText("页面渲染失败")).not.toBeInTheDocument();
  });
});
