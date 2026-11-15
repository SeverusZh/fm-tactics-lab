import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext } from "../app-context";
import type {
  ConcurrencyCheck,
  Draft,
  DraftSummary,
  ExperimentSubmitInput,
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
type EventStreamHandler = () => Response | Promise<Response>;

function openEventStream(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(": connected\n\n"));
    },
  });
  return new Response(stream);
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

function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: async () => {
      throw new Error("no content");
    },
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

const poolScenario = {
  schema: 4,
  teams: [],
  away_tactic_pool: {
    enabled: true,
    entries: [
      { name: "长传冲吊", weight: 1 },
      { name: "边路传中", weight: 1 },
      { name: "高位压迫", weight: 1 },
    ],
  },
};

function makeDraft(id: string): Draft {
  return {
    id,
    name: id === "draft-alpha" ? "高压逼抢" : "低位防守",
    source: {},
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    scenario: {},
  };
}

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
  draftsResponse?: () => Response;
  detail?: (draftId: string) => Response;
  resources?: () => Response;
  check?: (url: string) => Response;
  submit?: (body: ExperimentSubmitInput) => Response | Promise<Response>;
  start?: () => Response;
  events?: EventStreamHandler;
};

function stubScenario(options: ScenarioOptions = {}) {
  const drafts = options.drafts ?? [draftA, draftB, draftC];
  const draftsResponse = options.draftsResponse;
  const detail = options.detail ?? ((draftId: string) => jsonResponse(makeDraft(draftId)));
  const resources = options.resources ?? (() => jsonResponse(hostResources));
  const check = options.check ?? (() => jsonResponse(allowedCheck));
  const submit = options.submit ?? (() => jsonResponse(makeJob(), 201));
  const start =
    options.start ?? (() => jsonResponse({ job: makeJob({ status: "running" }) }));
  stubFetch((url, init) => {
    if (url.endsWith("/api/drafts")) {
      if (draftsResponse !== undefined) return draftsResponse();
      return jsonResponse({ items: drafts, total: drafts.length, next_offset: null });
    }
    if (url.includes("/api/drafts/")) {
      const draftId = decodeURIComponent(url.slice(url.indexOf("/api/drafts/") + 12));
      return detail(draftId);
    }
    if (url.endsWith("/api/system/resources")) return resources();
    if (url.includes("/api/concurrency/check")) return check(url);
    if (url.endsWith("/api/experiments/start")) return start();
    if (url.endsWith("/api/experiments") && init.method === "POST") {
      return submit(JSON.parse(String(init.body)) as ExperimentSubmitInput);
    }
    throw new Error("未预期的请求：" + url);
  }, options.events);
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
  return screen.getByRole("button", { name: /^开始实验/ });
}

async function waitForResources() {
  await waitFor(() => expect(screen.getByLabelText("CPU 核数")).toHaveValue(8));
  await waitFor(() => expect(screen.getByLabelText("并行数")).toHaveValue(6));
  await waitFor(() =>
    expect(screen.getByText("资源预检通过，推荐并行数 6")).toBeInTheDocument(),
  );
}

async function selectDraft(draftId = "draft-alpha") {
  fireEvent.change(screen.getByLabelText("草案"), { target: { value: draftId } });
  await waitFor(() =>
    expect(screen.getByText("固定对手（用于验证对特定打法的稳定性）")).toBeInTheDocument(),
  );
}

async function readyWithDraft() {
  stubScenario();
  renderExperimentsPage();
  await waitForResources();
  await selectDraft();
}

describe("ExperimentsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("按三段式顺序展示选择战术、对比与场数、资源与提交", () => {
    stubScenario();
    renderExperimentsPage();

    const draft = screen.getByRole("heading", { level: 3, name: "选择战术" });
    const scale = screen.getByRole("heading", { level: 3, name: "对比与场数" });
    const resources = screen.getByRole("heading", { level: 3, name: "资源与提交" });

    expect(draft).toHaveAttribute("id", "experiment-step-draft");
    expect(scale).toHaveAttribute("id", "experiment-step-scale");
    expect(resources).toHaveAttribute("id", "experiment-step-resources");

    const draftSection = draft.closest("section");
    const scaleSection = scale.closest("section");
    const resourcesSection = resources.closest("section");
    expect(draftSection).not.toBeNull();
    expect(scaleSection).not.toBeNull();
    expect(resourcesSection).not.toBeNull();
    expect(draftSection).toHaveAttribute("aria-labelledby", "experiment-step-draft");
    expect(scaleSection).toHaveAttribute("aria-labelledby", "experiment-step-scale");
    expect(resourcesSection).toHaveAttribute("aria-labelledby", "experiment-step-resources");

    expect(
      draft.compareDocumentPosition(scale) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      scale.compareDocumentPosition(resources) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("默认场数为 100 并实时展示总场数", () => {
    stubScenario();
    renderExperimentsPage();

    expect(screen.getByLabelText("场数")).toHaveValue(100);
    expect(screen.getByText("总场数 = 100 场")).toBeInTheDocument();
    expect(submitButton()).toHaveTextContent("开始实验（100 场）");
  });

  it("快捷按钮把场数切换为 50、100 和 200", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    fireEvent.click(screen.getByRole("button", { name: "50 场" }));
    expect(screen.getByText("总场数 = 50 场")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "100 场" }));
    expect(screen.getByText("总场数 = 100 场")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "200 场" }));
    expect(screen.getByText("总场数 = 200 场")).toBeInTheDocument();
    expect(submitButton()).toHaveTextContent("开始实验（200 场）");
  });

  it("选择基线草案后总场数按 A/B 对照翻倍", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("对比基线草案"), {
      target: { value: "draft-beta" },
    });

    expect(screen.getByText("总场数 = 100 × 2 = 200 场（A/B 对照）")).toBeInTheDocument();
  });

  it("草案选项展示名称与本地更新时间", async () => {
    stubScenario();
    renderExperimentsPage();

    const draftSelect = screen.getByLabelText("草案");
    const option = await within(draftSelect).findByRole("option", { name: /高压逼抢/ });
    expect(option.textContent).toMatch(/^高压逼抢 · 更新于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    const unnamed = await within(draftSelect).findByRole("option", {
      name: /draft-gamma/,
    });
    expect(unnamed.textContent).toMatch(/^draft-gamma · 更新于 /);
  });

  it("启用客队战术池的草案展示抽取说明", async () => {
    stubScenario({ detail: (draftId) => jsonResponse({ ...makeDraft(draftId), scenario: poolScenario }) });
    renderExperimentsPage();
    await waitForResources();

    fireEvent.change(screen.getByLabelText("草案"), { target: { value: "draft-alpha" } });

    expect(
      await screen.findByText("客队战术池：3 套客队战术，每个种子随机抽取（用于检验泛化）"),
    ).toBeInTheDocument();
  });

  it("未启用客队战术池时说明为固定对手", async () => {
    await readyWithDraft();

    expect(
      screen.getByText("固定对手（用于验证对特定打法的稳定性）"),
    ).toBeInTheDocument();
  });

  it("没有草案时提示前往战术板新建", async () => {
    stubScenario({ drafts: [] });
    renderExperimentsPage();

    const empty = await screen.findByText("还没有草案。");
    expect(empty).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往战术板新建" })).toHaveAttribute(
      "href",
      "/tactics",
    );
  });

  it("草案详情读取失败时展示后端信息并可重试", async () => {
    let detailCalls = 0;
    stubScenario({
      detail: (draftId) => {
        detailCalls += 1;
        if (detailCalls === 1) {
          return jsonResponse({ error: { message: "草案文件损坏", code: "internal_error" } }, 500);
        }
        return jsonResponse(makeDraft(draftId));
      },
    });
    renderExperimentsPage();
    await waitForResources();

    fireEvent.change(screen.getByLabelText("草案"), { target: { value: "draft-alpha" } });

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("草案文件损坏")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    expect(
      await screen.findByText("固定对手（用于验证对特定打法的稳定性）"),
    ).toBeInTheDocument();
    expect(detailCalls).toBe(2);
  });

  it("自动读取本机资源并预填 CPU、内存、磁盘与并行数", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    expect(screen.getByLabelText("CPU 核数")).toHaveValue(8);
    expect(screen.getByLabelText("可用内存（GiB）")).toHaveValue(16);
    expect(screen.getByLabelText("空闲磁盘（GiB）")).toHaveValue(120);
    expect(screen.getByLabelText("并行数")).toHaveValue(6);
    expect(screen.getByText("已自动读取本机资源，可手动修改。")).toBeInTheDocument();

    const checkCalls = callsTo("/api/concurrency/check");
    expect(checkCalls).toHaveLength(1);
    expect(checkCalls[0].url).toBe(
      "http://127.0.0.1:43210/api/concurrency/check?workers=6&cpu_count=8&available_memory_bytes=17179869184&free_disk_bytes=128849018880&allow_oversubscription=false",
    );
  });

  it("资源预检通过时展示推荐并行数并可一键采用", async () => {
    stubScenario({ check: () => jsonResponse({ ...allowedCheck, recommended_workers: 4 }) });
    renderExperimentsPage();

    expect(
      await screen.findByText("资源预检通过，推荐并行数 4"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "采用推荐并行数 4" }));

    expect(screen.getByLabelText("并行数")).toHaveValue(4);
  });

  it("资源预检未通过时禁用提交并给出原因", async () => {
    stubScenario({ check: () => jsonResponse(blockedCheck) });
    renderExperimentsPage();
    await waitFor(() => expect(screen.getByLabelText("并行数")).toHaveValue(6));
    await selectDraft();

    const reason = "资源预检未通过：可用内存不足，建议并行数不超过 2";
    expect((await screen.findAllByText(reason)).length).toBeGreaterThanOrEqual(2);
    expect(submitButton()).toBeDisabled();
  });

  it("固定种子包含非法字符时阻止提交并说明原因", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: "abc" } });

    expect(
      (await screen.findAllByText("种子 abc 必须为 0 到 4294967295 的整数"))[0],
    ).toBeInTheDocument();
    expect(screen.getByLabelText("场数")).toBeDisabled();
    expect(submitButton()).toBeDisabled();
  });

  it("固定种子超出上限时阻止提交", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("固定种子"), {
      target: { value: "4294967296" },
    });

    expect(
      (await screen.findAllByText("种子 4294967296 必须为 0 到 4294967295 的整数"))[0],
    ).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("固定种子重复时阻止提交", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: "5,5" } });

    expect((await screen.findAllByText("种子 5 重复"))[0]).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("固定种子数量超过 10000 时阻止提交并说明限制", async () => {
    await readyWithDraft();

    const seeds = Array.from({ length: 10001 }, (_, index) => String(index)).join(",");
    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: seeds } });

    expect((await screen.findAllByText("固定种子最多 10000 个"))[0]).toBeInTheDocument();
    expect(screen.getByLabelText("场数")).toBeDisabled();
    expect(submitButton()).toBeDisabled();
  });

  it("固定种子数量达到上限 10000 时仍可提交", async () => {
    await readyWithDraft();

    const seeds = Array.from({ length: 10000 }, (_, index) => String(index)).join(",");
    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: seeds } });

    expect(screen.getByText("按固定种子共 10000 场")).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it("固定种子生效后场数输入禁用并按种子数量计算总场数", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: "5,9,13" } });

    expect(screen.getByText("按固定种子共 3 场")).toBeInTheDocument();
    expect(screen.getByLabelText("场数")).toBeDisabled();
    expect(submitButton()).toHaveTextContent("开始实验（3 场）");
    expect(submitButton()).toBeEnabled();
  });

  it("提交实验时先提交任务再启动，并展示成功提示与任务链接", async () => {
    stubScenario({ start: () => jsonResponse({ job: makeJob({ status: "running", total: 100 }) }) });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看任务" })).toHaveAttribute("href", "/jobs");

    const calls = fetchCalls();
    const submitIndex = calls.findIndex(
      (call) => call.url.endsWith("/api/experiments") && call.init.method === "POST",
    );
    const startIndex = calls.findIndex((call) =>
      call.url.endsWith("/api/experiments/start"),
    );
    expect(submitIndex).toBeGreaterThanOrEqual(0);
    expect(startIndex).toBeGreaterThan(submitIndex);

    const body = JSON.parse(String(submitCalls()[0].init.body)) as ExperimentSubmitInput;
    expect(body.draft_id).toBe("draft-alpha");
    expect(body.baseline_draft_id).toBeNull();
    expect(body.name).toBeNull();
    expect(body.workers).toBe(6);
    expect(body.cpu_count).toBe(8);
    expect(body.available_memory_bytes).toBe(16 * GIB);
    expect(body.free_disk_bytes).toBe(120 * GIB);
    expect(body.allow_oversubscription).toBe(false);
    expect(body.seeds).toHaveLength(100);
    for (const seed of body.seeds) {
      expect(Number.isInteger(seed)).toBe(true);
      expect(seed).toBeGreaterThanOrEqual(0);
      expect(seed).toBeLessThanOrEqual(4294967295);
    }
  });

  it("提交请求未返回前不会启动任务", async () => {
    const pending = deferred<Response>();
    stubScenario({ submit: () => pending.promise });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    await waitFor(() => expect(submitCalls()).toHaveLength(1));
    expect(startCalls()).toHaveLength(0);
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText("正在提交实验…")).toBeInTheDocument();

    pending.resolve(jsonResponse(makeJob(), 201));
    await waitFor(() => expect(startCalls()).toHaveLength(1));
  });

  it("提交返回引擎校验错误时引导前往设置页", async () => {
    stubScenario({
      submit: () =>
        jsonResponse(
          {
            error: {
              message: "FM27 引擎不可用：未配置游戏根目录",
              code: "validation_failed",
            },
          },
          400,
        ),
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("FM27 引擎不可用：未配置游戏根目录")).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "前往设置页配置引擎" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(startCalls()).toHaveLength(0);
  });

  it("启动返回引擎不可用时引导前往设置页", async () => {
    stubScenario({
      start: () =>
        jsonResponse(
          { error: { message: "引擎不可用，请先完成配置", code: "engine_unavailable" } },
          503,
        ),
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("引擎不可用，请先完成配置")).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "前往设置页配置引擎" })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("没有待运行任务时说明任务为空", async () => {
    stubScenario({ start: () => noContentResponse() });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    expect(await screen.findByText("没有待运行任务")).toBeInTheDocument();
  });

  it("资源阻塞错误提示降低并行数或减少场数", async () => {
    stubScenario({
      submit: () =>
        jsonResponse(
          { error: { message: "可用内存不足", code: "insufficient_memory" } },
          409,
        ),
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("可用内存不足")).toBeInTheDocument();
    expect(
      within(alert).getByText("请降低并行数或减少场数后重试。"),
    ).toBeInTheDocument();
  });

  it("普通提交失败后可以重试", async () => {
    let attempts = 0;
    stubScenario({
      submit: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ error: { message: "内部错误", code: "internal_error" } }, 500);
        }
        return jsonResponse(makeJob(), 201);
      },
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("内部错误")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
    expect(submitCalls()).toHaveLength(2);
  });

  it("未选择草案时禁用提交并提示选择草案", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    expect(screen.getByText("请先选择草案")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("实验名称与超分配选项会进入请求体", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.change(screen.getByLabelText("实验名称（可选）"), {
      target: { value: "晚间扫描" },
    });
    fireEvent.click(screen.getByLabelText("允许超分配"));
    await waitFor(() =>
      expect(screen.getByText("资源预检通过，推荐并行数 6")).toBeInTheDocument(),
    );
    fireEvent.click(submitButton());

    await waitFor(() => expect(submitCalls()).toHaveLength(1));
    const body = JSON.parse(String(submitCalls()[0].init.body)) as ExperimentSubmitInput;
    expect(body.name).toBe("晚间扫描");
    expect(body.allow_oversubscription).toBe(true);
    expect(
      callsTo("/api/concurrency/check").some((call) =>
        call.url.includes("allow_oversubscription=true"),
      ),
    ).toBe(true);
  });

  it("固定种子与基线草案一起进入请求体", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();
    fireEvent.change(screen.getByLabelText("对比基线草案"), {
      target: { value: "draft-beta" },
    });
    fireEvent.change(screen.getByLabelText("固定种子"), { target: { value: "5,9,13" } });

    expect(screen.getByText("按固定种子共 6 场（A/B 对照）")).toBeInTheDocument();
    fireEvent.click(submitButton());

    await waitFor(() => expect(submitCalls()).toHaveLength(1));
    const body = JSON.parse(String(submitCalls()[0].init.body)) as ExperimentSubmitInput;
    expect(body.seeds).toEqual([5, 9, 13]);
    expect(body.baseline_draft_id).toBe("draft-beta");
  });

  it("场数非法时禁用提交并说明范围", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    fireEvent.change(screen.getByLabelText("场数"), { target: { value: "0" } });

    expect(screen.getAllByText("场数需为 1 到 10000 的整数")).toHaveLength(2);
    expect(screen.getByText("总场数 = —")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("A/B 对照总场数超过上限时禁用提交", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("场数"), { target: { value: "6000" } });
    fireEvent.change(screen.getByLabelText("对比基线草案"), {
      target: { value: "draft-beta" },
    });

    expect(screen.getAllByText("总场数 12000 超过上限 10000")[0]).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("并行数非法时禁用提交并说明范围", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "0" } });

    expect(screen.getAllByText("并行数需为 1 到 256 的整数")).toHaveLength(2);
    expect(submitButton()).toBeDisabled();
  });

  it("切换草案时清除与其相同的基线草案", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("对比基线草案"), {
      target: { value: "draft-beta" },
    });
    expect(screen.getByLabelText("对比基线草案")).toHaveValue("draft-beta");

    fireEvent.change(screen.getByLabelText("草案"), { target: { value: "draft-beta" } });

    expect(screen.getByLabelText("对比基线草案")).toHaveValue("");

    await waitFor(() => expect(submitButton()).toBeEnabled());
    fireEvent.click(submitButton());
    await waitFor(() => expect(submitCalls()).toHaveLength(1));
    const body = JSON.parse(String(submitCalls()[0].init.body)) as ExperimentSubmitInput;
    expect(body.draft_id).toBe("draft-beta");
    expect(body.baseline_draft_id).toBeNull();
  });

  it("实验名称超过 100 个字符时禁用提交并说明限制", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("实验名称（可选）"), {
      target: { value: "名".repeat(101) },
    });

    expect(screen.getByText("实验名称最多 100 个字符")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("CPU 核数超过 256 时仍可提交并进入请求体", async () => {
    await readyWithDraft();

    fireEvent.change(screen.getByLabelText("CPU 核数"), { target: { value: "512" } });
    await waitFor(() =>
      expect(
        callsTo("/api/concurrency/check").some((call) => call.url.includes("cpu_count=512")),
      ).toBe(true),
    );
    await waitFor(() => expect(submitButton()).toBeEnabled());
    expect(screen.queryByText("CPU 核数需为大于等于 1 的整数")).toBeNull();

    fireEvent.click(submitButton());
    await waitFor(() => expect(submitCalls()).toHaveLength(1));
    const body = JSON.parse(String(submitCalls()[0].init.body)) as ExperimentSubmitInput;
    expect(body.cpu_count).toBe(512);
  });

  it("资源预检自带失败后缀时不会重复展示", async () => {
    stubScenario({
      check: () =>
        jsonResponse({ ...blockedCheck, warnings: ["可用内存不足，资源预检未通过"] }),
    });
    renderExperimentsPage();
    await waitFor(() => expect(screen.getByLabelText("并行数")).toHaveValue(6));
    await selectDraft();

    expect((await screen.findAllByText("资源预检未通过：可用内存不足")).length).toBeGreaterThanOrEqual(
      2,
    );
    expect(screen.queryByText(/资源预检未通过：可用内存不足，资源预检未通过/)).toBeNull();
  });

  it("启动阶段普通失败后可重试启动且不会重复提交任务", async () => {
    let attempts = 0;
    stubScenario({
      start: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ error: { message: "启动失败", code: "internal_error" } }, 500);
        }
        return jsonResponse({ job: makeJob({ status: "running" }) });
      },
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("启动失败")).toBeInTheDocument();
    expect(screen.getByText("实验已提交，请先处理下方提示。")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();

    fireEvent.click(within(alert).getByRole("button", { name: "重试启动" }));

    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
    expect(submitCalls()).toHaveLength(1);
    expect(startCalls()).toHaveLength(2);
  });

  it("启动遇到已有任务运行时引导到任务页并可重新填写", async () => {
    let attempts = 0;
    stubScenario({
      start: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse(
            {
              error: {
                message: "已有任务在运行",
                code: "invalid_transition",
                retriable: false,
              },
            },
            409,
          );
        }
        return jsonResponse({ job: makeJob({ status: "running" }) });
      },
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("已有任务在运行")).toBeInTheDocument();
    expect(
      within(alert).getByText("已有任务在运行，请等待其结束后再试。"),
    ).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "查看任务" })).toHaveAttribute(
      "href",
      "/jobs",
    );
    expect(within(alert).queryByRole("button", { name: "重试启动" })).toBeNull();
    expect(screen.getByText("实验已提交，请先处理下方提示。")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(submitCalls()).toHaveLength(1);
    expect(startCalls()).toHaveLength(1);

    fireEvent.click(within(alert).getByRole("button", { name: "重新填写" }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("实验已提交，请先处理下方提示。")).toBeNull();
    expect(screen.getByLabelText("草案")).toBeEnabled();
    await waitFor(() => expect(submitButton()).toBeEnabled());

    fireEvent.click(submitButton());

    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
    expect(submitCalls()).toHaveLength(2);
    expect(startCalls()).toHaveLength(2);
  });

  it("提交返回不可重试的校验失败时提示修正输入", async () => {
    stubScenario({
      submit: () =>
        jsonResponse(
          {
            error: {
              message: "输入校验失败",
              code: "validation_failed",
              retriable: false,
            },
          },
          400,
        ),
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("输入校验失败")).toBeInTheDocument();
    expect(within(alert).getByText("请修正输入后重新提交。")).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
    expect(submitCalls()).toHaveLength(1);

    fireEvent.click(within(alert).getByRole("button", { name: "重新填写" }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(submitButton()).toBeEnabled();
    expect(submitCalls()).toHaveLength(1);
  });

  it("启动成功后锁定表单并阻止重复提交", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());
    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();

    expect(screen.getByText("实验已启动，等待运行结束后才能再次提交。")).toBeInTheDocument();
    expect(screen.getByLabelText("草案")).toBeDisabled();
    expect(screen.getByLabelText("场数")).toBeDisabled();
    expect(screen.getByLabelText("实验名称（可选）")).toBeDisabled();
    expect(submitButton()).toBeDisabled();

    fireEvent.submit(screen.getByRole("form", { name: "实验提交" }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(submitCalls()).toHaveLength(1);
    expect(startCalls()).toHaveLength(1);
  });

  it("点击重新填写后可再次提交实验", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());
    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新填写" }));

    expect(screen.queryByText("实验已启动，等待运行结束后才能再次提交。")).toBeNull();
    await waitFor(() => expect(submitButton()).toBeEnabled());

    fireEvent.click(submitButton());
    await waitFor(() => expect(submitCalls()).toHaveLength(2));
    expect(startCalls()).toHaveLength(2);
  });

  it("sidecar 未连接时展示空状态而不渲染表单", () => {
    stubScenario();
    renderExperimentsPage(null);

    expect(screen.getByText("sidecar 未连接")).toBeInTheDocument();
    expect(screen.getByText("连接 sidecar 后可以开始实验。")).toBeInTheDocument();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("草案列表读取失败时可重试并恢复", async () => {
    let attempts = 0;
    stubScenario({
      draftsResponse: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse(
            { error: { message: "草案服务不可用", code: "internal_error" } },
            500,
          );
        }
        return jsonResponse({ items: [draftA, draftB], total: 2, next_offset: null });
      },
    });
    renderExperimentsPage();
    await waitForResources();

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("草案服务不可用")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    expect(
      await within(screen.getByLabelText("草案")).findByRole("option", { name: /高压逼抢/ }),
    ).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("本机资源读取失败时可重试并预填", async () => {
    let attempts = 0;
    stubScenario({
      resources: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ error: { message: "资源读取失败", code: "internal_error" } }, 500);
        }
        return jsonResponse(hostResources);
      },
    });
    renderExperimentsPage();

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("资源读取失败")).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));

    await waitForResources();
    expect(attempts).toBe(2);
  });

  it("磁盘不足时提示空闲磁盘不足", async () => {
    stubScenario({
      submit: () =>
        jsonResponse(
          { error: { message: "空闲磁盘不足", code: "insufficient_disk", retriable: true } },
          409,
        ),
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("空闲磁盘不足")).toBeInTheDocument();
    expect(within(alert).getByText("请降低并行数或减少场数后重试。")).toBeInTheDocument();
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("提交失败后重试使用当前表单值而不是旧快照", async () => {
    let attempts = 0;
    stubScenario({
      submit: () => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ error: { message: "内部错误", code: "internal_error" } }, 500);
        }
        return jsonResponse(makeJob(), 201);
      },
    });
    renderExperimentsPage();
    await waitForResources();
    await selectDraft();

    fireEvent.click(submitButton());
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("内部错误")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("实验名称（可选）"), {
      target: { value: "改后名称" },
    });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(submitCalls()).toHaveLength(2));
    const body = JSON.parse(String(submitCalls()[1].init.body)) as ExperimentSubmitInput;
    expect(body.name).toBe("改后名称");
    expect(await screen.findByText("实验已启动：种子扫描")).toBeInTheDocument();
  });

  it("同时存在多个阻塞原因时全部展示", async () => {
    stubScenario();
    renderExperimentsPage();
    await waitForResources();

    fireEvent.change(screen.getByLabelText("场数"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("实验名称（可选）"), {
      target: { value: "名".repeat(101) },
    });

    const list = screen.getByRole("list", { name: "阻塞原因" });
    expect(within(list).getByText("请先选择草案")).toBeInTheDocument();
    expect(within(list).getByText("场数需为 1 到 10000 的整数")).toBeInTheDocument();
    expect(within(list).getByText("实验名称最多 100 个字符")).toBeInTheDocument();
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  });
});
