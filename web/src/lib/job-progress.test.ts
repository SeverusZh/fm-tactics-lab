import { describe, expect, it } from "vitest";

import {
  formatDuration,
  isActiveJob,
  jobElapsedMs,
  jobPercent,
  jobProgress,
  jobRemainingMs,
  type JobProgressInput,
} from "./job-progress";

const NOW = Date.parse("2026-11-15T12:00:00Z");

function source(overrides: Partial<JobProgressInput> = {}): JobProgressInput {
  return {
    status: "running",
    total: 10,
    completed: 2,
    started_at: "2026-11-15T11:59:00Z",
    ...overrides,
  };
}

describe("jobPercent", () => {
  it("按已完成场次取整计算百分比", () => {
    expect(jobPercent(0, 10)).toBe(0);
    expect(jobPercent(3, 10)).toBe(30);
    expect(jobPercent(2, 3)).toBe(66);
    expect(jobPercent(199, 200)).toBe(99);
    expect(jobPercent(200, 200)).toBe(100);
  });

  it("非法场次回退到 0 或上限 100", () => {
    expect(jobPercent(5, 0)).toBe(0);
    expect(jobPercent(5, -10)).toBe(0);
    expect(jobPercent(-1, 10)).toBe(0);
    expect(jobPercent(Number.NaN, 10)).toBe(0);
    expect(jobPercent(12, 10)).toBe(100);
  });
});

describe("jobElapsedMs", () => {
  it("从开始时间到当前时间", () => {
    expect(jobElapsedMs(source(), NOW)).toBe(60_000);
  });

  it("缺少或非法开始时间时返回 null", () => {
    expect(jobElapsedMs(source({ started_at: null }), NOW)).toBeNull();
    expect(jobElapsedMs(source({ started_at: "not-a-date" }), NOW)).toBeNull();
  });

  it("开始时间晚于当前时间时归零", () => {
    expect(jobElapsedMs(source({ started_at: "2026-11-15T12:00:30Z" }), NOW)).toBe(0);
  });
});

describe("jobRemainingMs", () => {
  it("按已完成场次与已用时间估算剩余时长", () => {
    expect(jobRemainingMs(source({ completed: 5, total: 10 }), NOW)).toBe(60_000);
  });

  it("已完成场次不足两个时无法估算", () => {
    expect(jobRemainingMs(source({ completed: 1 }), NOW)).toBeNull();
  });

  it("非运行状态不估算", () => {
    expect(jobRemainingMs(source({ status: "queued" }), NOW)).toBeNull();
    expect(jobRemainingMs(source({ status: "completed", completed: 10 }), NOW)).toBeNull();
    expect(jobRemainingMs(source({ status: "cancelled" }), NOW)).toBeNull();
  });

  it("缺少开始时间或已用时间为零时无法估算", () => {
    expect(jobRemainingMs(source({ started_at: null }), NOW)).toBeNull();
    expect(jobRemainingMs(source({ started_at: "2026-11-15T12:00:00Z" }), NOW)).toBeNull();
  });

  it("已经完成或超出总场数时不估算", () => {
    expect(jobRemainingMs(source({ completed: 10, total: 10 }), NOW)).toBeNull();
    expect(jobRemainingMs(source({ completed: 12, total: 10 }), NOW)).toBeNull();
  });
});

describe("formatDuration", () => {
  it("按秒、分、小时格式化", () => {
    expect(formatDuration(0)).toBe("0 秒");
    expect(formatDuration(59_000)).toBe("59 秒");
    expect(formatDuration(60_000)).toBe("1 分");
    expect(formatDuration(90_000)).toBe("1 分 30 秒");
    expect(formatDuration(3_600_000)).toBe("1 小时");
    expect(formatDuration(3_900_000)).toBe("1 小时 5 分");
  });

  it("负数归零，零头四舍五入到秒", () => {
    expect(formatDuration(-500)).toBe("0 秒");
    expect(formatDuration(500)).toBe("1 秒");
  });
});

describe("jobProgress", () => {
  it("聚合运行中任务的进度、已用时间与剩余时间", () => {
    expect(jobProgress(source({ completed: 5, total: 10 }), NOW)).toEqual({
      active: true,
      percent: 50,
      elapsedMs: 60_000,
      remainingMs: 60_000,
    });
  });

  it("完成态任务不估算剩余时间", () => {
    expect(jobProgress(source({ status: "completed", completed: 10, total: 10 }), NOW)).toEqual({
      active: false,
      percent: 100,
      elapsedMs: 60_000,
      remainingMs: null,
    });
  });
});

describe("isActiveJob", () => {
  it("仅排队与运行中视为活跃", () => {
    expect(isActiveJob("queued")).toBe(true);
    expect(isActiveJob("running")).toBe(true);
    expect(isActiveJob("completed")).toBe(false);
    expect(isActiveJob("error")).toBe(false);
    expect(isActiveJob("cancelled")).toBe(false);
    expect(isActiveJob("interrupted")).toBe(false);
  });
});
