import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  ApiError,
  applyRoster,
  createSave,
  deleteSave,
  getSaveSquad,
  importSave,
  importSaveFile,
  importSaveTactic,
  listSaves,
  listSaveTactics,
  undoRoster,
  updateSave,
  type Health,
  type Save,
  type SaveTactic,
} from "../lib/api";
import { LibraryPage } from "./LibraryPage";

const { isDesktopShellMock, chooseLocalFileMock } = vi.hoisted(() => ({
  isDesktopShellMock: vi.fn(),
  chooseLocalFileMock: vi.fn(),
}));

vi.mock("../lib/file-dialog", () => ({
  isDesktopShell: isDesktopShellMock,
  chooseLocalFile: chooseLocalFileMock,
}));

beforeEach(() => {
  isDesktopShellMock.mockReset();
  isDesktopShellMock.mockReturnValue(false);
  chooseLocalFileMock.mockReset();
  chooseLocalFileMock.mockResolvedValue(null);
});

const connection = { url: "http://127.0.0.1:43210", token: "test-token", api: "fm27lab/v2" };
const health: Health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};
const SHA = "0123456789abcdef".repeat(4);

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

function makeSave(overrides: Partial<Save> = {}): Save {
  return {
    id: "save-1",
    source_path: "/saves/season-1.fm",
    source_sha256: SHA,
    status: "pending",
    stage: null,
    metadata: {},
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

function makeList(items: Save[], total = items.length, nextOffset: number | null = null) {
  return { items, total, next_offset: nextOffset };
}

function TacticsPlaceholder() {
  const location = useLocation();
  return (
    <div data-testid="tactics-placeholder">{`${location.pathname}${location.search}`}</div>
  );
}

function renderLibraryPage(
  activeConnection: typeof connection | null = connection,
  initialEntries: string[] = ["/library"],
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <AppContext.Provider
          value={{
            connection: activeConnection,
            health,
            connectionError: null,
            refreshing: false,
            refresh: vi.fn(),
          }}
        >
          <Routes>
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/tactics" element={<TacticsPlaceholder />} />
          </Routes>
        </AppContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function rowFor(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (row === null) throw new Error("未找到存档行：" + text);
  return row;
}

function disabledControls(): Array<HTMLButtonElement | HTMLInputElement | HTMLSelectElement> {
  const controls = [
    ...screen.queryAllByRole("button"),
    ...screen.queryAllByRole("checkbox"),
    ...screen.queryAllByRole("combobox"),
  ];
  return controls
    .filter(
      (control): control is HTMLButtonElement | HTMLInputElement | HTMLSelectElement =>
        control instanceof HTMLButtonElement ||
        control instanceof HTMLInputElement ||
        control instanceof HTMLSelectElement,
    )
    .filter((control) => control.disabled);
}

function expectDisabledControlsExplained() {
  const controls = disabledControls();
  expect(controls.length).toBeGreaterThan(0);
  for (const control of controls) {
    const descriptionId = control.getAttribute("aria-describedby");
    const described = descriptionId === null ? null : document.getElementById(descriptionId);
    const explanation = control.getAttribute("title") ?? described?.textContent ?? "";
    expect(explanation.trim()).not.toBe("");
  }
}

describe("LibraryPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("加载中显示状态，成功后渲染带鉴权的存档列表", async () => {
    const pending = deferred<Response>();
    stubFetch(() => pending.promise);
    renderLibraryPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载存档");

    pending.resolve(jsonResponse(makeList([makeSave({ status: "reading" })])));

    expect(await screen.findByText("/saves/season-1.fm")).toBeInTheDocument();
    expect(within(rowFor("/saves/season-1.fm")).getByText("读取中")).toBeInTheDocument();

    const [first] = fetchCalls();
    expect(first.url).toBe("http://127.0.0.1:43210/api/saves?limit=20&offset=0");
    expect(new Headers(first.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("列表为空时显示导入引导", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();

    expect(await screen.findByText("尚未导入存档")).toBeInTheDocument();
    expect(
      screen.getByText(
        "这是唯一的存档导入入口。导入后可以浏览联赛战术、生成真实 AI 计划、导出 FMF 或加入客队战术池。没有存档也可以导入 FMF 战术文件使用战术板与固定对手实验。",
      ),
    ).toBeInTheDocument();
  });

  it("状态筛选携带 status 查询并渲染筛选结果", async () => {
    stubFetch((url) =>
      jsonResponse(
        url.includes("status=ready")
          ? makeList([makeSave({ id: "save-ready", status: "ready" })])
          : makeList([makeSave()]),
      ),
    );
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    fireEvent.change(screen.getByLabelText("状态筛选"), { target: { value: "ready" } });

    expect(await screen.findByText("已就绪")).toBeInTheDocument();
    expect(callsTo("/api/saves?status=ready&limit=20&offset=0")).toHaveLength(1);
  });

  it("分页按钮按 next_offset 加载下一页", async () => {
    stubFetch((url) =>
      jsonResponse(
        url.includes("offset=20")
          ? makeList([makeSave({ id: "save-2", source_path: "/saves/season-2.fm" })], 21, null)
          : makeList([makeSave()], 21, 20),
      ),
    );
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");
    expect(screen.getByText("共 21 个存档")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("/saves/season-2.fm")).toBeInTheDocument();
    expect(callsTo("offset=20")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
  });

  it("删除存档需要二次确认，成功后调用 DELETE 并刷新列表", async () => {
    let deleted = false;
    stubFetch((_url, init) => {
      if (init.method === "DELETE") {
        deleted = true;
        return noContentResponse();
      }
      return jsonResponse(deleted ? makeList([]) : makeList([makeSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    fireEvent.click(within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "删除" }));
    fireEvent.click(within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "放弃" }));
    expect(callsTo("/api/saves/save-1")).toHaveLength(0);

    fireEvent.click(within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "删除" }));
    fireEvent.click(
      within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "确认删除" }),
    );

    await waitFor(() => expect(callsTo("/api/saves/save-1")).toHaveLength(1));
    expect(callsTo("/api/saves/save-1")[0].init.method).toBe("DELETE");
    expect(await screen.findByText("已删除存档")).toBeInTheDocument();
    expect(await screen.findByText("尚未导入存档")).toBeInTheDocument();
  });

  it("列表加载失败时展示后端错误并可重试", async () => {
    let attempts = 0;
    stubFetch(() => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "validation_failed", message: "存档列表查询失败" } }, 400);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("存档列表查询失败");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("尚未导入存档")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("sidecar 未连接时显示空态", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage(null);

    expect(await screen.findByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });
});

describe("存档 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listSaves 携带状态筛选与分页参数", async () => {
    stubFetch(() => jsonResponse(makeList([makeSave()])));

    const list = await listSaves(connection, { status: "ready", limit: 20, offset: 40 });

    expect(list.items[0].id).toBe("save-1");
    expect(fetchCalls()[0].url).toBe(
      "http://127.0.0.1:43210/api/saves?status=ready&limit=20&offset=40",
    );
  });

  it("createSave 使用 POST 提交存档字段", async () => {
    stubFetch(() => jsonResponse(makeSave(), 201));

    await createSave(connection, {
      source_path: "/saves/new.fm",
      source_sha256: SHA,
      stage: "leagues",
      metadata: { a: 1 },
    });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      source_path: "/saves/new.fm",
      source_sha256: SHA,
      stage: "leagues",
      metadata: { a: 1 },
    });
  });

  it("updateSave 使用 PATCH 提交变更", async () => {
    stubFetch(() => jsonResponse(makeSave({ status: "reading" })));

    await updateSave(connection, "save-1", { status: "reading" });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/save-1");
    expect(call.init.method).toBe("PATCH");
    expect(JSON.parse(String(call.init.body))).toEqual({ status: "reading" });
  });

  it("deleteSave 使用 DELETE", async () => {
    stubFetch(() => noContentResponse());

    await deleteSave(connection, "save-1");

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/save-1");
    expect(call.init.method).toBe("DELETE");
  });

  it("importSave 提交 leagues 与 clubs 对象", async () => {
    stubFetch(() => jsonResponse(makeSave({ status: "ready" })));

    const imported = await importSave(connection, "save-1", {
      leagues: { premier: { clubs: [1] } },
      clubs: { "10": { name: "甲" } },
    });

    expect(imported.status).toBe("ready");
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/save-1/import");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      leagues: { premier: { clubs: [1] } },
      clubs: { "10": { name: "甲" } },
    });
  });
});

describe("存档战术库路由", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("通过 /library 渲染存档战术库并出现在主导航", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/health")) return jsonResponse(health);
      return jsonResponse(makeList([]));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/library"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "存档战术库" })).toBeInTheDocument();
    expect(await screen.findByText("尚未导入存档")).toBeInTheDocument();
  });
});

const FILE_IMPORT_RESULT = {
  save_id: "save-new",
  status: "ready",
  managed_clubs: [{ club_uid: 7, club_name: "阿森纳", players: 23 }],
  clubs: 1,
};

const SQUAD = {
  save_id: "save-1",
  club_uid: 7,
  club_name: "阿森纳",
  players: [
    { source_uid: 101, name: "萨卡", position: "AMR", ability: 168 },
    { source_uid: 102, name: "赖斯", position: "MC", ability: 172 },
  ],
  selection: { club_uid: 7, team_id: 22, team_slot: 0, lineup: [101, 102], substitutes: [103, 104, 105] },
};

function managedSave(): Save {
  return makeSave({ metadata: { managed_club_uids: [7] } });
}

function draftSummary(overrides: Record<string, unknown> = {}) {
  return {
    id: "draft-1",
    name: "测试草稿",
    source: {},
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

async function openSquad(): Promise<HTMLElement> {
  fireEvent.click(
    within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "查看名单" }),
  );
  const section = screen.getByRole("region", { name: "存档球队名单" });
  const clubs = within(section).getByRole("group", { name: "经理俱乐部" });
  fireEvent.click(within(clubs).getByRole("button", { name: "俱乐部 7" }));
  return section;
}

async function waitForRoster(scope: HTMLElement) {
  const roster = within(scope).getByRole("region", { name: "阵容同步" });
  const form = within(roster).getByRole("form", { name: "阵容同步表单" });
  await waitFor(() =>
    expect(within(form).getByLabelText("选择同步草稿")).toHaveValue("draft-1"),
  );
  return { roster, form };
}

describe("存档文件导入", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("校验存档路径后提交 source_path，成功后展示存档标识、状态与经理俱乐部", async () => {
    let posted: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posted = JSON.parse(String(init.body));
        return jsonResponse(FILE_IMPORT_RESULT, 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "导入存档文件" }));
    const form = screen.getByRole("form", { name: "导入存档文件" });
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));
    expect(within(form).getByText("存档文件路径不能为空")).toBeInTheDocument();
    expect(posted).toBeNull();

    fireEvent.change(within(form).getByLabelText("存档文件路径"), {
      target: { value: "/saves/season-2.fm" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));

    await waitFor(() =>
      expect(posted).toEqual({ source_path: "/saves/season-2.fm", replace: false }),
    );
    expect(callsTo("/api/saves/import")[0].url).toBe(
      "http://127.0.0.1:43210/api/saves/import",
    );
    const result = await screen.findByRole("region", { name: "存档文件导入结果" });
    expect(within(result).getByText("save-new")).toBeInTheDocument();
    expect(within(result).getByText("已就绪")).toBeInTheDocument();
    expect(within(result).getByText("阿森纳（23 人）")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/api/saves?limit=20&offset=0")).toHaveLength(2));
  });

  it("重复导入返回 409 时展示后端消息，并可用覆盖导入重试", async () => {
    const posts: unknown[] = [];
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        const body = JSON.parse(String(init.body)) as { replace?: boolean };
        posts.push(body);
        if (body.replace === true) return jsonResponse(FILE_IMPORT_RESULT, 201);
        return jsonResponse({ error: { code: "conflict", message: "存档内容重复" } }, 409);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "导入存档文件" }));
    const form = screen.getByRole("form", { name: "导入存档文件" });
    fireEvent.change(within(form).getByLabelText("存档文件路径"), {
      target: { value: "/saves/season-1.fm" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("存档内容重复");
    fireEvent.click(within(alert).getByRole("button", { name: "覆盖导入" }));

    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual({ source_path: "/saves/season-1.fm", replace: true });
    expect(
      await screen.findByRole("region", { name: "存档文件导入结果" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("存档内容重复")).not.toBeInTheDocument();
  });

  it("勾选覆盖复选项后提交 replace 为 true", async () => {
    let posted: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posted = JSON.parse(String(init.body));
        return jsonResponse(FILE_IMPORT_RESULT, 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "导入存档文件" }));
    const form = screen.getByRole("form", { name: "导入存档文件" });
    fireEvent.change(within(form).getByLabelText("存档文件路径"), {
      target: { value: "/saves/season-3.fm" },
    });
    fireEvent.click(within(form).getByLabelText("覆盖已存在的存档"));
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));

    await waitFor(() =>
      expect(posted).toEqual({ source_path: "/saves/season-3.fm", replace: true }),
    );
  });
});

describe("存档球队名单", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("选择存档与经理俱乐部后加载球员与阵容人数", async () => {
    const squadResponse = deferred<Response>();
    stubFetch((url) => {
      if (url.includes("/squad")) return squadResponse.promise;
      if (url.includes("/api/drafts")) {
        return jsonResponse({ items: [], total: 0, next_offset: null });
      }
      return jsonResponse(makeList([managedSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = await openSquad();
    expect(within(section).getByRole("group", { name: "经理俱乐部" })).toBeInTheDocument();
    expect(within(section).getByRole("status")).toHaveTextContent("正在加载名单");

    squadResponse.resolve(jsonResponse(SQUAD));

    expect(await within(section).findByText("萨卡")).toBeInTheDocument();
    expect(within(section).getByText("AMR")).toBeInTheDocument();
    expect(within(section).getByText("168")).toBeInTheDocument();
    expect(within(section).getByText("阿森纳")).toBeInTheDocument();
    expect(within(section).getByText("首发 2 人 · 替补 3 人")).toBeInTheDocument();
    expect(callsTo("/api/saves/save-1/squad?club_uid=7")).toHaveLength(1);
  });

  it("名单为空时显示空态", async () => {
    stubFetch((url) => {
      if (url.includes("/squad")) {
        return jsonResponse({ ...SQUAD, players: [], selection: null });
      }
      if (url.includes("/api/drafts")) {
        return jsonResponse({ items: [], total: 0, next_offset: null });
      }
      return jsonResponse(makeList([managedSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = await openSquad();

    expect(
      await within(section).findByText("该俱乐部没有可读取的球员"),
    ).toBeInTheDocument();
    expect(within(section).queryByText("首发 2 人 · 替补 3 人")).not.toBeInTheDocument();
  });

  it("名单加载失败时展示后端错误并可重试", async () => {
    let attempts = 0;
    stubFetch((url) => {
      if (url.includes("/squad")) {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse(
            { error: { code: "not_found", message: "存档球队不存在" } },
            404,
          );
        }
        return jsonResponse(SQUAD);
      }
      if (url.includes("/api/drafts")) {
        return jsonResponse({ items: [], total: 0, next_offset: null });
      }
      return jsonResponse(makeList([managedSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = await openSquad();
    const alert = await within(section).findByRole("alert");
    expect(alert).toHaveTextContent("存档球队不存在");

    fireEvent.click(within(alert).getByRole("button", { name: "重试" }));
    expect(await within(section).findByText("萨卡")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });
});

describe("阵容同步到草稿", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function stubRoster(handlers: {
    onApply?: (body: unknown) => Response;
    onUndo?: () => Response;
  }) {
    stubFetch((url, init) => {
      if (init.method === "POST" && url.includes("/apply-roster")) {
        const body: unknown = JSON.parse(String(init.body));
        return (
          handlers.onApply?.(body) ??
          jsonResponse({
            draft: draftSummary(),
            applied: { starters: 11, substitutes: 0 },
          })
        );
      }
      if (init.method === "POST" && url.includes("/undo-roster")) {
        return handlers.onUndo?.() ?? jsonResponse({ draft: draftSummary() });
      }
      if (url.includes("/squad")) return jsonResponse(SQUAD);
      if (url.includes("/api/drafts")) {
        return jsonResponse({ items: [draftSummary()], total: 1, next_offset: null });
      }
      return jsonResponse(makeList([managedSave()]));
    });
  }

  it("提交草稿、主客与范围并展示变更人数", async () => {
    const posts: unknown[] = [];
    stubRoster({
      onApply: (body) => {
        posts.push(body);
        return jsonResponse({
          draft: draftSummary(),
          applied: { starters: 11, substitutes: 0 },
        });
      },
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");
    const section = await openSquad();
    await within(section).findByText("萨卡");
    const { roster, form } = await waitForRoster(section);

    fireEvent.change(within(form).getByLabelText("同步范围"), {
      target: { value: "starters" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "同步阵容" }));

    await waitFor(() =>
      expect(posts[0]).toEqual({
        save_id: "save-1",
        club_uid: 7,
        side: "home",
        scope: "starters",
      }),
    );
    expect(
      await within(roster).findByText("已同步：首发 11 人、替补 0 人"),
    ).toBeInTheDocument();

    fireEvent.click(within(form).getByRole("button", { name: "客队" }));
    fireEvent.change(within(form).getByLabelText("同步范围"), {
      target: { value: "bench" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "同步阵容" }));

    await waitFor(() =>
      expect(posts[1]).toEqual({
        save_id: "save-1",
        club_uid: 7,
        side: "away",
        scope: "bench",
      }),
    );
  });

  it("撤销阵容同步成功后提示", async () => {
    stubRoster({});
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");
    const section = await openSquad();
    await within(section).findByText("萨卡");
    const { roster, form } = await waitForRoster(section);

    fireEvent.click(within(form).getByRole("button", { name: "撤销同步" }));

    expect(await within(roster).findByText("已撤销阵容同步")).toBeInTheDocument();
    const undoCall = callsTo("/api/drafts/draft-1/undo-roster");
    expect(undoCall).toHaveLength(1);
    expect(undoCall[0].init.method).toBe("POST");
  });

  it("同步与撤销失败时展示后端错误消息", async () => {
    stubRoster({
      onApply: () =>
        jsonResponse(
          { error: { code: "validation_failed", message: "草稿球队名单必须为 23 人" } },
          400,
        ),
      onUndo: () =>
        jsonResponse(
          { error: { code: "validation_failed", message: "没有可撤销的阵容同步" } },
          400,
        ),
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");
    const section = await openSquad();
    await within(section).findByText("萨卡");
    const { roster, form } = await waitForRoster(section);

    fireEvent.click(within(form).getByRole("button", { name: "同步阵容" }));
    expect(await within(roster).findByRole("alert")).toHaveTextContent(
      "草稿球队名单必须为 23 人",
    );

    fireEvent.click(within(form).getByRole("button", { name: "撤销同步" }));
    expect(await within(roster).findByRole("alert")).toHaveTextContent(
      "没有可撤销的阵容同步",
    );
  });

  it("草稿列表加载失败时提示且禁用同步按钮", async () => {
    stubFetch((url) => {
      if (url.includes("/squad")) return jsonResponse(SQUAD);
      if (url.includes("/api/drafts")) {
        return jsonResponse(
          { error: { code: "validation_failed", message: "草稿列表查询失败" } },
          400,
        );
      }
      return jsonResponse(makeList([managedSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");
    const section = await openSquad();
    await within(section).findByText("萨卡");

    const roster = screen.getByRole("region", { name: "阵容同步" });
    const alert = await within(roster).findByRole("alert");
    expect(alert).toHaveTextContent("草稿列表加载失败：草稿列表查询失败");
    const form = within(roster).getByRole("form", { name: "阵容同步表单" });
    expect(within(form).getByRole("button", { name: "同步阵容" })).toBeDisabled();
    expect(within(form).getByLabelText("选择同步草稿")).toBeDisabled();
  });
});

describe("存档文件导入与阵容 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("importSaveFile 使用 POST 提交 source_path 与 replace", async () => {
    stubFetch(() => jsonResponse(FILE_IMPORT_RESULT, 201));

    const result = await importSaveFile(connection, {
      source_path: "/saves/a.fm",
      replace: true,
    });

    expect(result.save_id).toBe("save-new");
    expect(result.managed_clubs[0].club_name).toBe("阿森纳");
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/import");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      source_path: "/saves/a.fm",
      replace: true,
    });
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("getSaveSquad 携带 club_uid 查询参数", async () => {
    stubFetch(() => jsonResponse(SQUAD));

    const squad = await getSaveSquad(connection, "save-1", 7);

    expect(squad.players).toHaveLength(2);
    expect(squad.selection?.lineup).toEqual([101, 102]);
    expect(fetchCalls()[0].url).toBe(
      "http://127.0.0.1:43210/api/saves/save-1/squad?club_uid=7",
    );
  });

  it("applyRoster 提交存档、主客与范围", async () => {
    stubFetch(() =>
      jsonResponse({ draft: draftSummary(), applied: { starters: 11, substitutes: 12 } }),
    );

    const result = await applyRoster(connection, "draft-1", {
      save_id: "save-1",
      club_uid: 7,
      side: "away",
      scope: "both",
    });

    expect(result.applied).toEqual({ starters: 11, substitutes: 12 });
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1/apply-roster");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      save_id: "save-1",
      club_uid: 7,
      side: "away",
      scope: "both",
    });
  });

  it("undoRoster 使用 POST 且不携带请求体", async () => {
    stubFetch(() => jsonResponse({ draft: draftSummary() }));

    const result = await undoRoster(connection, "draft-1");

    expect(result.draft.id).toBe("draft-1");
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1/undo-roster");
    expect(call.init.method).toBe("POST");
    expect(call.init.body).toBeUndefined();
  });

  it("导入冲突转换为 ApiError 并携带后端消息", async () => {
    stubFetch(() =>
      jsonResponse({ error: { code: "conflict", message: "存档内容重复" } }, 409),
    );

    await expect(
      importSaveFile(connection, { source_path: "/saves/a.fm", replace: false }),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      importSaveFile(connection, { source_path: "/saves/a.fm", replace: false }),
    ).rejects.toMatchObject({ status: 409, code: "conflict", message: "存档内容重复" });
  });
});

function fmfDraft(overrides: Record<string, unknown> = {}) {
  return {
    id: "draft-fmf",
    name: "导入战术",
    scenario: { schema: 4, teams: [] },
    source: { kind: "fmf" },
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

const SAVE_DIALOG_REQUEST = {
  title: "选择存档文件",
  filters: [{ name: "FM 存档", extensions: ["fm"] }],
};

const FMF_DIALOG_REQUEST = {
  title: "选择 FMF 战术文件",
  filters: [{ name: "FMF 战术文件", extensions: ["fmf"] }],
};

function openSaveForm(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: "导入存档文件" }));
  return screen.getByRole("form", { name: "导入存档文件" });
}

function openFmfForm(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: "导入 FMF 战术文件" }));
  return screen.getByRole("form", { name: "导入 FMF 战术文件" });
}

describe("存档导入桌面选择", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("工具栏按钮在桌面环境拉起存档选择器并预填路径", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockResolvedValue("/saves/desktop-pick.fm");
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();

    expect(chooseLocalFileMock).toHaveBeenCalledWith(SAVE_DIALOG_REQUEST);
    await waitFor(() =>
      expect(within(form).getByLabelText("存档文件路径")).toHaveValue("/saves/desktop-pick.fm"),
    );
  });

  it("取消选择时保留表单且路径为空", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockResolvedValue(null);
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();

    await waitFor(() => expect(chooseLocalFileMock).toHaveBeenCalledTimes(1));
    expect(within(form).getByLabelText("存档文件路径")).toHaveValue("");
    expect(screen.getByRole("form", { name: "导入存档文件" })).toBeInTheDocument();
  });

  it("选择器失败时保留表单并展示错误", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockRejectedValue(new Error("dialog failed"));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    openSaveForm();

    expect(await screen.findByRole("alert")).toHaveTextContent("dialog failed");
    expect(screen.getByRole("form", { name: "导入存档文件" })).toBeInTheDocument();
  });

  it("表单浏览按钮选择文件后填入路径", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock
      .mockResolvedValueOnce("/saves/toolbar-pick.fm")
      .mockResolvedValueOnce("/saves/browse-pick.fm");
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();
    await waitFor(() =>
      expect(within(form).getByLabelText("存档文件路径")).toHaveValue("/saves/toolbar-pick.fm"),
    );

    fireEvent.click(within(form).getByRole("button", { name: "浏览…" }));

    await waitFor(() =>
      expect(within(form).getByLabelText("存档文件路径")).toHaveValue("/saves/browse-pick.fm"),
    );
    expect(chooseLocalFileMock).toHaveBeenCalledTimes(2);
  });

  it("提交体使用 trim 后的路径", async () => {
    let posted: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posted = JSON.parse(String(init.body));
        return jsonResponse(FILE_IMPORT_RESULT, 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();
    fireEvent.change(within(form).getByLabelText("存档文件路径"), {
      target: { value: "  /saves/trimmed.fm  " },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));

    await waitFor(() =>
      expect(posted).toEqual({ source_path: "/saves/trimmed.fm", replace: false }),
    );
  });

  it("非桌面环境不渲染浏览按钮", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();

    expect(within(form).queryByRole("button", { name: "浏览…" })).not.toBeInTheDocument();
    expect(chooseLocalFileMock).not.toHaveBeenCalled();
  });

  it("存档导入请求中禁用浏览按钮", async () => {
    const pending = deferred<Response>();
    stubFetch((_url, init) =>
      init.method === "POST" ? pending.promise : jsonResponse(makeList([])),
    );
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockResolvedValue(null);
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openSaveForm();
    fireEvent.change(within(form).getByLabelText("存档文件路径"), {
      target: { value: "/saves/pending.fm" },
    });
    const browse = within(form).getByRole("button", { name: "浏览…" });
    expect(browse).toBeEnabled();
    fireEvent.click(within(form).getByRole("button", { name: "导入文件" }));

    await waitFor(() => expect(browse).toBeDisabled());

    pending.resolve(jsonResponse(FILE_IMPORT_RESULT, 201));
    await waitFor(() =>
      expect(screen.queryByRole("form", { name: "导入存档文件" })).not.toBeInTheDocument(),
    );
  });
});

describe("FMF 战术文件导入", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("工具栏在桌面环境拉起 FMF 选择器并填入路径与派生名称", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockResolvedValue("/tactics/4-4-2-press.fmf");
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();

    expect(chooseLocalFileMock).toHaveBeenCalledWith(FMF_DIALOG_REQUEST);
    expect(within(form).getByText(/FMF 文件自带双队场景/)).toBeInTheDocument();
    await waitFor(() =>
      expect(within(form).getByLabelText("战术文件路径")).toHaveValue("/tactics/4-4-2-press.fmf"),
    );
    expect(within(form).getByLabelText("名称")).toHaveValue("4-4-2-press");
  });

  it("提交精确请求体并在成功后跳转战术页", async () => {
    const posts: unknown[] = [];
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse(fmfDraft({ name: "北岸联战术" }), 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/北岸联战术.fmf" },
    });
    expect(within(form).getByLabelText("名称")).toHaveValue("北岸联战术");
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await waitFor(() =>
      expect(posts).toEqual([{ source_path: "/tactics/北岸联战术.fmf", name: "北岸联战术" }]),
    );
    expect(callsTo("/api/drafts/import-fmf-file")[0].url).toBe(
      "http://127.0.0.1:43210/api/drafts/import-fmf-file",
    );
    expect(callsTo("/api/drafts/import-fmf-file")[0].init.method).toBe("POST");
    const placeholder = await screen.findByTestId("tactics-placeholder");
    expect(placeholder).toHaveTextContent("/tactics?draft=draft-fmf");
  });

  it("空路径显示错误且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    expect(within(form).getByText("战术文件路径不能为空")).toBeInTheDocument();
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 25);
    });
    expect(callsTo("/api/drafts/import-fmf-file")).toHaveLength(0);
  });

  it("服务端 400 展示后端消息并可在重试后成功", async () => {
    const posts: unknown[] = [];
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        if (posts.length === 1) {
          return jsonResponse(
            { error: { code: "invalid_request", message: "FMF 文件缺少双队场景" } },
            400,
          );
        }
        return jsonResponse(fmfDraft(), 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/retry.fmf" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("FMF 文件缺少双队场景");
    expect(within(form).getByLabelText("战术文件路径")).toHaveValue("/tactics/retry.fmf");

    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    expect(await screen.findByTestId("tactics-placeholder")).toHaveTextContent(
      "/tactics?draft=draft-fmf",
    );
    expect(posts).toHaveLength(2);
  });

  it("请求中表单标记 aria-busy 且提交按钮禁用", async () => {
    const pending = deferred<Response>();
    stubFetch((_url, init) =>
      init.method === "POST" ? pending.promise : jsonResponse(makeList([])),
    );
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/slow.fmf" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await waitFor(() => expect(form).toHaveAttribute("aria-busy", "true"));
    expect(within(form).getByRole("button", { name: "导入中…" })).toBeDisabled();

    pending.resolve(jsonResponse(fmfDraft(), 201));
    expect(await screen.findByTestId("tactics-placeholder")).toBeInTheDocument();
  });

  it("用户改写名称后切换路径不覆盖名称", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("名称"), {
      target: { value: "自定义名称" },
    });
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/other-file.fmf" },
    });

    expect(within(form).getByLabelText("名称")).toHaveValue("自定义名称");
  });

  it("名称派生超过 80 字符时截断", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: `/tactics/${"a".repeat(100)}.fmf` },
    });

    expect(within(form).getByLabelText("名称")).toHaveValue("a".repeat(80));
  });

  it("名称清空后提交仅携带路径", async () => {
    const posts: unknown[] = [];
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse(fmfDraft(), 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/plain.fmf" },
    });
    fireEvent.change(within(form).getByLabelText("名称"), { target: { value: "" } });
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await waitFor(() => expect(posts).toEqual([{ source_path: "/tactics/plain.fmf" }]));
  });

  it("取消关闭表单并清空错误", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));
    expect(within(form).getByText("战术文件路径不能为空")).toBeInTheDocument();

    fireEvent.click(within(form).getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("form", { name: "导入 FMF 战术文件" })).not.toBeInTheDocument();
    const reopened = openFmfForm();
    expect(within(reopened).queryByText("战术文件路径不能为空")).not.toBeInTheDocument();
  });

  it("非桌面环境不渲染浏览按钮", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();

    expect(within(form).queryByRole("button", { name: "浏览…" })).not.toBeInTheDocument();
    expect(chooseLocalFileMock).not.toHaveBeenCalled();
  });

  it("工具栏按刷新、导入存档文件、导入 FMF 战术文件排列", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const refresh = screen.getByRole("button", { name: "刷新" });
    const toolbar = refresh.parentElement;
    if (toolbar === null) throw new Error("工具栏缺失");
    const labels = within(toolbar)
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());

    expect(labels).toEqual(["刷新", "导入存档文件", "导入 FMF 战术文件"]);
  });

  it("路径不含文件名时名称兜底为导入战术", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/" },
    });

    expect(within(form).getByLabelText("名称")).toHaveValue("导入战术");
  });

  it("名称被清空后修改路径重新派生名称", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/first.fmf" },
    });
    expect(within(form).getByLabelText("名称")).toHaveValue("first");
    fireEvent.change(within(form).getByLabelText("名称"), { target: { value: "" } });
    expect(within(form).getByLabelText("名称")).toHaveValue("");
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/second.fmf" },
    });

    expect(within(form).getByLabelText("名称")).toHaveValue("second");
  });

  it("FMF 导入成功使草稿查询失效", async () => {
    stubFetch((_url, init) =>
      init.method === "POST" ? jsonResponse(fmfDraft(), 201) : jsonResponse(makeList([])),
    );
    const invalidateSpy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/invalidate.fmf" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await screen.findByTestId("tactics-placeholder");
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["drafts", connection.url],
    });
  });

  it("提交 FMF 时裁剪路径前后空白", async () => {
    const posts: unknown[] = [];
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse(fmfDraft(), 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "  /tactics/trimmed.fmf  " },
    });
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await waitFor(() =>
      expect(posts).toEqual([{ source_path: "/tactics/trimmed.fmf", name: "trimmed" }]),
    );
  });

  it("FMF 导入请求中禁用浏览按钮", async () => {
    const pending = deferred<Response>();
    stubFetch((_url, init) =>
      init.method === "POST" ? pending.promise : jsonResponse(makeList([])),
    );
    isDesktopShellMock.mockReturnValue(true);
    chooseLocalFileMock.mockResolvedValue(null);
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    const form = openFmfForm();
    fireEvent.change(within(form).getByLabelText("战术文件路径"), {
      target: { value: "/tactics/pending.fmf" },
    });
    const browse = within(form).getByRole("button", { name: "浏览…" });
    expect(browse).toBeEnabled();
    fireEvent.click(within(form).getByRole("button", { name: "导入 FMF" }));

    await waitFor(() => expect(browse).toBeDisabled());

    pending.resolve(jsonResponse(fmfDraft(), 201));
    expect(await screen.findByTestId("tactics-placeholder")).toBeInTheDocument();
  });
});

describe("LibraryPage 清理后的入口与禁用说明", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("不提供新建存档与 JSON 导入入口", async () => {
    stubFetch(() => jsonResponse(makeList([makeSave()])));
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    expect(screen.queryByRole("button", { name: "新建存档" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "新建存档" })).not.toBeInTheDocument();
    expect(
      within(rowFor("/saves/season-1.fm")).queryByRole("button", { name: "导入" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "导入存档数据" })).not.toBeInTheDocument();
  });

  it("筛选无结果时提示切换状态", async () => {
    stubFetch((url) =>
      url.includes("status=ready") ? jsonResponse(makeList([])) : jsonResponse(makeList([makeSave()])),
    );
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    fireEvent.change(screen.getByLabelText("状态筛选"), { target: { value: "ready" } });

    expect(await screen.findByText("没有符合条件的存档")).toBeInTheDocument();
    expect(
      screen.getByText("当前筛选条件下没有存档，切换状态后重试。"),
    ).toBeInTheDocument();
  });

  it("禁用控件均带可访问说明", async () => {
    stubFetch(() => jsonResponse(makeList([makeSave()])));
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expectDisabledControlsExplained();
  });

  it("无可用草稿时说明阵容同步不可用原因", async () => {
    stubFetch((url) => {
      if (url.includes("/squad")) return jsonResponse(SQUAD);
      if (url.includes("/api/drafts")) {
        return jsonResponse({ items: [], total: 0, next_offset: null });
      }
      return jsonResponse(makeList([managedSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = await openSquad();
    await within(section).findByText("萨卡");
    const roster = within(section).getByRole("region", { name: "阵容同步" });
    expect(
      await within(roster).findByText("先在战术板保存草稿，才能同步阵容"),
    ).toBeInTheDocument();
    const draftSelect = within(roster).getByLabelText("选择同步草稿");
    expect(draftSelect).toBeDisabled();
    expect(draftSelect).toHaveAccessibleDescription("先在战术板保存草稿，才能同步阵容");
    const sync = within(roster).getByRole("button", { name: "同步阵容" });
    expect(sync).toBeDisabled();
    expect(sync).toHaveAccessibleDescription("先在战术板保存草稿，才能同步阵容");
    const undo = within(roster).getByRole("button", { name: "撤销同步" });
    expect(undo).toBeDisabled();
    expect(undo).toHaveAccessibleDescription("先在战术板保存草稿，才能同步阵容");
    expectDisabledControlsExplained();
  });
});

function makeSaveTactic(overrides: Partial<SaveTactic> = {}): SaveTactic {
  return {
    index: 0,
    name: "北岸联 4-4-2",
    style: "控制",
    mentality: 3,
    club_uid: 7,
    club_name: "北岸联",
    team_slot: 0,
    importable: true,
    ...overrides,
  };
}

function openTactics(): HTMLElement {
  fireEvent.click(
    within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "战术库" }),
  );
  return screen.getByRole("region", { name: "存档存储战术" });
}

function stubSaveLibrary(tacticsResponse: (init: RequestInit) => Response | Promise<Response>) {
  stubFetch((url, init) => {
    if (url.includes("/tactics")) return tacticsResponse(init);
    return jsonResponse(makeList([makeSave()]));
  });
}

describe("存档存储战术", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("加载中展示状态，成功后渲染存储战术并高亮一线队槽位", async () => {
    const pending = deferred<Response>();
    stubSaveLibrary(() => pending.promise);
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    expect(within(section).getByRole("status")).toHaveTextContent("正在加载存档战术");
    expect(within(section).getByText("/saves/season-1.fm")).toBeInTheDocument();

    pending.resolve(
      jsonResponse({
        items: [
          makeSaveTactic(),
          makeSaveTactic({
            index: 1,
            name: "北岸联 5-3-2",
            style: "反击",
            mentality: 5,
            team_slot: 1,
          }),
        ],
      }),
    );

    expect(await within(section).findByText("北岸联 4-4-2")).toBeInTheDocument();
    const firstRow = within(section).getByText("北岸联 4-4-2").closest("tr");
    if (firstRow === null) throw new Error("未找到战术行");
    expect(within(firstRow).getByText("控制")).toBeInTheDocument();
    expect(within(firstRow).getByText("谨慎")).toBeInTheDocument();
    expect(within(firstRow).getByText("可导入")).toBeInTheDocument();
    expect(within(firstRow).getByText("一线队")).toHaveAttribute("data-primary", "true");
    expect(within(firstRow).getByRole("button", { name: "导入到战术板" })).toBeEnabled();

    const secondRow = within(section).getByText("北岸联 5-3-2").closest("tr");
    if (secondRow === null) throw new Error("未找到战术行");
    expect(within(secondRow).getByText("槽位 1")).toBeInTheDocument();
    expect(within(secondRow).getByText("积极")).toBeInTheDocument();

    const calls = callsTo("/api/saves/save-1/tactics");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://127.0.0.1:43210/api/saves/save-1/tactics");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("导入成功后跳转战术板草稿并使草稿查询失效", async () => {
    stubFetch((url, init) => {
      if (init.method === "POST") {
        return jsonResponse({ draft: fmfDraft({ id: "draft-save" }) }, 201);
      }
      if (url.includes("/tactics")) return jsonResponse({ items: [makeSaveTactic({ index: 2 })] });
      return jsonResponse(makeList([makeSave()]));
    });
    const invalidateSpy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    fireEvent.click(await within(section).findByRole("button", { name: "导入到战术板" }));

    const placeholder = await screen.findByTestId("tactics-placeholder");
    expect(placeholder).toHaveTextContent("/tactics?draft=draft-save");
    const calls = callsTo("/api/saves/save-1/tactics/2/import");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://127.0.0.1:43210/api/saves/save-1/tactics/2/import");
    expect(calls[0].init.method).toBe("POST");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["drafts", connection.url] });
  });

  it("不可导入的战术禁用按钮并给出行内原因", async () => {
    stubSaveLibrary(() =>
      jsonResponse({
        items: [
          makeSaveTactic({ index: 0, name: "一线队可用", team_slot: 0, importable: true }),
          makeSaveTactic({ index: 1, name: "青年队战术", team_slot: 2, importable: false }),
          makeSaveTactic({ index: 2, name: "一线队缺引擎", team_slot: 0, importable: false }),
        ],
      }),
    );
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    await within(section).findByText("青年队战术");

    const youthRow = within(section).getByText("青年队战术").closest("tr");
    if (youthRow === null) throw new Error("未找到战术行");
    expect(within(youthRow).getByText("非一线队存储战术")).toBeInTheDocument();
    expect(within(youthRow).getByText("槽位 2")).toBeInTheDocument();
    expect(within(youthRow).getByText("不可导入")).toBeInTheDocument();
    const youthButton = within(youthRow).getByRole("button", { name: "导入到战术板" });
    expect(youthButton).toBeDisabled();
    expect(youthButton).toHaveAttribute("title", "非一线队存储战术");

    const engineRow = within(section).getByText("一线队缺引擎").closest("tr");
    if (engineRow === null) throw new Error("未找到战术行");
    expect(within(engineRow).getByText("需要先配置引擎资源")).toBeInTheDocument();
    const engineButton = within(engineRow).getByRole("button", { name: "导入到战术板" });
    expect(engineButton).toBeDisabled();
    expect(engineButton).toHaveAttribute("title", "需要先配置引擎资源");

    const primaryRow = within(section).getByText("一线队可用").closest("tr");
    if (primaryRow === null) throw new Error("未找到战术行");
    expect(within(primaryRow).getByRole("button", { name: "导入到战术板" })).toBeEnabled();
  });

  it("战术列表加载失败时展示后端消息并在重试后成功", async () => {
    let attempts = 0;
    stubSaveLibrary(() => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "not_found", message: "存档不存在" } }, 404);
      }
      return jsonResponse({ items: [makeSaveTactic()] });
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    expect(await within(section).findByRole("alert")).toHaveTextContent("存档不存在");

    fireEvent.click(within(section).getByRole("button", { name: "重试" }));

    expect(await within(section).findByText("北岸联 4-4-2")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("存档没有存储战术时显示空态", async () => {
    stubSaveLibrary(() => jsonResponse({ items: [] }));
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    expect(await within(section).findByText("该存档没有可用的存储战术")).toBeInTheDocument();
  });

  it("引擎不可用时展示后端消息与设置页链接", async () => {
    stubFetch((url, init) => {
      if (init.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "engine_unavailable",
              message: "引擎资源未配置，无法导入存档战术；请在设置页配置引擎目录与游戏目录",
            },
          },
          503,
        );
      }
      if (url.includes("/tactics")) return jsonResponse({ items: [makeSaveTactic()] });
      return jsonResponse(makeList([makeSave()]));
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    const section = openTactics();
    fireEvent.click(await within(section).findByRole("button", { name: "导入到战术板" }));

    const alert = await within(section).findByRole("alert");
    expect(alert).toHaveTextContent("引擎资源未配置");
    expect(within(alert).getByRole("link", { name: "去设置页" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByTestId("tactics-placeholder")).not.toBeInTheDocument();
  });
});

describe("存档战术 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listSaveTactics 请求存档战术并解包 items", async () => {
    stubFetch(() => jsonResponse({ items: [makeSaveTactic({ index: 3 })] }));

    const items = await listSaveTactics(connection, "save-1");

    expect(items).toHaveLength(1);
    expect(items[0].index).toBe(3);
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/save-1/tactics");
    expect(call.init.method).toBeUndefined();
  });

  it("importSaveTactic 以 POST 导入指定索引并解包 draft", async () => {
    stubFetch(() => jsonResponse({ draft: fmfDraft({ id: "draft-imported" }) }, 201));

    const draft = await importSaveTactic(connection, "save-1", 2);

    expect(draft.id).toBe("draft-imported");
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/saves/save-1/tactics/2/import");
    expect(call.init.method).toBe("POST");
    expect(call.init.body).toBeUndefined();
  });

  it("引擎不可用时抛出不带跳转的 ApiError", async () => {
    stubFetch(() =>
      jsonResponse({ error: { code: "engine_unavailable", message: "引擎资源未配置" } }, 503),
    );

    const caught = await importSaveTactic(connection, "save-1", 0).catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
    expect((caught as ApiError).code).toBe("engine_unavailable");
    expect((caught as ApiError).message).toBe("引擎资源未配置");
  });
});
