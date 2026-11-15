import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { QueryKey } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventRefresh } from "./useEventRefresh";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  return { invalidate, wrapper };
}

describe("useEventRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("窗口结束前不失效，到点后按查询键失效一次", () => {
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useEventRefresh([["jobs"]]), { wrapper });

    act(() => {
      result.current();
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  });

  it("窗口内重复触发同一查询键只失效一次", () => {
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useEventRefresh([["jobs"]]), { wrapper });

    act(() => {
      result.current();
      vi.advanceTimersByTime(100);
      result.current();
      vi.advanceTimersByTime(100);
      result.current();
    });

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  });

  it("多个查询键在窗口内合并后各失效一次", () => {
    const keys: QueryKey[] = [
      ["results-jobs"],
      ["job-summary"],
      ["job-runs"],
      ["job-pool-summary"],
    ];
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useEventRefresh(keys), { wrapper });

    act(() => {
      result.current();
      result.current();
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(invalidate).toHaveBeenCalledTimes(4);
    for (const key of keys) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: key });
    }
  });

  it("尾沿窗口随最后一次触发顺延", () => {
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useEventRefresh([["jobs"]]), { wrapper });

    act(() => {
      result.current();
      vi.advanceTimersByTime(250);
      result.current();
    });

    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(40);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("卸载清理定时器且不再失效", () => {
    const { invalidate, wrapper } = setup();
    const { result, unmount } = renderHook(() => useEventRefresh([["jobs"]]), { wrapper });

    act(() => {
      result.current();
    });
    unmount();

    expect(vi.getTimerCount()).toBe(0);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("重渲染传入结构相同的新数组仍合并到一次窗口", () => {
    const { invalidate, wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ keys }: { keys: QueryKey[] }) => useEventRefresh(keys),
      { initialProps: { keys: [["jobs"]] }, wrapper },
    );

    act(() => {
      result.current();
    });
    rerender({ keys: [["jobs"]] });
    act(() => {
      result.current();
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("重渲染后按最新查询键失效", () => {
    const { invalidate, wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ keys }: { keys: QueryKey[] }) => useEventRefresh(keys),
      { initialProps: { keys: [["a"]] }, wrapper },
    );

    rerender({ keys: [["b"]] });
    act(() => {
      result.current();
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["b"] });
  });
});
