import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  createSave,
  deleteSave,
  importSave,
  listSaves,
  updateSave,
  type Health,
  type Save,
} from "../lib/api";
import { LibraryPage } from "./LibraryPage";

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

function renderLibraryPage(activeConnection: typeof connection | null = connection) {
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
        <LibraryPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function rowFor(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (row === null) throw new Error("未找到存档行：" + text);
  return row;
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
        "这是唯一的存档导入入口。导入后可以浏览联赛战术、生成真实 AI 计划、导出 FMF 或加入客队战术池。",
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

  it("创建存档提交表单并刷新列表", async () => {
    let posted: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        posted = JSON.parse(String(init.body));
        return jsonResponse(makeSave({ source_path: "/saves/new.fm" }), 201);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "新建存档" }));
    fireEvent.change(screen.getByLabelText("存档路径"), {
      target: { value: "/saves/new.fm" },
    });
    fireEvent.change(screen.getByLabelText("SHA-256"), { target: { value: SHA } });
    fireEvent.change(screen.getByLabelText("阶段"), { target: { value: "leagues" } });
    fireEvent.change(screen.getByLabelText("元数据 JSON"), {
      target: { value: '{"联赛":"英超"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toEqual({
      source_path: "/saves/new.fm",
      source_sha256: SHA,
      stage: "leagues",
      metadata: { 联赛: "英超" },
    });
    expect(await screen.findByText("存档已创建")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/api/saves?").length).toBe(2));
  });

  it("创建表单校验错误就地显示并阻止提交", async () => {
    stubFetch((_url, init) => {
      if (init.method === "POST") return jsonResponse(makeSave(), 201);
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "新建存档" }));
    expect(screen.getByRole("button", { name: "创建" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("SHA-256"), { target: { value: "abc" } });
    expect(
      screen.getByText("SHA-256 需为 64 位十六进制字符串"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("SHA-256")).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(screen.getByLabelText("元数据 JSON"), { target: { value: "{" } });
    expect(screen.getByText("元数据必须为合法 JSON 对象")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("阶段"), { target: { value: "x".repeat(201) } });
    expect(screen.getByText("阶段最多 200 个字符")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("存档路径"), { target: { value: "/saves/a.fm" } });
    fireEvent.change(screen.getByLabelText("SHA-256"), { target: { value: SHA } });
    fireEvent.change(screen.getByLabelText("元数据 JSON"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("阶段"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "创建" })).toBeEnabled();
    expect(fetchCalls().some((call) => call.init.method === "POST")).toBe(false);
  });

  it("导入 JSON 调用 import 接口并刷新列表", async () => {
    let posted: unknown = null;
    let imported = false;
    stubFetch((url, init) => {
      if (init.method === "POST" && url.includes("/import")) {
        posted = JSON.parse(String(init.body));
        imported = true;
        return jsonResponse(makeSave({ status: "ready" }));
      }
      return jsonResponse(
        imported ? makeList([makeSave({ status: "ready" })]) : makeList([makeSave({ status: "reading" })]),
      );
    });
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    fireEvent.click(within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "导入" }));
    fireEvent.change(screen.getByLabelText("导入 JSON"), {
      target: {
        value: '{"leagues":{"premier":{"clubs":[1]}},"clubs":{"10":{"name":"甲"}}}',
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入存档" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(callsTo("/api/saves/save-1/import")[0].url).toBe(
      "http://127.0.0.1:43210/api/saves/save-1/import",
    );
    expect(posted).toEqual({
      leagues: { premier: { clubs: [1] } },
      clubs: { "10": { name: "甲" } },
    });
    expect(await screen.findByText("存档已导入")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/api/saves?").length).toBe(2));
  });

  it("导入 JSON 校验失败就地显示且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeList([makeSave({ status: "reading" })])));
    renderLibraryPage();
    await screen.findByText("/saves/season-1.fm");

    fireEvent.click(within(rowFor("/saves/season-1.fm")).getByRole("button", { name: "导入" }));
    fireEvent.click(screen.getByRole("button", { name: "导入存档" }));
    expect(screen.getByText("导入内容不能为空")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("导入 JSON"), { target: { value: "不是 JSON" } });
    fireEvent.click(screen.getByRole("button", { name: "导入存档" }));
    expect(screen.getByText("导入内容必须是合法 JSON")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("导入 JSON"), { target: { value: '{"leagues":{}}' } });
    fireEvent.click(screen.getByRole("button", { name: "导入存档" }));
    expect(screen.getByText("导入内容需要 leagues 与 clubs 对象")).toBeInTheDocument();

    expect(callsTo("/import")).toHaveLength(0);
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

  it("创建存档冲突时展示后端错误", async () => {
    stubFetch((_url, init) => {
      if (init.method === "POST") {
        return jsonResponse({ error: { code: "conflict", message: "存档内容重复" } }, 409);
      }
      return jsonResponse(makeList([]));
    });
    renderLibraryPage();
    await screen.findByText("尚未导入存档");

    fireEvent.click(screen.getByRole("button", { name: "新建存档" }));
    fireEvent.change(screen.getByLabelText("存档路径"), {
      target: { value: "/saves/new.fm" },
    });
    fireEvent.change(screen.getByLabelText("SHA-256"), { target: { value: SHA } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("存档内容重复");
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
