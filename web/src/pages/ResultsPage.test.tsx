import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  compareResults,
  downloadJobCsv,
  getJobPoolSummary,
  getJobSummary,
  type CompareCandidate,
  type CompareJob,
  type ComparePaired,
  type ComparePairing,
  type CompareResult,
  type Health,
  type Job,
  type JobMetrics,
  type JobRun,
  type JobSummary,
  type PoolSummary,
  type PoolSummaryEntry,
} from "../lib/api";
import { ResultsPage } from "./ResultsPage";
import { REFRESH_WINDOW_MS } from "../lib/useEventRefresh";

const connection = { url: "http://127.0.0.1:43210", token: "test-token", api: "fm27lab/v2" };
const health: Health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

const fetchMock = vi.fn();

type FetchHandler = (url: string, init: RequestInit) => Response | Promise<Response>;

type EventStreamHandler = () => Response | Promise<Response>;

function openEventStream(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(": connected\n\n"));
    },
  });
  return new Response(stream);
}

type EventStreamControl = {
  response: Response;
  send(text: string): void;
  close(): void;
};

function controllableEventStream(): EventStreamControl {
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(inner) {
      controller = inner;
    },
  });
  return {
    response: new Response(stream),
    send(text) {
      controller?.enqueue(new TextEncoder().encode(text));
    },
    close() {
      controller?.close();
    },
  };
}

function stubFetch(handler: FetchHandler, eventsHandler: EventStreamHandler = openEventStream) {
  fetchMock.mockImplementation(async (...args: unknown[]) => {
    const [input, init] = args as [RequestInfo | URL, RequestInit | undefined];
    const url = String(input);
    if (url.endsWith("/api/events")) return eventsHandler();
    return handler(url, init ?? {});
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

function allCalls(): { url: string; init: RequestInit }[] {
  return fetchMock.mock.calls.map((call) => {
    const [input, init] = call as unknown as [RequestInfo | URL, RequestInit | undefined];
    return { url: String(input), init: init ?? {} };
  });
}

function fetchCalls() {
  return allCalls().filter((call) => !call.url.endsWith("/api/events"));
}

function eventsCalls() {
  return allCalls().filter((call) => call.url.endsWith("/api/events"));
}

function callsTo(fragment: string) {
  return fetchCalls().filter((call) => call.url.includes(fragment));
}

function runsOffsets(fragment: string): (string | null)[] {
  return callsTo(fragment).map((call) => new URL(call.url).searchParams.get("offset"));
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

function makeComparePairing(overrides: Partial<ComparePairing> = {}): ComparePairing {
  return {
    common_seeds: 6,
    draw_mismatches: 0,
    mismatched_seeds: [],
    missing_seeds: [],
    ...overrides,
  };
}

function makeComparePaired(overrides: Partial<ComparePaired> = {}): ComparePaired {
  return {
    seeds: 6,
    win_rate_delta: 0.125,
    win_rate_delta_ci: [0.02, 0.23],
    points_delta: 0.5,
    points_delta_ci: [-0.2, 1.2],
    goal_difference_delta: 0.4,
    goal_difference_delta_ci: [-0.1, 0.9],
    xgd_delta: 0.15,
    xgd_delta_ci: [-0.05, 0.35],
    ...overrides,
  };
}

function makeCompareJob(overrides: Partial<CompareJob> = {}): CompareJob {
  return {
    job_id: "job-2",
    name: "批次二",
    metrics: makeMetrics(),
    tactic_pool: emptyPool,
    ...overrides,
  };
}

function makeCompareCandidate(overrides: Partial<CompareCandidate> = {}): CompareCandidate {
  return {
    ...makeCompareJob(),
    comparable: true,
    reason: null,
    pairing: makeComparePairing(),
    paired: makeComparePaired(),
    ...overrides,
  };
}

function makeCompareResult(overrides: Partial<CompareResult> = {}): CompareResult {
  return {
    baseline: makeCompareJob({ job_id: "job-1", name: "批次一" }),
    variant: "B",
    side: 0,
    candidates: [makeCompareCandidate()],
    ...overrides,
  };
}

type ResultsFixtures = {
  jobs?: { items: Job[]; total: number; next_offset: number | null };
  compare?: CompareResult | (() => CompareResult);
  summary?: JobSummary | ((url: string) => JobSummary);
  runs?: (url: string) => { items: JobRun[]; total: number; next_offset: number | null };
  pool?: PoolSummary | ((url: string) => PoolSummary);
  csv?: () => Response;
};

function resultsFetch(fixtures: ResultsFixtures = {}): FetchHandler {
  return (url) => {
    if (url.includes("/api/results/compare")) {
      const compare =
        typeof fixtures.compare === "function" ? fixtures.compare() : fixtures.compare;
      return jsonResponse(compare ?? makeCompareResult());
    }
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
  const view = render(
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
  return { client, ...view };
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


function comparePanel(): HTMLElement {
  const title = screen.getByText("任务对比");
  const panel = title.closest(".compare-panel");
  if (!(panel instanceof HTMLElement)) throw new Error("未找到任务对比面板");
  return panel;
}

function compareTable(): HTMLElement {
  return screen.getByRole("table", { name: "任务对比结果" });
}

function candidateCheckbox(label: string, jobId: string): HTMLElement {
  return screen.getByRole("checkbox", { name: "候选任务 " + label + "（" + jobId + "）" });
}

function compareRowTexts(): string[][] {
  return within(compareTable())
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

function jobRegion(): HTMLElement {
  return screen.getByRole("region", { name: "实验任务" });
}

function jobButton(name: string): HTMLElement {
  return within(jobRegion()).getByRole("button", { name });
}

function jobCheckbox(name: string, jobId: string): HTMLElement {
  return within(jobRegion()).getByRole("checkbox", { name: `选择任务 ${name}（${jobId}）` });
}

function jobActions(): HTMLElement {
  const actions = jobRegion().querySelector(".results-jobs-actions");
  if (!(actions instanceof HTMLElement)) throw new Error("未找到任务批量操作区");
  return actions;
}

describe("ResultsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.clear();
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

    expect(await screen.findByRole("region", { name: "实验任务" })).toBeInTheDocument();
    expect(await screen.findByText("场次")).toBeInTheDocument();
    expect(jobButton("批次一")).toHaveAttribute("aria-current", "true");

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

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobButton("批次二"));

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
    expect(screen.queryByRole("region", { name: "实验任务" })).not.toBeInTheDocument();
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

    expect(await screen.findByRole("region", { name: "实验任务" })).toBeInTheDocument();
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

    fireEvent.click(jobButton("批次二"));

    expect(await screen.findByRole("button", { name: "展开" })).toBeInTheDocument();
    expect(screen.queryByText("客队战术 B")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(await screen.findByText("客队战术 B")).toBeInTheDocument();

    fireEvent.click(jobButton("批次一"));

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

    fireEvent.click(jobButton("批次二"));

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

describe("ResultsPage 任务对比", () => {
  const threeJobs = {
    items: [
      makeJob(),
      makeJob({ id: "job-2", name: "批次二" }),
      makeJob({ id: "job-3", name: "批次三" }),
    ],
    total: 3,
    next_offset: null,
  };

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("面板列出基线之外的候选任务，默认变体 B 且未选择候选时按钮禁用", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");

    expect(candidateCheckbox("批次二", "job-2")).toBeInTheDocument();
    expect(candidateCheckbox("批次三", "job-3")).toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: "候选任务 批次一（job-1）" }),
    ).not.toBeInTheDocument();
    expect(comparePanel()).toHaveTextContent("批次一");
    expect(comparePanel()).toHaveTextContent("job-1");
    expect(within(comparePanel()).getByRole("button", { name: "B" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(comparePanel()).getByRole("button", { name: "开始对比" })).toBeDisabled();
  });

  it("提交对比时携带基线、候选、变体与视角", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(candidateCheckbox("批次三", "job-3"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "A" }));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));

    await waitFor(() => expect(callsTo("/api/results/compare")).toHaveLength(1));
    const call = callsTo("/api/results/compare")[0];
    expect(call.url).toBe("http://127.0.0.1:43210/api/results/compare");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      baseline_job_id: "job-1",
      candidate_job_ids: ["job-2", "job-3"],
      variant: "A",
      side: 0,
    });
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
  });

  it("渲染可比候选的配对差值与置信区间", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs, compare: makeCompareResult() }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));

    const table = await screen.findByRole("table", { name: "任务对比结果" });
    expect(within(table).getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "候选任务",
      "可比性",
      "场次",
      "Δ胜率",
      "Δ净胜球",
      "Δ积分",
      "ΔxGD",
    ]);
    const cells = compareRowTexts()[0];
    expect(cells[0]).toContain("批次二");
    expect(cells[0]).toContain("job-2");
    expect(cells[0]).toContain("同种子 6 场，抽签不一致 0 场");
    expect(cells[1]).toContain("可比");
    expect(cells[2]).toBe("6");
    expect(cells[3]).toContain("+12.5%");
    expect(cells[3]).toContain("95% 区间 [2.0%, 23.0%]");
    expect(cells[4]).toBe("+0.40");
    expect(cells[5]).toBe("+0.50");
    expect(cells[6]).toBe("+0.15");
  });

  it("不可比候选展示原因与不一致种子", async () => {
    const compare = makeCompareResult({
      candidates: [
        makeCompareCandidate({
          comparable: false,
          reason: "客队战术池分配不同：2/6 个同种子场次使用了不同战术",
          pairing: makeComparePairing({
            draw_mismatches: 2,
            mismatched_seeds: [11, 12, 13, 14],
            missing_seeds: [21, 22],
          }),
          paired: null,
        }),
      ],
    });
    stubFetch(resultsFetch({ jobs: threeJobs, compare }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));

    await screen.findByRole("table", { name: "任务对比结果" });
    const cells = compareRowTexts()[0];
    expect(cells[0]).toContain("同种子 6 场，抽签不一致 2 场");
    expect(cells[1]).toContain("不可比");
    expect(cells[1]).toContain("客队战术池分配不同：2/6 个同种子场次使用了不同战术");
    expect(cells[1]).toContain("不一致种子 11、12、13…");
    expect(cells[1]).toContain("缺失种子 21、22");
    expect(cells[2]).toBe("—");
    expect(cells[3]).toBe("—");
    expect(cells[4]).toBe("—");
    expect(cells[5]).toBe("—");
    expect(cells[6]).toBe("—");
  });

  it("对比失败展示内联错误并可重试", async () => {
    let attempts = 0;
    const base = resultsFetch({ jobs: threeJobs });
    stubFetch((url, init) => {
      if (!url.includes("/api/results/compare")) return base(url, init);
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "invalid_request", message: "候选任务不可用" } }, 400);
      }
      return jsonResponse(makeCompareResult());
    });
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("候选任务不可用");
    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    expect(await screen.findByRole("table", { name: "任务对比结果" })).toBeInTheDocument();
    await waitFor(() => expect(attempts).toBe(2));
  });

  it("对比请求进行中禁用按钮并显示加载状态", async () => {
    const pending = deferred<Response>();
    const base = resultsFetch({ jobs: threeJobs });
    stubFetch((url, init) => {
      if (!url.includes("/api/results/compare")) return base(url, init);
      return pending.promise;
    });
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));

    const busyButton = await within(comparePanel()).findByRole("button", { name: "对比中…" });
    expect(busyButton).toBeDisabled();
    expect(comparePanel()).toHaveAttribute("aria-busy", "true");

    pending.resolve(jsonResponse(makeCompareResult()));

    expect(await screen.findByRole("table", { name: "任务对比结果" })).toBeInTheDocument();
    expect(within(comparePanel()).getByRole("button", { name: "开始对比" })).toBeEnabled();
  });

  it("迟到的旧对比响应不覆盖新一轮运行状态与结果", async () => {
    const stale = deferred<Response>();
    const current = deferred<Response>();
    const pendingResponses = [stale, current];
    const base = resultsFetch({ jobs: threeJobs });
    stubFetch((url, init) => {
      if (!url.includes("/api/results/compare")) return base(url, init);
      const response = pendingResponses.shift();
      if (response === undefined) throw new Error("未预期的对比请求");
      return response.promise;
    });
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await waitFor(() => expect(callsTo("/api/results/compare")).toHaveLength(1));
    expect(within(comparePanel()).getByRole("button", { name: "对比中…" })).toBeDisabled();

    fireEvent.click(within(comparePanel()).getByRole("button", { name: "A" }));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await waitFor(() => expect(callsTo("/api/results/compare")).toHaveLength(2));
    expect(within(comparePanel()).getByRole("button", { name: "对比中…" })).toBeDisabled();

    await act(async () => {
      stale.resolve(
        jsonResponse(
          makeCompareResult({
            candidates: [
              makeCompareCandidate({
                name: "迟到旧结果",
                paired: makeComparePaired({
                  win_rate_delta: 0.1,
                  win_rate_delta_ci: [0.05, 0.2],
                }),
              }),
            ],
          }),
        ),
      );
    });

    expect(comparePanel()).toHaveAttribute("aria-busy", "true");
    expect(within(comparePanel()).getByRole("button", { name: "对比中…" })).toBeDisabled();
    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();

    await act(async () => {
      current.resolve(
        jsonResponse(
          makeCompareResult({
            variant: "A",
            candidates: [
              makeCompareCandidate({
                name: "当前结果",
                paired: makeComparePaired({
                  win_rate_delta: 0.5,
                  win_rate_delta_ci: [0.4, 0.6],
                }),
              }),
            ],
          }),
        ),
      );
    });

    const table = screen.getByRole("table", { name: "任务对比结果" });
    expect(table).not.toHaveTextContent("迟到旧结果");
    const cells = compareRowTexts()[0];
    expect(cells[0]).toContain("当前结果");
    expect(cells[3]).toContain("+50.0%");
  });

  it("切换统计视角后清空旧结果并保留候选选择", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await screen.findByRole("table", { name: "任务对比结果" });

    fireEvent.click(screen.getByRole("button", { name: "客队" }));

    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();
    expect(candidateCheckbox("批次二", "job-2")).toBeChecked();

    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await waitFor(() => expect(callsTo("/api/results/compare")).toHaveLength(2));
    const second = callsTo("/api/results/compare")[1];
    expect(JSON.parse(String(second.init.body)).side).toBe(1);
  });

  it("切换对比变体后清空旧结果，切回原变体不复活", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    expect(await screen.findByRole("table", { name: "任务对比结果" })).toBeInTheDocument();

    fireEvent.click(within(comparePanel()).getByRole("button", { name: "A" }));
    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();

    fireEvent.click(within(comparePanel()).getByRole("button", { name: "B" }));
    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();
    expect(within(comparePanel()).getByRole("button", { name: "开始对比" })).toBeEnabled();
    expect(callsTo("/api/results/compare")).toHaveLength(1);

    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await waitFor(() => expect(callsTo("/api/results/compare")).toHaveLength(2));
    expect(JSON.parse(String(callsTo("/api/results/compare")[1].init.body)).variant).toBe("B");
    expect(await screen.findByRole("table", { name: "任务对比结果" })).toBeInTheDocument();
  });

  it("切换基线任务后清空对比结果与候选选择", async () => {
    stubFetch(resultsFetch({ jobs: threeJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");
    fireEvent.click(candidateCheckbox("批次二", "job-2"));
    fireEvent.click(within(comparePanel()).getByRole("button", { name: "开始对比" }));
    await screen.findByRole("table", { name: "任务对比结果" });

    fireEvent.click(jobButton("批次二"));

    await waitFor(() => expect(comparePanel()).toHaveTextContent("批次二"));
    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();
    expect(candidateCheckbox("批次一", "job-1")).not.toBeChecked();
    expect(candidateCheckbox("批次三", "job-3")).not.toBeChecked();
    expect(within(comparePanel()).getByRole("button", { name: "开始对比" })).toBeDisabled();
  });

  it("候选任务最多选择五个", async () => {
    const sevenJobs = {
      items: [
        makeJob(),
        makeJob({ id: "job-2", name: "批次二" }),
        makeJob({ id: "job-3", name: "批次三" }),
        makeJob({ id: "job-4", name: "批次四" }),
        makeJob({ id: "job-5", name: "批次五" }),
        makeJob({ id: "job-6", name: "批次六" }),
        makeJob({ id: "job-7", name: "批次七" }),
      ],
      total: 7,
      next_offset: null,
    };
    stubFetch(resultsFetch({ jobs: sevenJobs }));
    renderResultsPage();

    await screen.findByText("任务对比");
    for (const [label, jobId] of [
      ["批次二", "job-2"],
      ["批次三", "job-3"],
      ["批次四", "job-4"],
      ["批次五", "job-5"],
      ["批次六", "job-6"],
    ]) {
      fireEvent.click(candidateCheckbox(label, jobId));
    }

    expect(candidateCheckbox("批次七", "job-7")).toBeDisabled();
    expect(candidateCheckbox("批次二", "job-2")).toBeEnabled();
  });
});

describe("ResultsPage 任务多选与批量删除", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("全选只覆盖当前筛选结果并支持清空选择", async () => {
    const allJobs = {
      items: [
        makeJob(),
        makeJob({ id: "job-2", name: "批次二", status: "running" }),
        makeJob({ id: "job-3", name: "批次三", status: "queued" }),
      ],
      total: 3,
      next_offset: null,
    };
    const completedJobs = { items: [makeJob()], total: 1, next_offset: null };
    const base = resultsFetch({ jobs: allJobs });
    stubFetch((url, init) => {
      if (!url.includes("/api/jobs?")) return base(url, init);
      return jsonResponse(url.includes("status=completed") ? completedJobs : allJobs);
    });
    renderResultsPage();

    expect(await screen.findByRole("region", { name: "实验任务" })).toBeInTheDocument();
    await waitFor(() => expect(within(jobRegion()).getAllByRole("listitem")).toHaveLength(3));
    expect(within(jobRegion()).getByText("已选 0 个任务")).toBeInTheDocument();

    fireEvent.click(within(jobRegion()).getByRole("checkbox", { name: "全选当前筛选结果" }));

    expect(within(jobRegion()).getByText("已选 3 个任务")).toBeInTheDocument();
    expect(jobCheckbox("批次一", "job-1")).toBeChecked();
    expect(jobCheckbox("批次二", "job-2")).toBeChecked();
    expect(jobCheckbox("批次三", "job-3")).toBeChecked();

    fireEvent.click(within(jobRegion()).getByRole("button", { name: "清空选择" }));

    expect(within(jobRegion()).getByText("已选 0 个任务")).toBeInTheDocument();
    expect(jobCheckbox("批次一", "job-1")).not.toBeChecked();

    fireEvent.change(within(jobRegion()).getByLabelText("状态筛选"), {
      target: { value: "completed" },
    });

    expect(within(jobRegion()).getByText("已选 0 个任务")).toBeInTheDocument();
    await waitFor(() => expect(within(jobRegion()).getAllByRole("listitem")).toHaveLength(1));
    expect(jobCheckbox("批次一", "job-1")).not.toBeChecked();
    const filtered = await waitFor(() => {
      const call = callsTo("/api/jobs?").find((item) => item.url.includes("status=completed"));
      if (call === undefined) throw new Error("未发送状态筛选请求");
      return call;
    });
    expect(filtered.url).toBe(
      "http://127.0.0.1:43210/api/jobs?status=completed&limit=50&offset=0",
    );

    fireEvent.click(within(jobRegion()).getByRole("checkbox", { name: "全选当前筛选结果" }));

    expect(within(jobRegion()).getByText("已选 1 个任务")).toBeInTheDocument();
    expect(jobCheckbox("批次一", "job-1")).toBeChecked();
  });

  it("点击任务名切换当前任务而不改变选择", async () => {
    stubFetch(
      resultsFetch({
        jobs: {
          items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
          total: 2,
          next_offset: null,
        },
        summary: (url) => {
          const jobId = url.includes("job-2") ? "job-2" : "job-1";
          return makeSummary({
            job: makeJob({ id: jobId, name: jobId === "job-2" ? "批次二" : "批次一" }),
          });
        },
      }),
    );
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobCheckbox("批次二", "job-2"));

    expect(jobCheckbox("批次二", "job-2")).toBeChecked();
    expect(jobButton("批次一")).toHaveAttribute("aria-current", "true");

    fireEvent.click(jobButton("批次二"));

    await waitFor(() => expect(callsTo("/job-2/summary")).toHaveLength(1));
    expect(jobButton("批次二")).toHaveAttribute("aria-current", "true");
    expect(jobButton("批次一")).not.toHaveAttribute("aria-current");
    expect(jobCheckbox("批次二", "job-2")).toBeChecked();
    expect(jobCheckbox("批次一", "job-1")).not.toBeChecked();
  });

  it("删除确认列出任务明细且确认前不发送删除请求", async () => {
    stubFetch(
      resultsFetch({
        jobs: {
          items: [makeJob(), makeJob({ id: "job-2", name: "批次二", total: 6 })],
          total: 2,
          next_offset: null,
        },
      }),
    );
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(jobCheckbox("批次二", "job-2"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));

    const dialog = screen.getByRole("alertdialog", { name: "确认批量删除" });
    expect(within(dialog).getByText(/将删除 2 个任务/)).toBeInTheDocument();
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(2);
    expect(within(dialog).getByText("批次一（job-1）（总场数 4）")).toBeInTheDocument();
    expect(within(dialog).getByText("批次二（job-2）（总场数 6）")).toBeInTheDocument();
    expect(
      callsTo("/api/jobs").filter((call) => call.init.method === "DELETE"),
    ).toHaveLength(0);

    fireEvent.click(within(dialog).getByRole("button", { name: "放弃" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      callsTo("/api/jobs").filter((call) => call.init.method === "DELETE"),
    ).toHaveLength(0);
    expect(within(jobRegion()).getByText("已选 2 个任务")).toBeInTheDocument();
  });

  it("确认框可用 Escape 关闭且保留选择", async () => {
    stubFetch(resultsFetch());
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(jobCheckbox("批次一", "job-1")).toBeChecked();
    expect(
      callsTo("/api/jobs").filter((call) => call.init.method === "DELETE"),
    ).toHaveLength(0);
  });

  it("确认后批量删除展示已删除与失败原因，当前任务被删后切到剩余首个", async () => {
    const initialJobs = {
      items: [
        makeJob(),
        makeJob({ id: "job-2", name: "批次二", status: "running" }),
        makeJob({ id: "job-3", name: "批次三" }),
      ],
      total: 3,
      next_offset: null,
    };
    const remainingJobs = {
      items: [
        makeJob({ id: "job-2", name: "批次二", status: "running" }),
        makeJob({ id: "job-3", name: "批次三" }),
      ],
      total: 2,
      next_offset: null,
    };
    let listCalls = 0;
    const base = resultsFetch({
      summary: (url) => {
        const jobId = url.includes("job-2") ? "job-2" : url.includes("job-3") ? "job-3" : "job-1";
        if (jobId === "job-2") return makeSummary({ job: makeJob({ id: "job-2", name: "批次二" }) });
        if (jobId === "job-3") return makeSummary({ job: makeJob({ id: "job-3", name: "批次三" }) });
        return makeSummary();
      },
    });
    stubFetch((url, init) => {
      if ((init.method ?? "GET") === "DELETE") {
        return jsonResponse({
          deleted: ["job-1"],
          failed: [{ id: "job-2", error: "任务正在运行或排队" }],
        });
      }
      if (url.includes("/api/jobs?")) {
        listCalls += 1;
        return jsonResponse(listCalls === 1 ? initialJobs : remainingJobs);
      }
      return base(url, init);
    });
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));
    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(jobCheckbox("批次二", "job-2"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    const deleteCall = await waitFor(() => {
      const call = callsTo("/api/jobs").find((item) => item.init.method === "DELETE");
      if (call === undefined) throw new Error("未发送批量删除请求");
      return call;
    });
    expect(JSON.parse(String(deleteCall.init.body))).toEqual({ ids: ["job-1", "job-2"] });

    const result = await screen.findByRole("status", { name: "批量删除结果" });
    expect(within(result).getByText("已删除 1 个任务")).toBeInTheDocument();
    expect(within(result).getByText("job-1")).toBeInTheDocument();
    expect(within(result).getByText("job-2：任务正在运行或排队")).toBeInTheDocument();

    await waitFor(() =>
      expect(within(jobRegion()).queryByText("批次一")).not.toBeInTheDocument(),
    );
    expect(jobButton("批次二")).toHaveAttribute("aria-current", "true");
    await waitFor(() => expect(callsTo("/job-2/summary")).toHaveLength(1));
  });

  it("批量删除请求失败时保留选择并展示错误", async () => {
    const base = resultsFetch();
    stubFetch((url, init) => {
      if ((init.method ?? "GET") === "DELETE") {
        return jsonResponse(
          { error: { code: "batch_delete_failed", message: "批量删除失败" } },
          400,
        );
      }
      return base(url, init);
    });
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("批量删除失败");
    expect(jobCheckbox("批次一", "job-1")).toBeChecked();
    expect(within(jobRegion()).getByText("已选 1 个任务")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "批量删除结果" })).not.toBeInTheDocument();
  });

  it("批量删除进行中展示忙碌状态", async () => {
    const pending = deferred<Response>();
    const base = resultsFetch({
      jobs: {
        items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
        total: 2,
        next_offset: null,
      },
    });
    stubFetch((url, init) => {
      if ((init.method ?? "GET") === "DELETE") return pending.promise;
      return base(url, init);
    });
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await within(jobRegion()).findByRole("button", { name: "删除中…" })).toBeDisabled();
    expect(jobActions()).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "确认删除" })).toBeDisabled();

    await act(async () => {
      pending.resolve(jsonResponse({ deleted: ["job-1"], failed: [] }));
    });

    expect(await screen.findByRole("status", { name: "批量删除结果" })).toHaveTextContent(
      "已删除 1 个任务",
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(within(jobRegion()).getByRole("button", { name: "删除所选" })).toBeDisabled();
    expect(jobActions()).toHaveAttribute("aria-busy", "false");
  });

  it("删除当前任务后立即切换基线并重置分页候选与下载错误", async () => {
    const initialJobs = {
      items: [
        makeJob(),
        makeJob({ id: "job-2", name: "批次二" }),
        makeJob({ id: "job-3", name: "批次三" }),
      ],
      total: 3,
      next_offset: null,
    };
    const remainingJobs = {
      items: [makeJob(), makeJob({ id: "job-3", name: "批次三" })],
      total: 2,
      next_offset: null,
    };
    const pendingList = deferred<Response>();
    let listCalls = 0;
    const base = resultsFetch({
      summary: (url) => {
        const jobId = url.includes("/job-2/") ? "job-2" : url.includes("/job-3/") ? "job-3" : "job-1";
        const name = jobId === "job-2" ? "批次二" : jobId === "job-3" ? "批次三" : "批次一";
        return makeSummary({ job: makeJob({ id: jobId, name }) });
      },
      runs: (url) => {
        const jobId = url.includes("/job-2/") ? "job-2" : url.includes("/job-3/") ? "job-3" : "job-1";
        const offset = Number(new URL(url).searchParams.get("offset") ?? "0");
        if (jobId === "job-2" && offset === 0) {
          return {
            items: [makeRun({ job_id: "job-2" }), makeRun({ job_id: "job-2", sequence: 2 })],
            total: 40,
            next_offset: 20,
          };
        }
        return { items: [makeRun({ job_id: jobId })], total: 1, next_offset: null };
      },
    });
    stubFetch((url, init) => {
      if ((init.method ?? "GET") === "DELETE") {
        return jsonResponse({ deleted: ["job-2"], failed: [] });
      }
      if (url.includes("/export.csv")) {
        return jsonResponse({ error: { code: "export_failed", message: "导出失败" } }, 500);
      }
      if (url.includes("/api/jobs?")) {
        listCalls += 1;
        return listCalls === 1 ? jsonResponse(initialJobs) : pendingList.promise;
      }
      return base(url, init);
    });
    renderResultsPage();

    await screen.findByRole("region", { name: "实验任务" });
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));
    const job1RunsBefore = runsOffsets("/job-1/runs").length;

    fireEvent.click(jobButton("批次二"));

    await waitFor(() => expect(callsTo("/job-2/summary")).toHaveLength(1));
    expect(jobButton("批次二")).toHaveAttribute("aria-current", "true");
    expect(jobButton("批次一")).not.toHaveAttribute("aria-current");

    fireEvent.click(screen.getByRole("button", { name: "下载 CSV" }));
    expect(await screen.findByText("导出失败")).toBeInTheDocument();

    const nextPage = await screen.findByRole("button", { name: "下一页" });
    await waitFor(() => expect(nextPage).toBeEnabled());
    fireEvent.click(nextPage);
    await waitFor(() => expect(runsOffsets("/job-2/runs")).toContain("20"));

    fireEvent.click(candidateCheckbox("批次三", "job-3"));
    expect(candidateCheckbox("批次三", "job-3")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "开始对比" }));
    expect(await screen.findByRole("table", { name: "任务对比结果" })).toBeInTheDocument();

    fireEvent.click(jobCheckbox("批次二", "job-2"));
    fireEvent.click(within(jobRegion()).getByRole("button", { name: "删除所选" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(jobButton("批次一")).toHaveAttribute("aria-current", "true"));
    expect(jobButton("批次二")).toBeInTheDocument();
    expect(jobButton("批次二")).not.toHaveAttribute("aria-current");
    expect(screen.queryByRole("table", { name: "任务对比结果" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始对比" })).toBeDisabled();
    expect(candidateCheckbox("批次三", "job-3")).not.toBeChecked();
    expect(screen.queryByText("导出失败")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(runsOffsets("/job-1/runs").length).toBeGreaterThan(job1RunsBefore),
    );
    expect(runsOffsets("/job-1/runs")).not.toContain("20");
    expect(runsOffsets("/job-1/runs")[runsOffsets("/job-1/runs").length - 1]).toBe("0");

    await act(async () => {
      pendingList.resolve(jsonResponse(remainingJobs));
    });

    const result = await screen.findByRole("status", { name: "批量删除结果" });
    expect(result).toHaveTextContent("已删除 1 个任务");
    await waitFor(() =>
      expect(within(jobRegion()).queryByText("批次二")).not.toBeInTheDocument(),
    );
    expect(jobButton("批次一")).toHaveAttribute("aria-current", "true");
    expect(jobCheckbox("批次三", "job-3")).not.toBeChecked();
  });

  it("客队战术池折叠状态跨组件卸载保留且只写入折叠布尔", async () => {
    stubFetch(resultsFetch({ pool: makePoolSummary() }));
    const first = renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("客队战术 1")).toBeInTheDocument();

    const stored: unknown = JSON.parse(
      String(sessionStorage.getItem("fm27lab.results.pool-expanded")),
    );
    expect(stored).toEqual({ "job-1": true });
    expect(localStorage.length).toBe(0);

    first.unmount();

    renderResultsPage();

    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "折叠" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(await screen.findByText("客队战术 1")).toBeInTheDocument();
  });

  it.each([
    ["非法 JSON", "not-json{"],
    ["JSON 字符串", '"展开"'],
    ["JSON 数字", "42"],
    ["JSON null", "null"],
    ["JSON 数组", "[true]"],
    ["非布尔字段值", JSON.stringify({ "job-1": "true", "job-2": 1, "job-3": null })],
  ])("客队战术池折叠状态在会话数据为%s时回退默认折叠", async (_label, raw) => {
    sessionStorage.setItem("fm27lab.results.pool-expanded", raw);
    stubFetch(resultsFetch({ pool: makePoolSummary() }));
    renderResultsPage();

    expect(await screen.findByRole("region", { name: "实验任务" })).toBeInTheDocument();
    expect(await screen.findByText("客队战术池")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("客队战术 1")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "折叠" })).not.toBeInTheDocument();
  });

  it("任务列表与批量操作提供窄屏可换行结构", async () => {
    stubFetch(resultsFetch());
    renderResultsPage();

    const region = await screen.findByRole("region", { name: "实验任务" });
    expect(region).toHaveClass("results-jobs");
    expect(region.querySelector(".results-jobs-head")).not.toBeNull();
    expect(region.querySelector(".results-jobs-actions")).not.toBeNull();
    expect(region.querySelector(".results-jobs-list")).not.toBeNull();
    expect(within(region).getByRole("button", { name: "删除所选" })).toBeInTheDocument();
    expect(within(region).getAllByRole("listitem")[0]).toHaveClass("results-job");
    expect(
      (await screen.findByRole("table", { name: "逐场记录" })).closest(".jobs-table-wrap"),
    ).not.toBeNull();

    fireEvent.click(jobCheckbox("批次一", "job-1"));
    fireEvent.click(within(region).getByRole("button", { name: "删除所选" }));

    expect(screen.getByRole("alertdialog")).toHaveClass("jobs-batch-confirm");
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

  it("compareResults 提交对比参数并读取结果", async () => {
    stubFetch(resultsFetch({ compare: makeCompareResult() }));

    const result = await compareResults(connection, {
      baseline_job_id: "job-1",
      candidate_job_ids: ["job-2"],
      variant: "A",
      side: 1,
      reps: 200,
    });

    expect(result.baseline.job_id).toBe("job-1");
    expect(result.candidates[0].comparable).toBe(true);
    const call = fetchCalls()[0];
    expect(call.url).toBe("http://127.0.0.1:43210/api/results/compare");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      baseline_job_id: "job-1",
      candidate_job_ids: ["job-2"],
      variant: "A",
      side: 1,
      reps: 200,
    });
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
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

describe("ResultsPage 实时事件", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("活动任务事件触发汇总、逐场与客队池刷新", async () => {
    const stream = controllableEventStream();
    stubFetch(resultsFetch(), () => stream.response);
    renderResultsPage();
    await screen.findByText("批次一");
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));
    await waitFor(() => expect(callsTo("/job-1/runs")).toHaveLength(1));
    await waitFor(() => expect(callsTo("/job-1/pool-summary")).toHaveLength(1));
    await waitFor(() => expect(callsTo("/api/jobs?")).toHaveLength(1));

    stream.send(
      'event: job.updated\ndata: {"job_id":"job-1","status":"completed","completed":4,"total":4}\n\n',
    );

    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(2));
    await waitFor(() => expect(callsTo("/job-1/runs")).toHaveLength(2));
    await waitFor(() => expect(callsTo("/job-1/pool-summary")).toHaveLength(2));
    await waitFor(() => expect(callsTo("/api/jobs?")).toHaveLength(2));
  });

  it("活动任务事件兼容 id 形状负载", async () => {
    const stream = controllableEventStream();
    stubFetch(resultsFetch(), () => stream.response);
    renderResultsPage();
    await screen.findByText("批次一");
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));

    stream.send(
      'event: job.updated\ndata: {"id":"job-1","status":"completed","completed":4,"total":4}\n\n',
    );

    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(2));
  });

  it("窗口内连续事件合并为一次刷新", async () => {
    const stream = controllableEventStream();
    stubFetch(resultsFetch(), () => stream.response);
    const { client } = renderResultsPage();
    await screen.findByText("批次一");
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));
    await waitFor(() => expect(eventsCalls()).toHaveLength(1));
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const eventPayload = (completed: number) =>
      `event: job.updated\ndata: {"job_id":"job-1","status":"running","completed":${completed},"total":4}\n\n`;
    stream.send(eventPayload(1));
    stream.send(eventPayload(2));
    stream.send(eventPayload(3));

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(4), { timeout: 2000 });
    for (const key of ["results-jobs", "job-summary", "job-runs", "job-pool-summary"]) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] });
    }
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(2));
    expect(invalidate).toHaveBeenCalledTimes(4);
  });

  it("删除事件只刷新任务列表", async () => {
    const stream = controllableEventStream();
    stubFetch(resultsFetch(), () => stream.response);
    renderResultsPage();
    await screen.findByText("批次一");
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));

    stream.send('event: job.deleted\ndata: {"job_id":"job-2","deleted":true}\n\n');

    await waitFor(() => expect(callsTo("/api/jobs?")).toHaveLength(2));
    expect(callsTo("/job-1/summary")).toHaveLength(1);
  });

  it("非活动任务事件不触发刷新", async () => {
    const stream = controllableEventStream();
    stubFetch(
      resultsFetch({
        jobs: {
          items: [makeJob(), makeJob({ id: "job-2", name: "批次二" })],
          total: 2,
          next_offset: null,
        },
      }),
      () => stream.response,
    );
    const { client } = renderResultsPage();
    await screen.findAllByText("批次二");
    await waitFor(() => expect(callsTo("/job-1/summary")).toHaveLength(1));
    await waitFor(() => expect(eventsCalls()).toHaveLength(1));
    const invalidate = vi.spyOn(client, "invalidateQueries");

    stream.send(
      'event: job.updated\ndata: {"id":"job-2","status":"running","completed":1,"total":4}\n\n',
    );
    await new Promise((resolve) => setTimeout(resolve, REFRESH_WINDOW_MS + 100));

    expect(invalidate).not.toHaveBeenCalled();
    expect(callsTo("/job-1/summary")).toHaveLength(1);
  });

  it("卸载时中止事件流连接", async () => {
    const stream = controllableEventStream();
    stubFetch(resultsFetch(), () => stream.response);
    const view = renderResultsPage();
    await screen.findByText("批次一");
    await waitFor(() => expect(eventsCalls()).toHaveLength(1));
    const signal = eventsCalls()[0].init.signal;
    expect(signal?.aborted).toBe(false);

    view.unmount();

    expect(signal?.aborted).toBe(true);
  });
});
