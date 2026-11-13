import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import type {
  ConcurrencyCheck,
  DraftSummary,
  Health,
  HostResources,
  Job,
} from "../lib/api";
import { ExperimentsPage } from "./ExperimentsPage";

const GIB = 1024 ** 3;
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

function submitCalls() {
  return fetchCalls().filter(
    (call) => call.url.endsWith("/api/experiments") && call.init.method === "POST",
  );
}

function startCalls() {
  return fetchCalls().filter((call) => call.url.endsWith("/api/experiments/start"));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

const draftA: DraftSummary = {
  id: "draft-alpha",
  name: "高压逼抢",
  source: {},
  created_at: "2026-11-13T10:00:00+00:00",
  updated_at: "2026-11-13T10:00:00+00:00",
};

const draftB: DraftSummary = {
  id: "draft-beta",
  name: "低位防守",
  source: {},
  created_at: "2026-11-13T10:00:00+00:00",
  updated_at: "2026-11-13T10:00:00+00:00",
};

const draftC: DraftSummary = {
  id: "draft-gamma",
  name: "",
  source: {},
  created_at: "2026-11-13T10:00:00+00:00",
  updated_at: "2026-11-13T10:00:00+00:00",
};

const hostResources: HostResources = {
  cpu_count: 8,
  available_memory_bytes: 16 * GIB,
  free_disk_bytes: 120 * GIB,
  recommended_workers: 6,
};

const allowedCheck: ConcurrencyCheck = {
  allowed: true,
  code: null,
  recommended_workers: 6,
  warnings: [],
  memory_required_bytes: 4 * GIB,
  disk_required_bytes: 10 * GIB,
};

const blockedCheck: ConcurrencyCheck = {
  allowed: false,
  code: "insufficient_memory",
  recommended_workers: 2,
  warnings: ["可用内存不足，建议并行数不超过 2"],
  memory_required_bytes: 64 * GIB,
  disk_required_bytes: 10 * GIB,
};

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-123",
    kind: "experiment",
    status: "queued",
    name: "种子扫描",
    config: {},
    summary: {},
    workers: 6,
    total: 2,
    completed: 0,
    created_at: "2026-11-13T10:00:00+00:00",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

type ScenarioOptions = {
  drafts?: DraftSummary[];
  resources?: () => Response;
  check?: (url: string) => Response;
  submit?: (body: unknown) => Response | Promise<Response>;
  start?: () => Response;
};

function stubScenario(options: ScenarioOptions = {}) {
  const drafts = options.drafts ?? [draftA, draftB, draftC];
  const resources = options.resources ?? (() => jsonResponse(hostResources));
  const check = options.check ?? (() => jsonResponse(allowedCheck));
  const submit =
    options.submit ?? (() => jsonResponse(makeJob(), 201));
  const start =
    options.start ?? (() => jsonResponse({ job: makeJob({ status: "running" }) }));
  stubFetch((url, init) => {
    if (url.endsWith("/api/drafts")) {
      return jsonResponse({ items: drafts, total: drafts.length, next_offset: null });
    }
    if (url.endsWith("/api/system/resources")) return resources();
    if (url.includes("/api/concurrency/check")) return check(url);
    if (url.endsWith("/api/experiments/start")) return start();
    if (url.endsWith("/api/experiments") && init.method === "POST") {
      return submit(JSON.parse(String(init.body)));
    }
    throw new Error("未预期的请求：" + url);
  });
}

function renderExperimentsPage(activeConnection: typeof connection | null = connection) {
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
        <MemoryRouter>
          <ExperimentsPage />
        </MemoryRouter>
      </AppContext.Provider>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

function submitButton() {
  return screen.getByRole("button", { name: "提交实验" });
}

async function waitForFormReady() {
  await waitFor(() => expect(screen.getByLabelText("并行数")).toHaveValue(6));
  await waitFor(() => expect(submitButton()).toBeEnabled());
}

function chooseDraftAndSeeds(seeds: string, draftId = "draft-alpha") {
  fireEvent.change(screen.getByLabelText("草案"), { target: { value: draftId } });
  fireEvent.change(screen.getByLabelText("种子"), { target: { value: seeds } });
}

describe("ExperimentsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载草案与资源后填充并行数与资源摘要", async () => {
    stubScenario();
    renderExperimentsPage();

    await waitFor(() => expect(screen.getByLabelText("并行数")).toHaveValue(6));

    const region = screen.getByRole("region", { name: "主机资源" });
    expect(within(region).getByText("8")).toBeInTheDocument();
    expect(within(region).getByText("16.0 GiB")).toBeInTheDocument();
    expect(within(region).getByText("120.0 GiB")).toBeInTheDocument();

    await waitFor(() => expect(callsTo("/api/concurrency/check")).toHaveLength(1));
    const [checkCall] = callsTo("/api/concurrency/check");
    expect(checkCall.url).toBe(
      "http://127.0.0.1:43210/api/concurrency/check?workers=6&cpu_count=8&available_memory_bytes=17179869184&free_disk_bytes=128849018880&allow_oversubscription=false",
    );
  });

  it("手动设置的并行数在资源重新解析后保持不变", async () => {
    let resourceCalls = 0;
    const refreshedResources: HostResources = {
      ...hostResources,
      available_memory_bytes: 32 * GIB,
      recommended_workers: 2,
    };
    stubScenario({
      resources: () => {
        resourceCalls += 1;
        return jsonResponse(resourceCalls === 1 ? hostResources : refreshedResources);
      },
    });
    const { client } = renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "3" } });
    expect(screen.getByLabelText("并行数")).toHaveValue(3);

    await client.invalidateQueries({ queryKey: ["experiments-resources", connection.url] });

    const region = screen.getByRole("region", { name: "主机资源" });
    expect(await within(region).findByText("32.0 GiB")).toBeInTheDocument();
    expect(resourceCalls).toBe(2);
    expect(screen.getByLabelText("并行数")).toHaveValue(3);
  });

  it("修改并行数会重新触发资源预检", async () => {
    const checkSpy = vi.fn((_url: string) => jsonResponse(allowedCheck));
    stubScenario({ check: checkSpy });
    renderExperimentsPage();
    await waitForFormReady();

    expect(checkSpy).toHaveBeenCalledTimes(1);
    expect(checkSpy.mock.calls[0]?.[0]).toContain("workers=6");

    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "3" } });

    await waitFor(() => expect(checkSpy).toHaveBeenCalledTimes(2));
    expect(checkSpy.mock.calls[1]?.[0]).toContain("workers=3");
  });

  it("主机资源数值变化会重新触发资源预检", async () => {
    let resourceCalls = 0;
    const changedResources: HostResources = {
      cpu_count: 16,
      available_memory_bytes: 32 * GIB,
      free_disk_bytes: 200 * GIB,
      recommended_workers: 6,
    };
    const checkSpy = vi.fn((_url: string) => jsonResponse(allowedCheck));
    stubScenario({
      resources: () => {
        resourceCalls += 1;
        return jsonResponse(resourceCalls === 1 ? hostResources : changedResources);
      },
      check: checkSpy,
    });
    const { client } = renderExperimentsPage();
    await waitForFormReady();

    expect(checkSpy).toHaveBeenCalledTimes(1);

    await client.invalidateQueries({ queryKey: ["experiments-resources", connection.url] });

    await waitFor(() => expect(checkSpy).toHaveBeenCalledTimes(2));
    expect(checkSpy.mock.calls[1]?.[0]).toContain("cpu_count=16");
    expect(checkSpy.mock.calls[1]?.[0]).toContain("available_memory_bytes=34359738368");
  });

  it("仅空闲磁盘变化时重新触发资源预检", async () => {
    let resourceCalls = 0;
    const moreDisk: HostResources = { ...hostResources, free_disk_bytes: 200 * GIB };
    const checkSpy = vi.fn((_url: string) => jsonResponse(allowedCheck));
    stubScenario({
      resources: () => {
        resourceCalls += 1;
        return jsonResponse(resourceCalls === 1 ? hostResources : moreDisk);
      },
      check: checkSpy,
    });
    const { client } = renderExperimentsPage();
    await waitForFormReady();

    expect(checkSpy).toHaveBeenCalledTimes(1);
    expect(checkSpy.mock.calls[0]?.[0]).toContain("free_disk_bytes=128849018880");

    await client.invalidateQueries({ queryKey: ["experiments-resources", connection.url] });

    await waitFor(() => expect(checkSpy).toHaveBeenCalledTimes(2));
    expect(checkSpy.mock.calls[1]?.[0]).toContain("free_disk_bytes=214748364800");
    expect(checkSpy.mock.calls[1]?.[0]).toContain("cpu_count=8");
    expect(checkSpy.mock.calls[1]?.[0]).toContain("available_memory_bytes=17179869184");

    const region = screen.getByRole("region", { name: "主机资源" });
    expect(await within(region).findByText("200.0 GiB")).toBeInTheDocument();
  });

  it.each([
    {
      label: "仅 CPU 数量变化",
      changed: { cpu_count: 16 } satisfies Partial<HostResources>,
      original: "cpu_count=8",
      expected: [
        "cpu_count=16",
        "available_memory_bytes=17179869184",
        "free_disk_bytes=128849018880",
      ],
    },
    {
      label: "仅可用内存变化",
      changed: { available_memory_bytes: 32 * GIB } satisfies Partial<HostResources>,
      original: "available_memory_bytes=17179869184",
      expected: [
        "cpu_count=8",
        "available_memory_bytes=34359738368",
        "free_disk_bytes=128849018880",
      ],
    },
  ])("$label时重新触发资源预检", async ({ changed, original, expected }) => {
    let resourceCalls = 0;
    const changedResources: HostResources = { ...hostResources, ...changed };
    const checkSpy = vi.fn((_url: string) => jsonResponse(allowedCheck));
    stubScenario({
      resources: () => {
        resourceCalls += 1;
        return jsonResponse(resourceCalls === 1 ? hostResources : changedResources);
      },
      check: checkSpy,
    });
    const { client } = renderExperimentsPage();
    await waitForFormReady();

    expect(checkSpy).toHaveBeenCalledTimes(1);
    expect(checkSpy.mock.calls[0]?.[0]).toContain(original);

    await client.invalidateQueries({ queryKey: ["experiments-resources", connection.url] });

    await waitFor(() => expect(checkSpy).toHaveBeenCalledTimes(2));
    const secondUrl = checkSpy.mock.calls[1]?.[0];
    expect(secondUrl).toContain(expected[0]);
    expect(secondUrl).toContain(expected[1]);
    expect(secondUrl).toContain(expected[2]);
  });

  it("草案选项展示名称与标识，空名回退到标识", async () => {
    stubScenario({ drafts: [draftA, draftB, draftC] });
    renderExperimentsPage();

    const select = screen.getByLabelText("草案");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));

    const labels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(labels).toEqual(["请选择草案", "高压逼抢 · draft-alpha", "低位防守 · draft-beta", "draft-gamma"]);
  });

  it("种子支持换行、空格与中英文逗号混用", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("种子"), {
      target: { value: "101\n202 303，404,505" },
    });

    expect(await screen.findByText("共 5 场")).toBeInTheDocument();
    expect(screen.queryByText(/必须为 0 到 4294967295 的整数/)).not.toBeInTheDocument();
  });

  it("重复种子报错且不静默去重", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "7 8 7" } });

    expect(await screen.findByText("种子 7 重复")).toBeInTheDocument();
    fireEvent.click(submitButton());
    expect(submitCalls()).toHaveLength(0);
  });

  it.each(["1.5", "-1", "4294967296", "abc"])("非法种子 %s 报错", async (token) => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("种子"), { target: { value: token } });

    expect(
      await screen.findByText(/必须为 0 到 4294967295 的整数/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("种子")).toHaveAttribute("aria-invalid", "true");
  });

  it("最大种子 4294967295 合法而 4294967296 非法", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    const seeds = screen.getByLabelText("种子");
    fireEvent.change(seeds, { target: { value: "4294967295" } });

    expect(await screen.findByText("共 1 场")).toBeInTheDocument();
    expect(screen.queryByText(/必须为 0 到 4294967295 的整数/)).not.toBeInTheDocument();

    fireEvent.change(seeds, { target: { value: "4294967296" } });

    expect(
      await screen.findByText("种子 4294967296 必须为 0 到 4294967295 的整数"),
    ).toBeInTheDocument();
    expect(seeds).toHaveAttribute("aria-invalid", "true");
  });

  it("种子为空时提交报错且不发请求", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("草案"), { target: { value: "draft-alpha" } });
    fireEvent.click(submitButton());

    expect(await screen.findByText("请填写至少一个种子")).toBeInTheDocument();
    expect(submitCalls()).toHaveLength(0);
  });

  it("设置基线草案后总场数翻倍", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("1 2 3");
    fireEvent.change(screen.getByLabelText("基线草案"), { target: { value: "draft-beta" } });

    expect(await screen.findByText("共 6 场")).toBeInTheDocument();
  });

  it("主草案切换到与基线相同的草案时清空基线", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("基线草案"), { target: { value: "draft-alpha" } });
    expect(screen.getByLabelText("基线草案")).toHaveValue("draft-alpha");

    fireEvent.change(screen.getByLabelText("草案"), { target: { value: "draft-alpha" } });
    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "1" } });

    expect(await screen.findByText("共 1 场")).toBeInTheDocument();
    expect(screen.getByLabelText("基线草案")).toHaveValue("");
  });

  it("总场数超过上限时报错并禁用提交", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds(
      Array.from({ length: 5001 }, (_, index) => String(index)).join(" "),
    );
    fireEvent.change(screen.getByLabelText("基线草案"), { target: { value: "draft-beta" } });

    expect(await screen.findByText(/总场数 10002 超过上限 10000/)).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("实验名称超过 100 个字符时禁用提交并报错", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("1");
    await waitFor(() => expect(submitButton()).toBeEnabled());

    const nameInput = screen.getByLabelText("实验名称");
    fireEvent.change(nameInput, { target: { value: "名".repeat(101) } });

    expect(await screen.findByText("实验名称最多 100 个字符")).toBeInTheDocument();
    expect(nameInput).toHaveAttribute("aria-invalid", "true");
    expect(submitButton()).toBeDisabled();

    fireEvent.change(nameInput, { target: { value: "名".repeat(100) } });

    expect(screen.queryByText("实验名称最多 100 个字符")).not.toBeInTheDocument();
    await waitFor(() => expect(submitButton()).toBeEnabled());
  });

  it("预检阻塞时禁用提交，允许超分配后恢复并传入提交体", async () => {
    let submitted: unknown = null;
    stubScenario({
      check: (url) =>
        jsonResponse(url.includes("allow_oversubscription=true") ? allowedCheck : blockedCheck),
      submit: (body) => {
        submitted = body;
        return jsonResponse(makeJob(), 201);
      },
    });
    renderExperimentsPage();

    const region = await screen.findByRole("region", { name: "资源预检" });
    await waitFor(() => expect(within(region).getByText("阻止提交")).toBeInTheDocument());
    expect(within(region).getByText("可用内存不足，建议并行数不超过 2")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();

    fireEvent.click(screen.getByLabelText("允许超分配"));

    await waitFor(() => expect(within(region).getByText("通过")).toBeInTheDocument());
    await waitFor(() => expect(submitButton()).toBeEnabled());
    expect(
      callsTo("/api/concurrency/check").some((call) =>
        call.url.includes("allow_oversubscription=true"),
      ),
    ).toBe(true);

    chooseDraftAndSeeds("21");
    fireEvent.click(submitButton());

    await waitFor(() => expect(submitted).not.toBeNull());
    expect(submitted).toMatchObject({ allow_oversubscription: true, seeds: [21] });
  });

  it("预检通过时仍展示警告", async () => {
    const allowedWithWarnings: ConcurrencyCheck = {
      ...allowedCheck,
      warnings: ["并行数高于推荐值，已按显式覆盖运行"],
    };
    stubScenario({ check: () => jsonResponse(allowedWithWarnings) });
    renderExperimentsPage();

    const region = await screen.findByRole("region", { name: "资源预检" });
    expect(await within(region).findByText("通过")).toBeInTheDocument();
    expect(
      within(region).getByText("并行数高于推荐值，已按显式覆盖运行"),
    ).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it("预检请求失败时展示错误并禁用提交", async () => {
    stubScenario({
      check: () =>
        jsonResponse({ error: { code: "engine_unavailable", message: "引擎不可用" } }, 503),
    });
    renderExperimentsPage();

    const region = await screen.findByRole("region", { name: "资源预检" });
    expect(await within(region).findByRole("alert")).toHaveTextContent("引擎不可用");
    expect(submitButton()).toBeDisabled();
  });

  it("资源探测失败时展示错误并可重试", async () => {
    let attempts = 0;
    stubScenario({
      resources: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse(
            { error: { code: "engine_unavailable", message: "资源探测失败" } },
            503,
          );
        }
        return jsonResponse(hostResources);
      },
    });
    renderExperimentsPage();

    const region = await screen.findByRole("region", { name: "主机资源" });
    expect(await within(region).findByRole("alert")).toHaveTextContent("资源探测失败");
    expect(submitButton()).toBeDisabled();

    fireEvent.click(within(region).getByRole("button", { name: "重试" }));

    expect(await within(region).findByText("16.0 GiB")).toBeInTheDocument();
    await waitFor(() => expect(submitButton()).toBeEnabled());
    expect(attempts).toBe(2);
  });

  it("错误与提示文本通过 aria-describedby 关联到输入控件", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    const nameInput = screen.getByLabelText("实验名称");
    fireEvent.change(nameInput, { target: { value: "名".repeat(101) } });
    expect(await screen.findByText("实验名称最多 100 个字符")).toHaveAttribute(
      "id",
      "experiment-name-error",
    );
    expect(nameInput).toHaveAttribute("aria-describedby", "experiment-name-error");

    const seedsInput = screen.getByLabelText("种子");
    fireEvent.change(seedsInput, { target: { value: "1 2" } });
    expect(screen.getByText("共 2 场")).toHaveAttribute("id", "experiment-seeds-hint");
    expect(seedsInput).toHaveAttribute("aria-describedby", "experiment-seeds-hint");

    fireEvent.change(seedsInput, { target: { value: "1 1" } });
    expect(await screen.findByText("种子 1 重复")).toHaveAttribute(
      "id",
      "experiment-seeds-error",
    );
    expect(seedsInput).toHaveAttribute("aria-describedby", "experiment-seeds-error");

    const workersInput = screen.getByLabelText("并行数");
    fireEvent.change(workersInput, { target: { value: "0" } });
    expect(await screen.findByText("并行数需为 1 到 256 的整数")).toHaveAttribute(
      "id",
      "experiment-workers-error",
    );
    expect(workersInput).toHaveAttribute("aria-describedby", "experiment-workers-error");

    fireEvent.change(nameInput, { target: { value: "" } });
    fireEvent.change(workersInput, { target: { value: "6" } });
    await waitFor(() => expect(submitButton()).toBeEnabled());

    chooseDraftAndSeeds(
      Array.from({ length: 5001 }, (_, index) => String(index)).join(" "),
    );
    fireEvent.change(screen.getByLabelText("基线草案"), { target: { value: "draft-beta" } });

    expect(await screen.findByText(/总场数 10002 超过上限 10000/)).toHaveAttribute(
      "id",
      "experiment-total-error",
    );
    expect(seedsInput).toHaveAttribute(
      "aria-describedby",
      "experiment-seeds-hint experiment-total-error",
    );
  });

  it("草案选择框仅在缺少草案时关联错误说明", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    const draftSelect = screen.getByLabelText("草案");
    expect(draftSelect).toHaveAttribute("aria-invalid", "false");
    expect(draftSelect).not.toHaveAttribute("aria-describedby");

    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "1" } });
    fireEvent.click(submitButton());

    expect(screen.getByText("请选择草案", { selector: ".field-error" })).toHaveAttribute(
      "id",
      "experiment-draft-error",
    );
    expect(draftSelect).toHaveAttribute("aria-describedby", "experiment-draft-error");
    expect(draftSelect).toHaveAttribute("aria-invalid", "true");
    expect(submitCalls()).toHaveLength(0);

    fireEvent.change(draftSelect, { target: { value: "draft-alpha" } });

    expect(
      screen.queryByText("请选择草案", { selector: ".field-error" }),
    ).not.toBeInTheDocument();
    expect(draftSelect).not.toHaveAttribute("aria-describedby");
    expect(draftSelect).toHaveAttribute("aria-invalid", "false");
  });

  it("草案为空时展示空态并禁用提交", async () => {
    stubScenario({ drafts: [] });
    renderExperimentsPage();

    expect(await screen.findByText("尚无草案")).toBeInTheDocument();
    expect(screen.getByText("先到战术板保存草案，再提交实验。")).toBeInTheDocument();
    expect(screen.getByLabelText("草案")).toBeDisabled();
    expect(submitButton()).toBeDisabled();
  });

  it("允许超分配复选框不嵌套在字段容器内", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    const checkbox = screen.getByLabelText("允许超分配");
    expect(checkbox.closest(".field")).toBeNull();
    expect(checkbox.parentElement).toHaveClass("field-inline");
  });

  it("提交实验发送完整请求并展示结果区", async () => {
    let submitted: unknown = null;
    const job = makeJob();
    stubScenario({
      submit: (body) => {
        submitted = body;
        return jsonResponse(job, 201);
      },
    });
    const { client } = renderExperimentsPage();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());

    await waitFor(() => expect(submitted).not.toBeNull());
    const [call] = submitCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/experiments");
    expect(call.init.method).toBe("POST");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
    expect(submitted).toEqual({
      name: null,
      seeds: [11, 12],
      draft_id: "draft-alpha",
      baseline_draft_id: null,
      workers: 6,
      cpu_count: 8,
      available_memory_bytes: 16 * GIB,
      free_disk_bytes: 120 * GIB,
      allow_oversubscription: false,
    });

    const result = await screen.findByRole("region", { name: "实验任务" });
    expect(within(result).getByText("种子扫描")).toBeInTheDocument();
    expect(within(result).getByText("job-123")).toBeInTheDocument();
    expect(within(result).getByText("排队中")).toBeInTheDocument();
    expect(within(result).getByText("总场数 2")).toBeInTheDocument();
    expect(within(result).getByRole("button", { name: "启动实验" })).toBeInTheDocument();
    expect(within(result).getByRole("link", { name: "查看任务" })).toHaveAttribute(
      "href",
      "/jobs",
    );
    expect(await screen.findByText("实验已提交")).toBeInTheDocument();
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs"] }),
    );
  });

  it("提交失败时展示中文错误并保留表单", async () => {
    stubScenario({
      submit: () =>
        jsonResponse({ error: { code: "validation_failed", message: "草案不存在" } }, 400),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("31");
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("草案不存在");
    expect(screen.getByLabelText("草案")).toHaveValue("draft-alpha");
    expect(screen.getByLabelText("种子")).toHaveValue("31");
  });

  it("启动实验展示运行状态与结果链接", async () => {
    stubScenario({
      start: () => jsonResponse({ job: makeJob({ id: "job-456", status: "running" }) }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(screen.getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(within(started).getByText("运行中")).toBeInTheDocument();
    expect(within(started).getByRole("link", { name: "查看结果" })).toHaveAttribute(
      "href",
      "/results",
    );
    const [startCall] = startCalls();
    expect(startCall.url).toBe("http://127.0.0.1:43210/api/experiments/start");
    expect(startCall.init.method).toBe("POST");
  });

  it("启动队列中更早的任务时展示其名称与总场数", async () => {
    stubScenario({
      start: () =>
        jsonResponse({
          job: makeJob({ id: "job-older", name: "队列早期任务", total: 7, status: "running" }),
        }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const submitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(submitted).getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(within(started).getByRole("heading", { name: "已启动任务" })).toBeInTheDocument();
    expect(within(started).getByText("队列早期任务")).toBeInTheDocument();
    expect(within(started).getByText("job-older")).toBeInTheDocument();
    expect(within(started).getByText("总场数 7")).toBeInTheDocument();
    expect(within(started).getByText("运行中")).toBeInTheDocument();
    expect(within(started).getByText(/更早的任务/)).toBeInTheDocument();

    expect(within(submitted).getByText("排队中")).toBeInTheDocument();
    expect(within(submitted).getByText("总场数 2")).toBeInTheDocument();
  });

  it("启动更早任务时锁定完整提示文案", async () => {
    stubScenario({
      start: () =>
        jsonResponse({
          job: makeJob({ id: "job-earlier", name: "队列早期任务", total: 7, status: "running" }),
        }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const submitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(submitted).getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(
      within(started).getByText("已启动队列中更早的任务，而不是本次提交的任务"),
    ).toHaveClass("experiments-start-note");
  });

  it("启动结果名称缺失时回退到任务标识", async () => {
    stubScenario({
      start: () => jsonResponse({ job: makeJob({ id: "job-123", name: null, status: "running" }) }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const submitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(submitted).getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(
      within(started).getByText("job-123", { selector: ".experiments-result-name" }),
    ).toBeInTheDocument();
    expect(
      within(started).getByText("job-123", { selector: ".experiments-result-id" }),
    ).toBeInTheDocument();
    expect(within(started).queryByText(/更早的任务/)).not.toBeInTheDocument();
  });

  it("启动任务与本次提交一致时不提示更早任务", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const submitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(submitted).getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(within(started).getByText("已启动任务")).toBeInTheDocument();
    expect(within(started).queryByText(/更早的任务/)).not.toBeInTheDocument();
  });

  it("启动结果区与实验任务区为同级且不互相嵌套", async () => {
    stubScenario({
      start: () => jsonResponse({ job: makeJob({ id: "job-456", status: "running" }) }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const submitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(submitted).getByRole("button", { name: "启动实验" }));

    const started = await screen.findByRole("region", { name: "启动结果" });

    expect(submitted.contains(started)).toBe(false);
    expect(started.contains(submitted)).toBe(false);
    expect(within(submitted).queryByRole("region", { name: "启动结果" })).not.toBeInTheDocument();
    expect(started.parentElement).not.toBeNull();
    expect(started.parentElement).toBe(submitted.parentElement);
    expect(started.previousElementSibling).toBe(submitted);
  });

  it("启动时没有待运行任务展示通知", async () => {
    stubScenario({ start: () => noContentResponse() });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(screen.getByRole("button", { name: "启动实验" }));

    expect(await screen.findByText("没有待运行任务")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "启动结果" })).not.toBeInTheDocument();
  });

  it("启动失败展示错误并可重试", async () => {
    let attempts = 0;
    stubScenario({
      start: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse(
            { error: { code: "engine_unavailable", message: "引擎不可用" } },
            503,
          );
        }
        return jsonResponse({ job: makeJob({ status: "running" }) });
      },
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const result = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(result).getByRole("button", { name: "启动实验" }));

    expect(await within(result).findByRole("alert")).toHaveTextContent("引擎不可用");

    fireEvent.click(within(result).getByRole("button", { name: "启动实验" }));

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    expect(startCalls()).toHaveLength(2);
  });

  it("提交进行中禁止重复提交", async () => {
    const pending = deferred<Response>();
    let attempts = 0;
    stubScenario({
      submit: () => {
        attempts += 1;
        return pending.promise;
      },
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());

    await waitFor(() => expect(attempts).toBe(1));
    expect(submitButton()).toBeDisabled();
    expect(submitButton()).toHaveAttribute("aria-busy", "true");

    fireEvent.click(submitButton());
    expect(attempts).toBe(1);

    pending.resolve(jsonResponse(makeJob(), 201));
    expect(await screen.findByRole("region", { name: "实验任务" })).toBeInTheDocument();
  });

  it("再次提交后结果区被新结果替换", async () => {
    const bodies: unknown[] = [];
    let attempts = 0;
    stubScenario({
      submit: (body) => {
        bodies.push(body);
        attempts += 1;
        const job =
          attempts === 1
            ? makeJob({ id: "job-one", name: "第一组" })
            : makeJob({ id: "job-two", name: "第二组" });
        return jsonResponse(job, 201);
      },
    });
    renderExperimentsPage();
    await waitForFormReady();

    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "第一组" } });
    chooseDraftAndSeeds("1");
    fireEvent.click(submitButton());

    expect(await screen.findByText("第一组")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "第二组" } });
    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "2" } });
    fireEvent.click(submitButton());

    expect(await screen.findByText("第二组")).toBeInTheDocument();
    expect(screen.queryByText("第一组")).not.toBeInTheDocument();
    expect(bodies[0]).toMatchObject({ name: "第一组", seeds: [1] });
    expect(bodies[1]).toMatchObject({ name: "第二组", seeds: [2] });
  });

  it("重新提交实验后清空上次启动结果", async () => {
    let attempts = 0;
    stubScenario({
      submit: () => {
        attempts += 1;
        return jsonResponse(
          makeJob({
            id: attempts === 1 ? "job-first" : "job-second",
            name: attempts === 1 ? "第一轮" : "第二轮",
          }),
          201,
        );
      },
      start: () => jsonResponse({ job: makeJob({ id: "job-first", status: "running" }) }),
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("11 12");
    fireEvent.click(submitButton());
    const firstSubmitted = await screen.findByRole("region", { name: "实验任务" });

    fireEvent.click(within(firstSubmitted).getByRole("button", { name: "启动实验" }));
    const started = await screen.findByRole("region", { name: "启动结果" });
    expect(within(started).getByText("运行中")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "21" } });
    fireEvent.click(submitButton());

    expect(await screen.findByText("job-second")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "启动结果" })).not.toBeInTheDocument();
  });

  it("基线草案选择影响提交体", async () => {
    const bodies: any[] = [];
    stubScenario({
      submit: (body) => {
        bodies.push(body);
        return jsonResponse(makeJob(), 201);
      },
    });
    renderExperimentsPage();
    await waitForFormReady();

    chooseDraftAndSeeds("1 2");
    fireEvent.click(submitButton());
    await waitFor(() => expect(bodies).toHaveLength(1));

    fireEvent.change(screen.getByLabelText("基线草案"), { target: { value: "draft-beta" } });
    fireEvent.click(submitButton());
    await waitFor(() => expect(bodies).toHaveLength(2));

    expect(bodies[0].baseline_draft_id).toBeNull();
    expect(bodies[1].baseline_draft_id).toBe("draft-beta");
    expect(bodies[1].seeds).toEqual([1, 2]);
  });

  it("通过 /experiments 渲染实验页并出现在主导航", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/health")) return jsonResponse(health);
      if (url.endsWith("/api/drafts")) {
        return jsonResponse({ items: [draftA], total: 1, next_offset: null });
      }
      if (url.endsWith("/api/system/resources")) return jsonResponse(hostResources);
      if (url.includes("/api/concurrency/check")) return jsonResponse(allowedCheck);
      throw new Error("未预期的请求：" + url);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/experiments"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "实验", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "实验" })).toHaveAttribute("href", "/experiments");
    expect(await screen.findByRole("heading", { name: "实验", level: 2 })).toBeInTheDocument();
    expect(await screen.findByLabelText("草案")).toBeInTheDocument();
  });
});
