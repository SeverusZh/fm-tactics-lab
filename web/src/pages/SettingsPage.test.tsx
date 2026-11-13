import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { AppContext } from "../app-context";
import {
  checkConcurrency,
  deleteSetting,
  getSetting,
  listSettings,
  putSetting,
  type ConcurrencyCheck,
  type Health,
  type Setting,
} from "../lib/api";
import { SettingsPage } from "./SettingsPage";

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

function listCalls() {
  return fetchCalls().filter(
    (call) => (call.init.method ?? "GET") === "GET" && call.url.endsWith("/api/settings"),
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function makeSetting(overrides: Partial<Setting> = {}): Setting {
  return {
    key: "match.roster_size",
    value: { size: 23 },
    note: "首发人数",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

function makeList(items: Setting[], total = items.length) {
  return { items, total };
}

function renderSettingsPage(activeConnection: typeof connection | null = connection) {
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
        <SettingsPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function rowFor(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (row === null) throw new Error("未找到设置行：" + text);
  return row;
}

const allowedCheck: ConcurrencyCheck = {
  allowed: true,
  code: null,
  recommended_workers: 8,
  warnings: [],
  memory_required_bytes: 6 * GIB,
  disk_required_bytes: 6 * GIB,
};

const blockedCheck: ConcurrencyCheck = {
  allowed: false,
  code: "insufficient_memory",
  recommended_workers: 1,
  warnings: ["可用内存低于 2 GiB，资源预检未通过"],
  memory_required_bytes: 10 * GIB,
  disk_required_bytes: 10 * GIB,
};

describe("SettingsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载中显示状态，成功后渲染带鉴权的设置列表", async () => {
    const pending = deferred<Response>();
    stubFetch(() => pending.promise);
    renderSettingsPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载设置");

    pending.resolve(jsonResponse(makeList([makeSetting()])));

    expect(await screen.findByText("match.roster_size")).toBeInTheDocument();
    const row = rowFor("match.roster_size");
    expect(within(row).getByText('{"size":23}')).toBeInTheDocument();
    expect(within(row).getByText("首发人数")).toBeInTheDocument();
    expect(within(row).getByText(/2026/)).toBeInTheDocument();

    const [first] = fetchCalls();
    expect(first.url).toBe("http://127.0.0.1:43210/api/settings");
    expect(new Headers(first.init.headers).get("Authorization")).toBe("Bearer test-token");

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(listCalls()).toHaveLength(2));
  });

  it("列表为空时显示空态", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderSettingsPage();

    expect(await screen.findByText("尚无设置")).toBeInTheDocument();
    expect(screen.getByText("新建设置后，这里会显示键、JSON 值与更新时间。")).toBeInTheDocument();
  });

  it("列表加载失败时展示后端错误信息并可重试", async () => {
    let attempts = 0;
    stubFetch(() => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "validation_failed", message: "设置列表读取失败" } }, 400);
      }
      return jsonResponse(makeList([]));
    });
    renderSettingsPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("设置列表读取失败");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("尚无设置")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("新建设置校验键与 JSON 后保存并刷新列表", async () => {
    const savedItem = makeSetting({ key: "match.tempo", value: { high: true }, note: "战术节奏" });
    let saved: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "PUT") {
        saved = JSON.parse(String(init.body));
        return jsonResponse(savedItem);
      }
      return jsonResponse(makeList(saved === null ? [] : [savedItem]));
    });
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByRole("button", { name: "新建设置" }));
    fireEvent.change(screen.getByLabelText("设置键"), { target: { value: "Bad-Key" } });
    fireEvent.change(screen.getByLabelText("值 JSON"), { target: { value: "{" } });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "战术节奏" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(
      screen.getByText("设置键需以小写字母开头，仅含小写字母、数字、点、横线或下划线，最多 64 个字符"),
    ).toBeInTheDocument();
    expect(screen.getByText("设置值必须是合法 JSON")).toBeInTheDocument();
    expect(screen.getByLabelText("设置键")).toHaveAttribute("aria-invalid", "true");
    expect(fetchCalls().some((call) => call.init.method === "PUT")).toBe(false);

    fireEvent.change(screen.getByLabelText("设置键"), { target: { value: "match.tempo" } });
    fireEvent.change(screen.getByLabelText("值 JSON"), { target: { value: '{"high":true}' } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(saved).not.toBeNull());
    const [put] = fetchCalls().filter((call) => call.init.method === "PUT");
    expect(put.url).toBe("http://127.0.0.1:43210/api/settings/match.tempo");
    expect(saved).toEqual({ value: { high: true }, note: "战术节奏" });
    expect(await screen.findByText("设置「match.tempo」已保存")).toBeInTheDocument();
    expect(await screen.findByText("match.tempo")).toBeInTheDocument();
    expect(screen.queryByLabelText("设置键")).not.toBeInTheDocument();
    await waitFor(() => expect(listCalls()).toHaveLength(2));
  });

  it("编辑设置时预填 JSON 并锁定设置键", async () => {
    let saved: unknown = null;
    stubFetch((_url, init) => {
      if (init.method === "PUT") {
        saved = JSON.parse(String(init.body));
        return jsonResponse(makeSetting({ value: 24, note: null }));
      }
      return jsonResponse(makeList([makeSetting()]));
    });
    renderSettingsPage();
    await screen.findByText("match.roster_size");

    fireEvent.click(within(rowFor("match.roster_size")).getByRole("button", { name: "编辑" }));
    const keyInput = screen.getByLabelText("设置键");
    expect(keyInput).toBeDisabled();
    expect(keyInput).toHaveValue("match.roster_size");
    expect(screen.getByLabelText("值 JSON")).toHaveValue(JSON.stringify({ size: 23 }, null, 2));
    expect(screen.getByLabelText("备注")).toHaveValue("首发人数");

    fireEvent.change(screen.getByLabelText("值 JSON"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toEqual({ value: 24, note: null });
    expect(await screen.findByText("设置「match.roster_size」已保存")).toBeInTheDocument();
  });

  it("备注超过上限时阻止保存", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByRole("button", { name: "新建设置" }));
    fireEvent.change(screen.getByLabelText("设置键"), { target: { value: "match.tempo" } });
    fireEvent.change(screen.getByLabelText("值 JSON"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "n".repeat(201) } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(screen.getByText("设置备注最多 200 个字符")).toBeInTheDocument();
    expect(fetchCalls().some((call) => call.init.method === "PUT")).toBe(false);
  });

  it("保存失败时展示后端错误信息并保留表单", async () => {
    stubFetch((_url, init) => {
      if (init.method === "PUT") {
        return jsonResponse({ error: { code: "validation_failed", message: "设置值嵌套过深" } }, 400);
      }
      return jsonResponse(makeList([]));
    });
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByRole("button", { name: "新建设置" }));
    fireEvent.change(screen.getByLabelText("设置键"), { target: { value: "deep.value" } });
    fireEvent.change(screen.getByLabelText("值 JSON"), {
      target: { value: "[".repeat(70) + "0" + "]".repeat(70) },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("设置值嵌套过深");
    expect(screen.getByLabelText("设置键")).toBeInTheDocument();
  });

  it("删除设置需要二次确认，确认后调用 DELETE 并显示空态", async () => {
    let deleted = false;
    stubFetch((_url, init) => {
      if (init.method === "DELETE") {
        deleted = true;
        return noContentResponse();
      }
      return jsonResponse(makeList(deleted ? [] : [makeSetting()]));
    });
    renderSettingsPage();
    await screen.findByText("match.roster_size");

    fireEvent.click(within(rowFor("match.roster_size")).getByRole("button", { name: "删除" }));
    fireEvent.click(within(rowFor("match.roster_size")).getByRole("button", { name: "放弃" }));
    expect(fetchCalls().some((call) => call.init.method === "DELETE")).toBe(false);

    fireEvent.click(within(rowFor("match.roster_size")).getByRole("button", { name: "删除" }));
    fireEvent.click(within(rowFor("match.roster_size")).getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(fetchCalls().some((call) => call.init.method === "DELETE")).toBe(true));
    const [call] = fetchCalls().filter((entry) => entry.init.method === "DELETE");
    expect(call.url).toBe("http://127.0.0.1:43210/api/settings/match.roster_size");
    expect(await screen.findByText("已删除设置「match.roster_size」")).toBeInTheDocument();
    expect(await screen.findByText("尚无设置")).toBeInTheDocument();
  });

  it("并发预检展示允许状态、推荐并行数与查询参数", async () => {
    const pending = deferred<Response>();
    stubFetch((url) => {
      if (url.includes("/api/concurrency/check")) return pending.promise;
      return jsonResponse(makeList([]));
    });
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));
    expect(await screen.findByRole("status")).toHaveTextContent("正在预检");
    pending.resolve(jsonResponse(allowedCheck));

    const region = await screen.findByRole("region", { name: "并发预检结果" });
    expect(within(region).getByText("允许提交")).toBeInTheDocument();
    expect(within(region).getByText(/推荐并行数/)).toHaveTextContent("推荐并行数 8");
    expect(within(region).queryByRole("list")).not.toBeInTheDocument();
    expect(within(region).getByText(/需要内存 6 GiB/)).toBeInTheDocument();

    const [call] = callsTo("/api/concurrency/check");
    expect(call.url).toBe(
      `http://127.0.0.1:43210/api/concurrency/check?workers=4&cpu_count=8&available_memory_bytes=${32 * GIB}&free_disk_bytes=${100 * GIB}&allow_oversubscription=false`,
    );
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("并发预检展示阻止状态、原因代码与警告", async () => {
    stubFetch((url) =>
      url.includes("/api/concurrency/check") ? jsonResponse(blockedCheck) : jsonResponse(makeList([])),
    );
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("可用内存 GiB"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));

    const region = await screen.findByRole("region", { name: "并发预检结果" });
    expect(within(region).getByText("阻止提交")).toBeInTheDocument();
    expect(within(region).getByText("insufficient_memory")).toBeInTheDocument();
    expect(within(region).getByRole("listitem")).toHaveTextContent(
      "可用内存低于 2 GiB，资源预检未通过",
    );

    const query = new URL(callsTo("/api/concurrency/check")[0].url).searchParams;
    expect(query.get("workers")).toBe("8");
    expect(query.get("available_memory_bytes")).toBe(String(GIB));
    expect(query.get("allow_oversubscription")).toBe("false");
  });

  it("允许资源覆盖时按 true 查询并展示覆盖警告", async () => {
    const overridden: ConcurrencyCheck = {
      ...allowedCheck,
      recommended_workers: 1,
      warnings: ["已按显式覆盖运行", "并行数高于推荐值，收益不保证"],
    };
    stubFetch((url) =>
      url.includes("/api/concurrency/check") ? jsonResponse(overridden) : jsonResponse(makeList([])),
    );
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByLabelText("允许资源覆盖"));
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));

    const region = await screen.findByRole("region", { name: "并发预检结果" });
    expect(within(region).getByText("允许提交")).toBeInTheDocument();
    expect(within(region).getByText("已按显式覆盖运行")).toBeInTheDocument();
    expect(within(region).getByText("并行数高于推荐值，收益不保证")).toBeInTheDocument();
    expect(new URL(callsTo("/api/concurrency/check")[0].url).searchParams.get("allow_oversubscription")).toBe(
      "true",
    );
  });

  it("并发预检输入非法时禁用按钮且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "257" } });
    fireEvent.change(screen.getByLabelText("CPU 数量"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("可用内存 GiB"), { target: { value: "-1" } });
    fireEvent.change(screen.getByLabelText("空闲磁盘 GiB"), { target: { value: "abc" } });

    expect(screen.getByText("并行数需为 1–256 的整数")).toBeInTheDocument();
    expect(screen.getByText("CPU 数量需为正整数")).toBeInTheDocument();
    expect(screen.getByText("可用内存需为非负 GiB 数值")).toBeInTheDocument();
    expect(screen.getByText("空闲磁盘需为非负 GiB 数值")).toBeInTheDocument();
    expect(screen.getByLabelText("并行数")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "运行预检" })).toBeDisabled();
    expect(callsTo("/api/concurrency/check")).toHaveLength(0);
  });

  it("并发预检请求失败时展示后端错误信息", async () => {
    stubFetch((url) =>
      url.includes("/api/concurrency/check")
        ? jsonResponse({ error: { code: "validation_failed", message: "资源预检失败" } }, 400)
        : jsonResponse(makeList([])),
    );
    renderSettingsPage();
    await screen.findByText("尚无设置");

    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("资源预检失败");
    expect(screen.queryByRole("region", { name: "并发预检结果" })).not.toBeInTheDocument();
  });

  it("sidecar 未连接时显示空态且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeList([])));
    renderSettingsPage(null);

    expect(await screen.findByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
    expect(screen.getByRole("button", { name: "运行预检" })).toBeDisabled();
  });
});

describe("设置 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listSettings 使用 GET 并携带鉴权", async () => {
    stubFetch(() => jsonResponse(makeList([makeSetting()])));

    const list = await listSettings(connection);

    expect(list.items[0].key).toBe("match.roster_size");
    expect(fetchCalls()[0].url).toBe("http://127.0.0.1:43210/api/settings");
    expect(new Headers(fetchCalls()[0].init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("getSetting 请求单个设置键并透出后端错误", async () => {
    stubFetch(() => jsonResponse({ error: { code: "not_found", message: "设置不存在" } }, 404));

    await expect(getSetting(connection, "match.roster_size")).rejects.toMatchObject({
      message: "设置不存在",
      status: 404,
      code: "not_found",
    });
    expect(fetchCalls()[0].url).toBe("http://127.0.0.1:43210/api/settings/match.roster_size");
  });

  it("putSetting 使用 PUT 提交值与备注", async () => {
    stubFetch(() => jsonResponse(makeSetting({ value: 24, note: null })));

    await putSetting(connection, "match.roster_size", { value: 24, note: null });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/settings/match.roster_size");
    expect(call.init.method).toBe("PUT");
    expect(JSON.parse(String(call.init.body))).toEqual({ value: 24, note: null });
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
  });

  it("deleteSetting 使用 DELETE", async () => {
    stubFetch(() => noContentResponse());

    await deleteSetting(connection, "match.roster_size");

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/settings/match.roster_size");
    expect(call.init.method).toBe("DELETE");
  });

  it("checkConcurrency 序列化全部预检参数", async () => {
    stubFetch(() => jsonResponse(allowedCheck));

    const result = await checkConcurrency(connection, {
      workers: 4,
      cpu_count: 8,
      available_memory_bytes: 32 * GIB,
      free_disk_bytes: 100 * GIB,
      allow_oversubscription: false,
    });

    expect(result.allowed).toBe(true);
    expect(fetchCalls()[0].url).toBe(
      `http://127.0.0.1:43210/api/concurrency/check?workers=4&cpu_count=8&available_memory_bytes=${32 * GIB}&free_disk_bytes=${100 * GIB}&allow_oversubscription=false`,
    );
  });

  it("checkConcurrency 允许覆盖时查询参数为 true", async () => {
    stubFetch(() => jsonResponse({ ...allowedCheck, warnings: ["已按显式覆盖运行"] }));

    await checkConcurrency(connection, {
      workers: 4,
      cpu_count: 8,
      available_memory_bytes: 32 * GIB,
      free_disk_bytes: 100 * GIB,
      allow_oversubscription: true,
    });

    expect(fetchCalls()[0].url).toContain("allow_oversubscription=true");
  });
});

describe("设置路由", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("通过 /settings 渲染设置页并出现在主导航", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/health")) return jsonResponse(health);
      return jsonResponse(makeList([]));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/settings"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "设置" })).toBeInTheDocument();
    expect(await screen.findByText("尚无设置")).toBeInTheDocument();
  });
});
