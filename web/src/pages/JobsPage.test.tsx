import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  getJob,
  listJobRuns,
  updateJob,
  type Health,
  type Job,
  type JobRun,
} from "../lib/api";
import { JobsPage } from "./JobsPage";

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

function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: async () => {
      throw new Error("no content");
    },
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
    status: "queued",
    name: "任务一",
    config: {},
    summary: {},
    workers: 2,
    total: 100,
    completed: 0,
    created_at: "2026-11-13T10:00:00+00:00",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function renderJobsPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider
        value={{ connection, health, connectionError: null, refreshing: false, refresh: vi.fn() }}
      >
        <JobsPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function rowFor(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (row === null) throw new Error("未找到任务行：" + text);
  return row;
}

describe("JobsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载中显示状态，成功后渲染带鉴权的任务列表", async () => {
    const pending = deferred<Response>();
    stubFetch(() => pending.promise);
    renderJobsPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载任务");

    pending.resolve(jsonResponse({ items: [makeJob()], total: 1, next_offset: null }));

    expect(await screen.findByText("任务一")).toBeInTheDocument();
    expect(within(rowFor("任务一")).getByText("排队中")).toBeInTheDocument();

    const [first] = fetchCalls();
    expect(first.url).toBe("http://127.0.0.1:43210/api/jobs?limit=20&offset=0");
    expect(new Headers(first.init.headers).get("Authorization")).toBe("Bearer test-token");

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(callsTo("/api/jobs?").length).toBe(2));
  });

  it("列表为空时显示空态", async () => {
    stubFetch(() => jsonResponse({ items: [], total: 0, next_offset: null }));
    renderJobsPage();

    expect(await screen.findByText("尚无任务")).toBeInTheDocument();
    expect(screen.getByText("创建任务后，这里会显示运行状态、进度与取消入口。")).toBeInTheDocument();
  });

  it("列表加载失败时展示后端错误信息并可重试", async () => {
    stubFetch(() =>
      jsonResponse({ error: { code: "validation_failed", message: "任务列表查询失败" } }, 400),
    );
    renderJobsPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("任务列表查询失败");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(callsTo("/api/jobs?").length).toBe(2));
  });

  it("切换状态筛选会带 status 查询并渲染筛选结果", async () => {
    stubFetch((url) => {
      if (url.includes("status=completed")) {
        return jsonResponse({
          items: [makeJob({ id: "job-done", name: "已完成任务", status: "completed" })],
          total: 1,
          next_offset: null,
        });
      }
      return jsonResponse({ items: [makeJob()], total: 1, next_offset: null });
    });
    renderJobsPage();
    await screen.findByText("任务一");

    fireEvent.change(screen.getByLabelText("状态筛选"), { target: { value: "completed" } });

    expect(await screen.findByText("已完成任务")).toBeInTheDocument();
    expect(callsTo("/api/jobs?status=completed&limit=20&offset=0")).toHaveLength(1);
  });

  it("分页按钮按 next_offset 加载下一页", async () => {
    stubFetch((url) => {
      if (url.includes("offset=20")) {
        return jsonResponse({
          items: [makeJob({ id: "job-2", name: "第二页任务" })],
          total: 21,
          next_offset: null,
        });
      }
      return jsonResponse({ items: [makeJob()], total: 21, next_offset: 20 });
    });
    renderJobsPage();
    await screen.findByText("任务一");
    expect(screen.getByText("共 21 个任务")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("第二页任务")).toBeInTheDocument();
    expect(callsTo("offset=20")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
  });

  it("取消任务需要二次确认，成功后调用取消接口并刷新列表", async () => {
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        return jsonResponse(makeJob({ name: "待取消任务", status: "cancelled" }));
      }
      return jsonResponse({ items: [makeJob({ name: "待取消任务" })], total: 1, next_offset: null });
    });
    renderJobsPage();
    await screen.findByText("待取消任务");

    fireEvent.click(within(rowFor("待取消任务")).getByRole("button", { name: "取消" }));
    expect(within(rowFor("待取消任务")).getByRole("button", { name: "确认取消" })).toBeInTheDocument();
    fireEvent.click(within(rowFor("待取消任务")).getByRole("button", { name: "放弃" }));
    expect(callsTo("/cancel")).toHaveLength(0);

    fireEvent.click(within(rowFor("待取消任务")).getByRole("button", { name: "取消" }));
    fireEvent.click(within(rowFor("待取消任务")).getByRole("button", { name: "确认取消" }));

    await waitFor(() => expect(callsTo("/api/jobs/job-1/cancel")).toHaveLength(1));
    expect(callsTo("/api/jobs/job-1/cancel")[0].init.method).toBe("POST");
    expect(await screen.findByText("已取消任务「待取消任务」")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/api/jobs?").length).toBeGreaterThanOrEqual(2));
  });

  it("删除任务需要二次确认，成功后调用 DELETE 并刷新列表", async () => {
    let deleted = false;
    stubFetch((_url, init) => {
      if (init.method === "DELETE") {
        deleted = true;
        return noContentResponse();
      }
      if (deleted) return jsonResponse({ items: [], total: 0, next_offset: null });
      return jsonResponse({ items: [makeJob({ name: "待删除任务" })], total: 1, next_offset: null });
    });
    renderJobsPage();
    await screen.findByText("待删除任务");

    fireEvent.click(within(rowFor("待删除任务")).getByRole("button", { name: "删除" }));
    fireEvent.click(within(rowFor("待删除任务")).getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(callsTo("/api/jobs/job-1")).toHaveLength(1));
    expect(callsTo("/api/jobs/job-1")[0].url).toBe("http://127.0.0.1:43210/api/jobs/job-1");
    expect(callsTo("/api/jobs/job-1")[0].init.method).toBe("DELETE");
    expect(await screen.findByText("已删除任务「待删除任务」")).toBeInTheDocument();
    expect(await screen.findByText("尚无任务")).toBeInTheDocument();
  });

  it("创建任务提交表单并刷新列表", async () => {
    stubFetch((_url, init) => {
      if (init.method === "POST") return jsonResponse(makeJob({ name: "批量任务" }), 201);
      return jsonResponse({ items: [], total: 0, next_offset: null });
    });
    renderJobsPage();
    await screen.findByText("尚无任务");

    fireEvent.click(screen.getByRole("button", { name: "新建任务" }));
    const workers = screen.getByLabelText("并行数");
    fireEvent.change(workers, { target: { value: "257" } });
    expect(workers).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("并行数需为 1–256 的整数")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建" })).toBeDisabled();

    fireEvent.change(workers, { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("任务名称"), { target: { value: "批量任务" } });
    fireEvent.change(screen.getByLabelText("总场数"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(fetchCalls().some((call) => call.init.method === "POST")).toBe(true));
    const post = fetchCalls().find((call) => call.init.method === "POST");
    expect(JSON.parse(String(post?.init.body))).toEqual({
      kind: "experiment",
      name: "批量任务",
      workers: 4,
      total: 100,
    });
    expect(await screen.findByText("任务已创建")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/api/jobs?").length).toBe(2));
  });

  it("取消操作失败时展示后端错误信息", async () => {
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        return jsonResponse(
          { error: { code: "invalid_transition", message: "任务状态不允许该流转" } },
          409,
        );
      }
      return jsonResponse({ items: [makeJob({ name: "取消失败任务" })], total: 1, next_offset: null });
    });
    renderJobsPage();
    await screen.findByText("取消失败任务");

    fireEvent.click(within(rowFor("取消失败任务")).getByRole("button", { name: "取消" }));
    fireEvent.click(within(rowFor("取消失败任务")).getByRole("button", { name: "确认取消" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("任务状态不允许该流转");
  });
});

function makeRun(overrides: Partial<JobRun> = {}): JobRun {
  return {
    job_id: "job-1",
    sequence: 1,
    variant: "a",
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

describe("jobs API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getJob 请求单任务并编码任务 id", async () => {
    stubFetch(() => jsonResponse(makeJob()));

    const job = await getJob(connection, "job/1");

    expect(job.id).toBe("job-1");
    expect(fetchCalls()[0].url).toBe("http://127.0.0.1:43210/api/jobs/job%2F1");
    expect(fetchCalls()[0].init.method).toBeUndefined();
  });

  it("updateJob 使用 PATCH 提交变更", async () => {
    stubFetch(() => jsonResponse(makeJob({ status: "running" })));

    await updateJob(connection, "job-1", { status: "running" });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/jobs/job-1");
    expect(call.init.method).toBe("PATCH");
    expect(JSON.parse(String(call.init.body))).toEqual({ status: "running" });
  });

  it("listJobRuns 按 limit 与 offset 分页读取逐场记录", async () => {
    stubFetch(() => jsonResponse({ items: [makeRun()], total: 1, next_offset: null }));

    const runs = await listJobRuns(connection, "job-1", { limit: 10, offset: 20 });

    expect(runs.items[0].sequence).toBe(1);
    expect(fetchCalls()[0].url).toBe(
      "http://127.0.0.1:43210/api/jobs/job-1/runs?limit=10&offset=20",
    );
  });
});

describe("任务管理路由", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("通过 /jobs 渲染任务管理页并出现在主导航", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/health")) return jsonResponse(health);
      return jsonResponse({ items: [], total: 0, next_offset: null });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/jobs"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "任务管理" })).toBeInTheDocument();
    expect(await screen.findByText("尚无任务")).toBeInTheDocument();
  });
});
