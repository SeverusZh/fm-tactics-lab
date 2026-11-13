import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  downloadJobCsv,
  getJobPoolSummary,
  getJobSummary,
  type Health,
  type Job,
  type JobMetrics,
  type JobRun,
  type JobSummary,
  type PoolSummary,
  type PoolSummaryEntry,
} from "../lib/api";
import { ResultsPage } from "./ResultsPage";

const connection = { url: "http://127.0.0.1:43210", token: "test-token", api: "fm27lab/v2" };
const health: Health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

const fetchMock = vi.fn();

type FetchHandler = (url: string, init: RequestInit) => Response | Promise<Response>;

function stubFetch(handler: FetchHandler) {
  fetchMock.mockImplementation(async (...args: unknown[]) => {
    const [input, init] = args as [RequestInfo | URL, RequestInit | undefined];
    return handler(String(input), init ?? {});
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function textResponse(body: string): Response {
  return {
    ok: true,
    status: 200,
    text: async () => body,
  } as unknown as Response;
}

function fetchCalls(): { url: string; init: RequestInit }[] {
  return fetchMock.mock.calls.map((call) => {
    const [input, init] = call as unknown as [RequestInfo | URL, RequestInit | undefined];
    return { url: String(input), init: init ?? {} };
  });
}

function callsTo(fragment: string) {
  return fetchCalls().filter((call) => call.url.includes(fragment));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    kind: "experiment",
    status: "completed",
    name: "批次一",
    config: {},
    summary: {},
    workers: 2,
    total: 4,
    completed: 4,
    created_at: "2026-11-13T10:00:00+00:00",
    started_at: "2026-11-13T10:00:01+00:00",
    finished_at: "2026-11-13T10:02:00+00:00",
    ...overrides,
  };
}

function makeMetrics(overrides: Partial<JobMetrics> = {}): JobMetrics {
  return {
    n: 4,
    wins: 2,
    draws: 1,
    losses: 1,
    win_rate: 0.5,
    win_interval: [0.15, 0.85],
    goals_for: 1.5,
    goals_against: 0.75,
    points: 1.75,
    xg: 1.42,
    xga: 0.85,
    possession: 58.2,
    shots: 12.5,
    pass_completion: 0.81,
    ...overrides,
  };
}

function makeSummary(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job: makeJob(),
    metrics: makeMetrics(),
    paired: { n: 2, goal_difference_delta: 0.25 },
    ...overrides,
  };
}

function makeRun(overrides: Partial<JobRun> = {}): JobRun {
  return {
    job_id: "job-1",
    sequence: 1,
    variant: "A",
    seed: 42,
    score: [2, 1],
    verified: true,
    stats: {},
    events: null,
    log_path: null,
    created_at: "2026-11-13T10:01:00+00:00",
    ...overrides,
  };
}

function makePoolEntry(overrides: Partial<PoolSummaryEntry> = {}): PoolSummaryEntry {
  return {
    index: 0,
    name: "客队战术 1",
    weight: 1,
    probability: 1 / 3,
    roster: false,
    ...overrides,
  };
}

function makePoolSummary(overrides: Partial<PoolSummary> = {}): PoolSummary {
  return {
    enabled: true,
    entry_count: 2,
    mode: "random",
    rounds: 1,
    players: "uniform",
    uniform: { enabled: true, attribute_value: 15 },
    entries: [
      makePoolEntry(),
      makePoolEntry({ index: 1, name: "客队战术 2", weight: 2, probability: 2 / 3, roster: true }),
    ],
    draws: { "0": 2, "1": 3 },
    ...overrides,
  };
}

const emptyPool: PoolSummary = {
  enabled: false,
  entry_count: 0,
  mode: null,
  players: null,
  draws: {},
};

type ResultsFixtures = {
  jobs?: { items: Job[]; total: number; next_offset: number | null };
  summary?: JobSummary | ((url: string) => JobSummary);
  runs?: (url: string) => { items: JobRun[]; total: number; next_offset: number | null };
  pool?: PoolSummary | ((url: string) => PoolSummary);
  csv?: () => Response;
};

function resultsFetch(fixtures: ResultsFixtures = {}): FetchHandler {
  return (url) => {
    if (url.includes("/export.csv")) {
      return fixtures.csv?.() ?? textResponse("job_id,sequence\r\njob-1,1\r\n");
    }
    if (url.includes("/pool-summary")) {
      const pool = typeof fixtures.pool === "function" ? fixtures.pool(url) : fixtures.pool;
      return jsonResponse(pool ?? emptyPool);
    }
    if (url.includes("/summary")) {
      const summary =
        typeof fixtures.summary === "function" ? fixtures.summary(url) : fixtures.summary;
      return jsonResponse(summary ?? makeSummary());
    }
    if (url.includes("/runs")) {
      return jsonResponse(
        fixtures.runs?.(url) ?? { items: [makeRun()], total: 1, next_offset: null },
      );
    }
    return jsonResponse(
      fixtures.jobs ?? { items: [makeJob()], total: 1, next_offset: null },
    );
  };
}

function renderResultsPage(activeConnection: typeof connection | null = connection) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider
        value={{
          connection: activeConnection,
          health,
          connectionError: null,
          refreshing: false,
          refresh: vi.fn(),
        }}
      >
        <ResultsPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function metricValue(label: string): string {
  const card = screen.getByText(label).closest(".metric");
  if (card === null) throw new Error("未找到指标卡片：" + label);
  return card.querySelector(".metric-value")?.textContent ?? "";
}

function poolCard(): HTMLElement {
  const card = screen.getByText("客队战术池").closest(".pool-card");
  if (!(card instanceof HTMLElement)) throw new Error("未找到客队战术池卡片");
  return card;
}

function poolRowTexts(): string[][] {
  return within(poolCard())
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent ?? ""),
    );
}

function captureDownload() {
  const objectUrls: string[] = [];
  const blobs: Blob[] = [];
  const clicked: HTMLAnchorElement[] = [];
  const createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    const url = "blob:test-" + objectUrls.length;
    objectUrls.push(url);
    return url;
  });
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  return { blobs, objectUrls, clicked, createObjectURL, revokeObjectURL, clickSpy };
}

describe("ResultsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (URL as unknown as Record<string, unknown>).createObjectURL;
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
  });

  it("加载中显示状态，成功后渲染带鉴权的任务摘要", async () => {
    const pending = deferred<Response>();
    const base = resultsFetch();
    stubFetch((url, init) => (url.includes("/api/jobs?") ? pending.promise : base(url, init)));

    renderResultsPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载实验任务");

    pending.resolve(jsonResponse({ items: [makeJob()], total: 1, next_offset: null }));

    expect(await screen.findByLabelText("实验任务")).toBeInTheDocument();
    expect(await screen.findByText("场次")).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("实验任务")).getByRole("option", { name: "批次一" }),
    ).toBeInTheDocument();

    const [listCall] = callsTo("/api/jobs?");
    expect(listCall.url).toBe("http://127.0.0.1:43210/api/jobs?limit=50&offset=0");
    expect(new Headers(listCall.init.headers).get("Authorization")).toBe("Bearer test-token");

    const [summaryCall] = callsTo("/summary");
    expect(summaryCall.url).toBe("http://127.0.0.1:43210/api/jobs/job-1/summary?side=0");
    expect(new Headers(summaryCall.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("指标按主队视角渲染数值与配对差值", async () => {
    stubFetch(resultsFetch());
    renderResultsPage();

    await screen.findByText("场次");
    expect(metricValue("场次")).toBe("4");
    expect(metricValue("胜 / 平 / 负")).toBe("2 / 1 / 1");
    expect(metricValue("胜率")).toBe("50.0%");
    expect(screen.getByText("95% 区间 15.0%–85.0%")).toBeInTheDocument();
    expect(metricValue("场均进球")).toBe("1.50");
    expect(metricValue("场均失球")).toBe("0.75");
    expect(metricValue("场均积分")).toBe("1.75");
    expect(metricValue("xG")).toBe("1.42");
    expect(metricValue("xGA")).toBe("0.85");
    expect(metricValue("控球率")).toBe("58.2%");
    expect(metricValue("场均射门")).toBe("12.5");
    expect(metricValue("传球成功率")).toBe("81.0%");
    expect(metricValue("配对场次")).toBe("2");
    expect(metricValue("净胜球差")).toBe("+0.25");
  });

  it("缺失指标显示占位符", async () => {
    stubFetch(
      resultsFetch({
        summary: makeSummary({
          metrics: makeMetrics({
            xg: null,
            xga: null,
            possession: null,
            shots: null,
            pass_completion: null,
          }),
          paired: { n: 0, goal_difference_delta: null },
        }),
      }),
    );
    renderResultsPage();

    await screen.findByText("场次");
    expect(metricValue("xG")).toBe("—");
    expect(metricValue("xGA")).toBe("—");
    expect(metricValue("控球率")).toBe("—");
    expect(metricValue("场均射门")).toBe("—");
    expect(metricValue("传球成功率")).toBe("—");
    expect(metricValue("净胜球差")).toBe("—");
  });

  it("切换客队视角按 side 重新请求摘要", async () => {
    stubFetch(
      resultsFetch({
        summary: (url) =>
          url.includes("side=1")
            ? makeSummary({
                metrics: makeMetrics({ wins: 1, draws: 1, losses: 2, win_rate: 0.25 }),
                paired: { n: 2, goal_difference_delta: -0.25 },
              })
            : makeSummary(),
      }),
    );
    renderResultsPage();

    await screen.findByText("场次");
    expect(metricValue("胜率")).toBe("50.0%");

    fireEvent.click(screen.getByRole("button", { name: "客队" }));

    await waitFor(() => expect(callsTo("/summary")).toHaveLength(2));
    expect(callsTo("/summary")[1].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job-1/summary?side=1",
    );
    await waitFor(() => expect(metricValue("胜率")).toBe("25.0%"));
    expect(metricValue("净胜球差")).toBe("-0.25");
    expect(screen.getByRole("button", { name: "客队" })).toHaveAttribute("aria-pressed", "true");
  });

  it("切换任务后按新任务请求摘要与逐场记录", async () => {
    stubFetch(
      resultsFetch({
        jobs: {
          items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
          total: 2,
          next_offset: null,
        },
        summary: (url) =>
          makeSummary({ job: makeJob({ id: url.includes("job-2") ? "job-2" : "job-1" }) }),
        runs: (url) => ({
          items: [makeRun({ job_id: url.includes("job-2") ? "job-2" : "job-1" })],
          total: 1,
          next_offset: null,
        }),
      }),
    );
    renderResultsPage();

    await screen.findByLabelText("实验任务");
    fireEvent.change(screen.getByLabelText("实验任务"), { target: { value: "job-2" } });

    await waitFor(() => expect(callsTo("/job-2/summary")).toHaveLength(1));
    expect(callsTo("/job-2/summary")[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job-2/summary?side=0",
    );
    await waitFor(() => expect(callsTo("/job-2/runs")).toHaveLength(1));
    expect(callsTo("/job-2/runs")[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job-2/runs?limit=20&offset=0",
    );
  });

  it("逐场记录表格渲染比分与校验状态并支持分页", async () => {
    const pages: Record<string, { items: JobRun[]; total: number; next_offset: number | null }> = {
      "offset=20": {
        items: [makeRun({ sequence: 21, variant: "B", seed: 99, score: [1, 0] })],
        total: 21,
        next_offset: null,
      },
      default: {
        items: [
          makeRun({ sequence: 1, score: [2, 1] }),
          makeRun({ sequence: 2, variant: "B", seed: 43, score: null, verified: false }),
        ],
        total: 21,
        next_offset: 20,
      },
    };
    stubFetch(
      resultsFetch({
        runs: (url) => pages[url.includes("offset=20") ? "offset=20" : "default"],
      }),
    );
    renderResultsPage();

    expect(await screen.findByText("逐场记录")).toBeInTheDocument();
    expect(await screen.findByText("2–1")).toBeInTheDocument();
    expect(screen.getByText("未验证")).toBeInTheDocument();
    expect(screen.getByText("共 21 场")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() => expect(callsTo("/runs?limit=20&offset=20")).toHaveLength(1));
    expect(await screen.findByText("1–0")).toBeInTheDocument();
  });

  it("任务没有已完成比赛时显示空态且不请求逐场记录", async () => {
    stubFetch(
      resultsFetch({
        summary: makeSummary({ metrics: null, paired: { n: 0, goal_difference_delta: null } }),
      }),
    );
    renderResultsPage();

    expect(await screen.findByText("尚无比赛结果")).toBeInTheDocument();
    expect(screen.queryByText("场次")).not.toBeInTheDocument();
    expect(callsTo("/runs")).toHaveLength(0);
  });

  it("无任务时显示空态引导", async () => {
    stubFetch(resultsFetch({ jobs: { items: [], total: 0, next_offset: null } }));
    renderResultsPage();

    expect(await screen.findByText("尚无实验结果")).toBeInTheDocument();
    expect(
      screen.getByText("提交实验后，这里会显示批次摘要、A/B 指标、配对差值与逐场记录。"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("实验任务")).not.toBeInTheDocument();
    expect(callsTo("/summary")).toHaveLength(0);
  });

  it("任务列表加载失败时展示后端错误并可重试", async () => {
    let attempts = 0;
    const base = resultsFetch({ jobs: { items: [], total: 0, next_offset: null } });
    stubFetch((url, init) => {
      if (!url.includes("/api/jobs?")) return base(url, init);
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse(
          { error: { code: "validation_failed", message: "任务列表查询失败" } },
          400,
        );
      }
      return jsonResponse({ items: [makeJob()], total: 1, next_offset: null });
    });
    renderResultsPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("任务列表查询失败");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByLabelText("实验任务")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("摘要加载失败时展示错误并可重试", async () => {
    let attempts = 0;
    const base = resultsFetch();
    stubFetch((url, init) => {
      if (!url.includes("/summary")) return base(url, init);
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "not_found", message: "任务不存在" } }, 404);
      }
      return jsonResponse(makeSummary());
    });
    renderResultsPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("任务不存在");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(attempts).toBe(2));
    expect(await screen.findByText("场次")).toBeInTheDocument();
  });

  it("CSV 下载带 Bearer 请求并触发浏览器下载", async () => {
    const download = captureDownload();
    stubFetch(resultsFetch());
    renderResultsPage();

    await screen.findByText("场次");
    fireEvent.click(screen.getByRole("button", { name: "下载 CSV" }));

    await waitFor(() => expect(callsTo("/export.csv")).toHaveLength(1));
    expect(callsTo("/export.csv")[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job-1/export.csv",
    );
    expect(new Headers(callsTo("/export.csv")[0].init.headers).get("Authorization")).toBe(
      "Bearer test-token",
    );
    await waitFor(() => expect(download.clicked).toHaveLength(1));
    expect(download.clicked[0].download).toBe("job-job-1.csv");
    expect(download.objectUrls).toHaveLength(1);
    expect(download.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("CSV 下载失败时展示后端错误", async () => {
    stubFetch(
      resultsFetch({
        csv: () =>
          jsonResponse({ error: { code: "not_found", message: "任务不存在" } }, 404),
      }),
    );
    renderResultsPage();

    await screen.findByText("场次");
    fireEvent.click(screen.getByRole("button", { name: "下载 CSV" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("任务不存在");
  });

  it("客队战术池默认折叠并支持展开与再次折叠", async () => {
    stubFetch(resultsFetch({ pool: makePoolSummary() }));
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("客队战术 1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开" }));

    expect(screen.getByRole("button", { name: "折叠" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();
    expect(screen.getByText("客队战术 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "折叠" }));

    expect(screen.queryByText("客队战术 1")).not.toBeInTheDocument();
  });

  it("客队战术池展示条目数、模式、名单来源与逐条数据", async () => {
    stubFetch(resultsFetch({ pool: makePoolSummary({ draws: { "0": 2 } }) }));
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    const card = poolCard();
    expect(within(card).getByText("共 2 套")).toBeInTheDocument();
    expect(within(card).getByText("随机抽取")).toBeInTheDocument();
    expect(within(card).getByText("名单：统一属性")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "展开" }));

    expect(poolRowTexts()).toEqual([
      ["客队战术 1", "1", "33.3%", "统一属性", "2"],
      ["客队战术 2", "2", "66.7%", "真实名单", "0"],
    ]);
  });

  it("轮战模式展示概率占位与真实名单标签", async () => {
    stubFetch(
      resultsFetch({
        pool: makePoolSummary({
          mode: "rotation",
          rounds: 2,
          players: "real",
          entries: [
            makePoolEntry({ probability: null }),
            makePoolEntry({ index: 1, name: "客队战术 2", weight: 2, probability: null, roster: true }),
          ],
          draws: { "0": 2, "1": 2 },
        }),
      }),
    );
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    const card = poolCard();
    expect(within(card).getByText("轮战")).toBeInTheDocument();
    expect(within(card).getByText("名单：真实名单")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "展开" }));

    expect(poolRowTexts()).toEqual([
      ["客队战术 1", "1", "—", "统一属性", "2"],
      ["客队战术 2", "2", "—", "真实名单", "2"],
    ]);
  });

  it("客队战术池禁用时提示未启用并保留条目数", async () => {
    stubFetch(
      resultsFetch({
        pool: { enabled: false, entry_count: 2, mode: null, players: null, draws: {} },
      }),
    );
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    const card = poolCard();
    expect(within(card).getByText("未启用客队战术池")).toBeInTheDocument();
    expect(within(card).getByText("共 2 套")).toBeInTheDocument();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    expect(within(card).queryByRole("table")).not.toBeInTheDocument();
  });

  it("无客队战术池配置时不渲染卡片", async () => {
    stubFetch(resultsFetch());
    renderResultsPage();

    await screen.findByText("场次");
    await waitFor(() => expect(callsTo("/pool-summary")).toHaveLength(1));
    expect(screen.queryByText("客队战术池")).not.toBeInTheDocument();
    expect(screen.queryByText("未启用客队战术池")).not.toBeInTheDocument();
  });

  it("切换任务后各任务的折叠状态在会话内保留", async () => {
    stubFetch(
      resultsFetch({
        jobs: {
          items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
          total: 2,
          next_offset: null,
        },
        pool: (url) =>
          url.includes("job-2")
            ? makePoolSummary({
                entry_count: 1,
                entries: [makePoolEntry({ name: "客队战术 B" })],
                draws: { "0": 0 },
              })
            : makePoolSummary(),
      }),
    );
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("实验任务"), { target: { value: "job-2" } });

    expect(await screen.findByRole("button", { name: "展开" })).toBeInTheDocument();
    expect(screen.queryByText("客队战术 B")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(await screen.findByText("客队战术 B")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("实验任务"), { target: { value: "job-1" } });

    expect(await screen.findByRole("button", { name: "折叠" })).toBeInTheDocument();
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();
    expect(screen.queryByText("客队战术 B")).not.toBeInTheDocument();
  });

  it("切换任务后池摘要返回前不展示上一任务的条目", async () => {
    const pending = deferred<Response>();
    const base = resultsFetch({
      jobs: {
        items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
        total: 2,
        next_offset: null,
      },
      pool: () => makePoolSummary(),
    });
    stubFetch((url, init) =>
      url.includes("/job-2/pool-summary") ? pending.promise : base(url, init),
    );
    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("实验任务"), { target: { value: "job-2" } });

    expect(await screen.findByText("正在加载客队战术池…")).toBeInTheDocument();
    expect(screen.queryByText("客队战术 1")).not.toBeInTheDocument();

    pending.resolve(
      jsonResponse(
        makePoolSummary({
          entry_count: 1,
          entries: [makePoolEntry({ name: "客队战术 B" })],
          draws: { "0": 1 },
        }),
      ),
    );

    fireEvent.click(await screen.findByRole("button", { name: "展开" }));
    expect(await screen.findByText("客队战术 B")).toBeInTheDocument();
    expect(screen.queryByText("客队战术 1")).not.toBeInTheDocument();
  });

  it("池摘要请求失败时展示内联错误并可重试", async () => {
    let attempts = 0;
    const base = resultsFetch();
    stubFetch((url, init) => {
      if (!url.includes("/pool-summary")) return base(url, init);
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "not_found", message: "战术池读取失败" } }, 404);
      }
      return jsonResponse(makePoolSummary());
    });
    renderResultsPage();

    expect(await screen.findByText("场次")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("战术池读取失败");
    expect(metricValue("场次")).toBe("4");
    expect(await screen.findByText("2–1")).toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    await waitFor(() => expect(attempts).toBe(2));
    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();
  });

  it("sidecar 未连接时显示空态", async () => {
    stubFetch(resultsFetch());
    renderResultsPage(null);

    expect(await screen.findByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });
});

describe("结果读取 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getJobSummary 按 side 读取摘要并编码任务 id", async () => {
    stubFetch(resultsFetch());

    const summary = await getJobSummary(connection, "job/1", 1);

    expect(summary.metrics?.n).toBe(4);
    expect(fetchCalls()[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job%2F1/summary?side=1",
    );
    expect(new Headers(fetchCalls()[0].init.headers).get("Authorization")).toBe(
      "Bearer test-token",
    );
  });

  it("getJobPoolSummary 读取客队战术池摘要并编码任务 id", async () => {
    stubFetch(resultsFetch({ pool: makePoolSummary() }));

    const summary = await getJobPoolSummary(connection, "job/1");

    expect(summary.entry_count).toBe(2);
    expect(summary.mode).toBe("random");
    expect(summary.entries?.[0].name).toBe("客队战术 1");
    expect(summary.draws).toEqual({ "0": 2, "1": 3 });
    expect(fetchCalls()[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job%2F1/pool-summary",
    );
    expect(new Headers(fetchCalls()[0].init.headers).get("Authorization")).toBe(
      "Bearer test-token",
    );
  });

  it("downloadJobCsv 返回 CSV 文本", async () => {
    stubFetch(() => textResponse("job_id,sequence\r\njob-1,1\r\n"));

    const text = await downloadJobCsv(connection, "job-1");

    expect(text).toBe("job_id,sequence\r\njob-1,1\r\n");
    expect(fetchCalls()[0].url).toBe("http://127.0.0.1:43210/api/jobs/job-1/export.csv");
  });
});

describe("实验结果路由", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("通过 /results 渲染结果页并出现在主导航", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/health")) return jsonResponse(health);
      return jsonResponse({ items: [], total: 0, next_offset: null });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/results"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "实验结果" })).toBeInTheDocument();
    expect(await screen.findByText("尚无实验结果")).toBeInTheDocument();
  });
});
