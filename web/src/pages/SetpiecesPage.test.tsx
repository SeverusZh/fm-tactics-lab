import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import type { Health } from "../lib/api";
import type {
  SetpieceCatalog,
  SetpieceDetail,
  SetpieceRoutine,
  SetpieceValue,
} from "../lib/api-setpieces";
import { SetpiecesPage } from "./SetpiecesPage";

const connection = { url: "http://127.0.0.1:43210", token: "test-token", api: "fm27lab/v2" };
const health: Health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

const TYPE_NAMES = [
  "防守角球",
  "防守直接任意球",
  "防守边路任意球",
  "防守远距离任意球",
  "防守界外球",
  "进攻角球",
  "进攻直接任意球",
  "进攻边路任意球",
  "进攻远距离任意球",
  "进攻界外球",
];

const DEFEND_TASKS = [
  { id: 1, label: "盯防近门柱" },
  { id: 2, label: "盯防远门柱" },
  { id: 3, label: "区域防守" },
  { id: 4, label: "封堵射门" },
  { id: 5, label: "保护禁区" },
];

const ATTACK_TASKS = [
  { id: 6, label: "前点跑位" },
  { id: 7, label: "后点跑位" },
  { id: 8, label: "外围策应" },
  { id: 9, label: "掩护跑动" },
  { id: 10, label: "二点争抢" },
];

const CATALOG: SetpieceCatalog = {
  allowed: {
    "0": [1, 2, 3, 4, 5],
    "1": [1, 2, 3, 4, 5],
    "2": [1, 2, 3, 4, 5],
    "3": [1, 2, 3, 4, 5],
    "4": [6, 7, 8, 9, 10],
    "5": [6, 7, 8, 9, 10],
    "6": [6, 7, 8, 9, 10],
    "7": [6, 7, 8, 9, 10],
  },
  attack: ATTACK_TASKS,
  defend: DEFEND_TASKS,
  categories: [
    { id: 0, label: "门将" },
    { id: 1, label: "中后卫" },
    { id: 2, label: "边后卫" },
    { id: 3, label: "后腰" },
    { id: 4, label: "前腰" },
    { id: 5, label: "边锋" },
    { id: 6, label: "前锋" },
    { id: 7, label: "二前锋" },
  ],
  swing: [
    { id: 0, label: "内旋" },
    { id: 1, label: "外旋" },
  ],
  corner_target: [
    { id: 3, label: "近门柱" },
    { id: 4, label: "远门柱" },
  ],
  free_kick_risk: [{ id: 3, label: "直接射门" }],
  defensive_line: [
    { id: 0, label: "高位防线" },
    { id: 1, label: "低位防线" },
  ],
  types: TYPE_NAMES.map((label, id) => ({
    id,
    label,
    strategy_kind: id === 5 ? "corner_target" : [6, 7, 8].includes(id) ? "free_kick_risk" : [2, 3].includes(id) ? "defensive_line" : null,
    swing: id === 5 || id === 7,
  })),
  frequencies: [
    { id: 0, label: "较少 · 权重2" },
    { id: 1, label: "正常 · 权重5" },
    { id: 2, label: "较多 · 权重8" },
  ],
};

function makeRoutine(kind: number): SetpieceRoutine {
  return {
    name: TYPE_NAMES[kind] + " 1",
    opaque_flags: 0,
    frequency: 0,
    strategy: 255,
    swing: 255,
    priority: [0, 1, 2, 3, 4, 5, 6, 7],
    groups: [[1, 2], [3], [4], [5], [6], [7], [8], [9, 10]],
    backups: [[0, 0], [0], [0], [0], [0], [0], [0], [0, 0]],
  };
}

function makeValue(): SetpieceValue {
  const routines: Record<string, SetpieceRoutine[]> = {};
  for (const kind of TYPE_NAMES.keys()) {
    routines[String(kind)] = [makeRoutine(kind)];
  }
  return {
    routines,
    throw_styles: [0, 1, 0],
    role_priorities: { "0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": [], "7": [] },
  };
}

function makeDetail(overrides: Partial<SetpieceDetail> = {}): SetpieceDetail {
  return {
    setpiece_id: "home",
    team: "主队",
    side: 0,
    configured: false,
    updated_at: null,
    roster_size: 3,
    players: [
      { index: 0, name: "主队球员 01" },
      { index: 1, name: "主队球员 02" },
      { index: 2, name: "主队球员 03" },
    ],
    value: makeValue(),
    default: makeValue(),
    ...overrides,
  };
}

function makeList() {
  return {
    catalog: CATALOG,
    setpieces: [
      { setpiece_id: "home", team: "主队", side: 0, configured: false, updated_at: null },
      { setpiece_id: "away", team: "客队", side: 1, configured: false, updated_at: null },
    ],
  };
}

function decodeBase64Text(value: string): string {
  return new TextDecoder().decode(Uint8Array.from(atob(value), (ch) => ch.charCodeAt(0)));
}

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "Content-Type": "application/json" }),
    json: async () => body,
  } as unknown as Response;
}

function errorResponse(status: number, code: string, message: string): Response {
  return {
    ok: false,
    status,
    headers: new Headers({ "Content-Type": "application/json" }),
    json: async () => ({
      error: { code, message, details: null, retriable: status >= 500, retry_after_seconds: null },
    }),
  } as unknown as Response;
}

function downloadResponse(body: string): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({
      "Content-Type": "application/json",
      "Content-Disposition": 'attachment; filename="setpieces-home.json"',
      ETag: '"deadbeef"',
    }),
    blob: async () => new Blob([body], { type: "application/json" }),
    json: async () => JSON.parse(body),
  } as unknown as Response;
}

type FetchHandler = (url: string, init: RequestInit) => Response | Promise<Response>;

function stubFetch(handler: FetchHandler): void {
  fetchMock.mockImplementation(async (...args: unknown[]) => {
    const [input, init] = args as [RequestInfo | URL, RequestInit | undefined];
    return handler(String(input), init ?? {});
  });
}

function defaultHandler(url: string, init: RequestInit): Response {
  const method = init.method ?? "GET";
  if (url.endsWith("/api/health")) {
    return jsonResponse(health);
  }
  if (url.endsWith("/api/setpieces") && method === "GET") {
    return jsonResponse(makeList());
  }
  if (url.endsWith("/api/setpieces/home") && method === "GET") {
    return jsonResponse(makeDetail());
  }
  if (url.endsWith("/api/setpieces/home") && method === "PATCH") {
    const body = JSON.parse(String(init.body)) as { value: SetpieceValue };
    return jsonResponse(makeDetail({ configured: true, updated_at: "2026-11-15T10:00:00+00:00", value: body.value }));
  }
  if (url.endsWith("/api/setpieces/home/import-file") && method === "POST") {
    const body = JSON.parse(String(init.body)) as { content_base64?: string };
    const document = JSON.parse(decodeBase64Text(body.content_base64 ?? "")) as { value?: SetpieceValue };
    return jsonResponse(makeDetail({ configured: true, value: document.value ?? makeValue() }));
  }
  if (url.endsWith("/api/setpieces/home/export-file") && method === "GET") {
    return downloadResponse(JSON.stringify({ schema: "fm27-setpiece-document-v1", value: makeValue() }));
  }
  throw new Error("未处理的请求：" + method + " " + url);
}

function awayHandler(url: string, init: RequestInit): Response {
  const method = init.method ?? "GET";
  if (url.endsWith("/api/setpieces/away") && method === "GET") {
    const value = makeValue();
    value.routines["0"][0].name = "客队防守角球 1";
    return jsonResponse(makeDetail({ setpiece_id: "away", team: "客队", side: 1, value }));
  }
  return defaultHandler(url, init);
}

function allCalls(): { url: string; init: RequestInit }[] {
  return fetchMock.mock.calls.map((call) => {
    const [input, init] = call as unknown as [RequestInfo | URL, RequestInit | undefined];
    return { url: String(input), init: init ?? {} };
  });
}

function callsTo(fragment: string) {
  return allCalls().filter((call) => call.url.includes(fragment));
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider
        value={{ connection, health, connectionError: null, refreshing: false, refresh: vi.fn() }}
      >
        <SetpiecesPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function nameInput(): HTMLInputElement {
  return screen.getByLabelText("套路名称") as HTMLInputElement;
}

function saveButton(): HTMLElement {
  return screen.getByRole("button", { name: "保存定位球" });
}

describe("SetpiecesPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载后展示定位球类型、套路与默认值", async () => {
    stubFetch(defaultHandler);
    renderPage();

    expect(await screen.findByLabelText("套路名称")).toHaveValue("防守角球 1");
    expect(screen.getByLabelText("队伍")).toHaveValue("home");
    expect(screen.getByLabelText("定位球类型")).toHaveValue("0");
    expect(screen.getAllByRole("option", { name: /防守角球/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "界外球策略" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "角色分配顺序" })).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();

    const [first] = allCalls();
    expect(first.url).toBe("http://127.0.0.1:43210/api/setpieces");
    expect(new Headers(first.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("切换定位球类型后展示对应套路与发球策略", async () => {
    stubFetch(defaultHandler);
    renderPage();

    await screen.findByLabelText("套路名称");
    fireEvent.change(screen.getByLabelText("定位球类型"), { target: { value: "5" } });

    await waitFor(() => expect(nameInput()).toHaveValue("进攻角球 1"));
    const strategy = await screen.findByLabelText("发球策略");
    expect(within(strategy).queryByRole("option", { name: "近门柱" })).not.toBeNull();
  });

  it("保存时提交规范化前的完整文档", async () => {
    stubFetch(defaultHandler);
    renderPage();

    await screen.findByLabelText("套路名称");
    fireEvent.change(nameInput(), { target: { value: "角球新套路" } });
    fireEvent.click(saveButton());

    expect(await screen.findByText("已保存定位球配置")).toBeInTheDocument();
    const patches = callsTo("/api/setpieces/home").filter((call) => call.init.method === "PATCH");
    expect(patches).toHaveLength(1);
    const body = JSON.parse(String(patches[0].init.body)) as { value: SetpieceValue };
    expect(body.value.routines["0"][0].name).toBe("角球新套路");
    expect(new Headers(patches[0].init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("移除任务后禁用保存并说明任务数量不符", async () => {
    stubFetch(defaultHandler);
    renderPage();

    const goalkeeper = await screen.findByRole("region", { name: "门将" });
    fireEvent.click(within(goalkeeper).getByRole("button", { name: "移除门将第1项任务" }));

    const problem = await screen.findByRole("status");
    expect(problem).toHaveTextContent("防守角球需要分配10项任务，当前为9项");
    expect(saveButton()).toBeDisabled();
    expect(saveButton().getAttribute("title") ?? "").toContain("需要分配10项任务");
  });

  it("添加任务超出配额时保存被禁用", async () => {
    stubFetch(defaultHandler);
    renderPage();

    const goalkeeper = await screen.findByRole("region", { name: "门将" });
    fireEvent.click(within(goalkeeper).getByRole("button", { name: "添加任务" }));

    expect(await screen.findByRole("status")).toHaveTextContent("最多分配10项任务，当前为11项");
    expect(saveButton()).toBeDisabled();
  });

  it("导入本地 JSON 文档时以 base64 提交并刷新编辑值", async () => {
    stubFetch(defaultHandler);
    renderPage();
    await screen.findByLabelText("套路名称");

    const imported = makeValue();
    imported.routines["0"][0].name = "导入角球套路";
    const content = JSON.stringify({ schema: "fm27-setpiece-document-v1", value: imported });
    const file = new File([content], "setpieces.json", { type: "application/json" });
    fireEvent.change(screen.getByLabelText("选择定位球文档"), { target: { files: [file] } });

    await waitFor(() => expect(callsTo("/import-file")).toHaveLength(1));
    expect(await screen.findByText("已导入定位球文档")).toBeInTheDocument();
    const [importCall] = callsTo("/import-file");
    const body = JSON.parse(String(importCall.init.body)) as { content_base64: string };
    const decoded = Uint8Array.from(atob(body.content_base64), (ch) => ch.charCodeAt(0));
    expect(new TextDecoder().decode(decoded)).toBe(content);
    await waitFor(() => expect(nameInput()).toHaveValue("导入角球套路"));
  });

  it("导出文档时触发浏览器下载", async () => {
    stubFetch(defaultHandler);
    const blobs: Blob[] = [];
    const clicked: HTMLAnchorElement[] = [];
    const createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:test";
    });
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
    renderPage();

    await screen.findByLabelText("套路名称");
    fireEvent.click(screen.getByRole("button", { name: "导出文档" }));

    expect(await screen.findByText("已导出定位球文档")).toBeInTheDocument();
    expect(callsTo("/export-file")).toHaveLength(1);
    expect(blobs).toHaveLength(1);
    expect(clicked[0].download).toBe("setpieces-home.json");
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalled(), { timeout: 2500 });
    vi.restoreAllMocks();
    delete (URL as unknown as Record<string, unknown>).createObjectURL;
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
  });

  it("引擎资源未配置时展示可读错误", async () => {
    stubFetch(() =>
      errorResponse(503, "engine_unavailable", "引擎资源未配置，无法编辑定位球；请在设置页配置引擎目录与游戏目录"),
    );
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("引擎资源未配置，无法编辑定位球");
  });

  it("未连接 sidecar 时展示空态", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AppContext.Provider
          value={{ connection: null, health: null, connectionError: null, refreshing: false, refresh: vi.fn() }}
        >
          <SetpiecesPage />
        </AppContext.Provider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("提示任务配额与角色分配数量", async () => {
    stubFetch(defaultHandler);
    renderPage();

    expect(
      await screen.findByText("共 10 项任务，目标 10 项；已把 0 名球员分配到角色。"),
    ).toBeInTheDocument();
  });

  it("未保存时切换队伍需要确认", async () => {
    stubFetch(awayHandler);
    renderPage();

    await screen.findByLabelText("套路名称");
    fireEvent.change(nameInput(), { target: { value: "改过的套路" } });
    fireEvent.change(screen.getByLabelText("队伍"), { target: { value: "away" } });

    const dialog = await screen.findByRole("alertdialog", { name: "切换队伍确认" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-describedby", "setpiece-switch-warning");
    expect(within(dialog).getByRole("button", { name: "放弃修改并切换" })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("队伍")).toHaveValue("home");
    expect(screen.getByLabelText("队伍")).toHaveFocus();
    expect(nameInput()).toHaveValue("改过的套路");
    expect(callsTo("/api/setpieces/away")).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("队伍"), { target: { value: "away" } });
    fireEvent.click(await screen.findByRole("button", { name: "放弃修改并切换" }));

    await waitFor(() => expect(nameInput()).toHaveValue("客队防守角球 1"));
    expect(screen.getByLabelText("队伍")).toHaveValue("away");
    expect(callsTo("/api/setpieces/away")).toHaveLength(1);
  });

  it("后台刷新不覆盖未保存的修改", async () => {
    let detailCalls = 0;
    stubFetch((url, init) => {
      if (url.endsWith("/api/setpieces/home") && (init.method ?? "GET") === "GET") {
        detailCalls += 1;
        if (detailCalls > 1) {
          const value = makeValue();
          value.routines["0"][0].name = "服务器改名";
          return jsonResponse(makeDetail({ configured: true, value }));
        }
      }
      return defaultHandler(url, init);
    });
    renderPage();

    await screen.findByLabelText("套路名称");
    fireEvent.change(nameInput(), { target: { value: "未保存的改名" } });
    await waitFor(() => expect(screen.getByText("未保存")).toBeInTheDocument());
    const before = detailCalls;

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    window.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(detailCalls).toBeGreaterThan(before));
    Reflect.deleteProperty(document, "visibilityState");
    expect(nameInput()).toHaveValue("未保存的改名");
  });

  it("未保存的修改阻止关闭窗口", async () => {
    stubFetch(defaultHandler);
    renderPage();

    await screen.findByLabelText("套路名称");
    const clean = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(clean)).toBe(true);

    fireEvent.change(nameInput(), { target: { value: "改过的套路" } });
    await waitFor(() => expect(screen.getByText("未保存")).toBeInTheDocument());

    const dirty = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(dirty)).toBe(false);
  });

  it("只剩一套套路时禁止删除并说明原因", async () => {
    stubFetch(defaultHandler);
    renderPage();

    await screen.findByLabelText("套路名称");
    const remove = screen.getByRole("button", { name: "删除套路" });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAttribute("title", "至少保留 1 套套路");
  });
});

describe("定位球路由", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("通过 /setpieces 渲染定位球页并出现在主导航", async () => {
    stubFetch(defaultHandler);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/setpieces"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "定位球" })).toBeInTheDocument();
    expect(await screen.findByLabelText("套路名称")).toHaveValue("防守角球 1");
  });
});
