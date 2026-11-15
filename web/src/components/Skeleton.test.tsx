import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Skeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("以状态区域展示中文加载提示", () => {
    render(<Skeleton label="正在加载存档…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("正在加载存档…");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("骨架图形对辅助技术隐藏", () => {
    const { container } = render(<Skeleton label="正在加载存档…" />);
    const bars = container.querySelector(".skeleton-lines");
    expect(bars).toHaveAttribute("aria-hidden", "true");
    expect(bars?.children).toHaveLength(3);
  });

  it("行数由 count 控制且至少渲染一行", () => {
    const { container, rerender } = render(<Skeleton label="加载中" count={5} />);
    expect(container.querySelectorAll(".skeleton-line")).toHaveLength(5);
    rerender(<Skeleton label="加载中" count={0} />);
    expect(container.querySelectorAll(".skeleton-line")).toHaveLength(1);
  });

  it("表格行变体按行渲染三列骨架块", () => {
    const { container } = render(<Skeleton label="正在加载设置…" variant="rows" count={2} />);
    expect(container.querySelectorAll(".skeleton-row")).toHaveLength(2);
    expect(container.querySelectorAll(".skeleton-block")).toHaveLength(6);
  });

  it("支持追加自定义类名", () => {
    render(<Skeleton label="加载中" className="custom" />);
    expect(screen.getByRole("status")).toHaveClass("skeleton", "custom");
  });
});
