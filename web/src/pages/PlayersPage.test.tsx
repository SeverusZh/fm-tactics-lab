import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext } from "../app-context";
import {
  applyDraftAttributes,
  createDraft,
  deleteDraft,
  getDraft,
  listDrafts,
  updateDraft,
  type Draft,
  type DraftList,
  type DraftSummary,
  type Health,
} from "../lib/api";
import type { Connection } from "../lib/connection";
import { PlayersPage } from "./PlayersPage";

const connection: Connection = {
  url: "http://127.0.0.1:43210",
  token: "test-token",
  api: "fm27lab/v2",
};
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

function makeAttributes(overrides: Record<number, number> = {}): number[] {
  const attributes = new Array<number>(69).fill(10);
  attributes[7] = 18;
  attributes[0] = 5;
  for (const [index, value] of Object.entries(overrides)) {
    attributes[Number(index)] = value;
  }
  return attributes;
}

function makePlayer(
  uid: number,
  name: string,
  overrides: Record<number, number> = {},
  ability: unknown = 10,
): Record<string, unknown> {
  return { source_uid: uid, name, attributes: makeAttributes(overrides), ability };
}

const HOME_FIRST = { 15: 78, 21: 60, 38: 75, 39: 40, 49: 90, 26: 55 };
const AWAY_FIRST = { 0: 20, 15: 45 };

function makeTeam(
  name: string,
  uidBase: number,
  firstOverrides: Record<number, number>,
  ability: unknown,
): Record<string, unknown> {
  return {
    name,
    players: Array.from({ length: 23 }, (_, index) => {
      if (index === 0) {
        return makePlayer(uidBase + index, `${name}球员 01`, firstOverrides, ability);
      }
      if (index === 1) {
        return makePlayer(uidBase + index, `${name}球员 02`, { 15: 60 });
      }
      return makePlayer(uidBase + index, `${name}球员 ${String(index + 1).padStart(2, "0")}`);
    }),
    roster_size: 23,
  };
}

function makeScenario(homeName = "主队", awayName = "客队"): Record<string, unknown> {
  return {
    schema: 4,
    teams: [
      makeTeam(homeName, 100, HOME_FIRST, 88),
      makeTeam(awayName, 200, AWAY_FIRST, { current: 70 }),
    ],
  };
}

function makeSummary(overrides: Partial<DraftSummary> = {}): DraftSummary {
  return {
    id: "draft-1",
    name: "草案一",
    source: { kind: "inline" },
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

function makeDraft(overrides: Partial<Draft> = {}): Draft {
  return {
    id: "draft-1",
    name: "草案一",
    scenario: makeScenario(),
    source: { kind: "inline" },
    created_at: "2026-11-13T10:00:00+00:00",
    updated_at: "2026-11-13T10:00:00+00:00",
    ...overrides,
  };
}

function makeDraftList(
  items: DraftSummary[],
  total = items.length,
  nextOffset: number | null = null,
): DraftList {
  return { items, total, next_offset: nextOffset };
}

function makeAttributeResult(overrides: Partial<{ changed_players: number }> = {}) {
  return {
    draft: makeSummary(),
    snapshot: { side: "home", scope: "all", operation: "bulk", indices: [15] },
    changed_players: 23,
    ...overrides,
  };
}

function attributeCalls() {
  return fetchCalls().filter((call) => call.url.endsWith("/api/drafts/draft-1/attributes"));
}

function detailCalls(draftId = "draft-1") {
  return fetchCalls().filter((call) => call.url.endsWith(`/api/drafts/${draftId}`));
}

function renderPlayersPage(activeConnection: Connection | null = connection) {
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
        <PlayersPage />
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function roster(name: "主队球员名单" | "客队球员名单"): HTMLElement {
  return screen.getByRole("complementary", { name });
}

function detailRegion(): HTMLElement {
  return screen.getByRole("region", { name: "选中球员属性" });
}

function displayedAttribute(label: string): string {
  const term = screen.getByText(label, { selector: "dt" });
  const value = term.parentElement?.querySelector("dd");
  if (value === null || value === undefined) throw new Error("未找到属性值：" + label);
  return value.textContent ?? "";
}

function draftHandlers(detail: Draft = makeDraft()) {
  return (url: string) => {
    if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
    return jsonResponse(detail);
  };
}

describe("PlayersPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载草稿列表后请求首个草稿并渲染 23 人名单", async () => {
    const pendingDetail = deferred<Response>();
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) {
        return jsonResponse(
          makeDraftList([makeSummary(), makeSummary({ id: "draft-2", name: "草案二" })]),
        );
      }
      if (url.endsWith("/api/drafts/draft-1")) return pendingDetail.promise;
      return jsonResponse({}, 404);
    });
    renderPlayersPage();

    expect(screen.getByRole("status")).toHaveTextContent("正在加载草稿");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("正在加载球员属性"),
    );

    pendingDetail.resolve(jsonResponse(makeDraft()));

    expect(within(await screen.findByRole("complementary", { name: "主队球员名单" })).getByText("主队球员 01")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");
    expect(within(roster("主队球员名单")).getAllByRole("button")).toHaveLength(23);

    const [listCall, detailCall] = fetchCalls();
    expect(listCall.url).toBe("http://127.0.0.1:43210/api/drafts");
    expect(new Headers(listCall.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(detailCall.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1");
    expect(new Headers(detailCall.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("选择另一份草稿会加载对应场景", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) {
        return jsonResponse(
          makeDraftList([makeSummary(), makeSummary({ id: "draft-2", name: "草案二" })]),
        );
      }
      if (url.endsWith("/api/drafts/draft-2")) {
        return jsonResponse(
          makeDraft({ id: "draft-2", name: "草案二", scenario: makeScenario("主队乙", "客队乙") }),
        );
      }
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getByText("主队球员 01")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "选择草稿" }), {
      target: { value: "draft-2" },
    });

    const updatedRoster = await screen.findByRole("complementary", {
      name: "主队球员名单",
    });
    expect(within(updatedRoster).getByText("主队乙球员 01")).toBeInTheDocument();
    expect(within(updatedRoster).queryByText("主队球员 01")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2");
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(1);
  });

  it("主客队切换渲染对应名单与属性", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getByText("主队球员 01")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "主队" })).toHaveAttribute("aria-pressed", "true");
    expect(within(detailRegion()).getByText("主队")).toBeInTheDocument();
    expect(displayedAttribute("门将")).toBe("5");

    fireEvent.click(screen.getByRole("button", { name: "客队" }));

    const awayRoster = await screen.findByRole("complementary", { name: "客队球员名单" });
    expect(within(awayRoster).getByText("客队球员 01")).toBeInTheDocument();
    expect(within(awayRoster).queryByText("主队球员 01")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "客队" })).toHaveAttribute("aria-pressed", "true");
    expect(within(detailRegion()).getByText("客队")).toBeInTheDocument();

    const row = within(awayRoster).getByRole("button", { name: /客队球员 01/ });
    expect(within(row).getByText("GK")).toBeInTheDocument();
    expect(within(row).getByText("70")).toBeInTheDocument();
    expect(displayedAttribute("门将")).toBe("20");

    fireEvent.click(screen.getByRole("button", { name: "主队" }));

    const restoredRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(restoredRoster).getByText("主队球员 01")).toBeInTheDocument();
    expect(displayedAttribute("门将")).toBe("5");
  });

  it("按六组展示属性并按内部值换算显示值", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    expect(
      within(await screen.findByRole("complementary", { name: "主队球员名单" })).getByText(
        "主队球员 01",
      ),
    ).toBeInTheDocument();

    for (const title of ["技术", "精神", "身体", "门将", "位置熟练度"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: "隐藏" })).not.toBeInTheDocument();

    expect(displayedAttribute("传中")).toBe("15.6");
    expect(displayedAttribute("技术")).toBe("15");
    expect(displayedAttribute("无球跑动")).toBe("12");
    expect(displayedAttribute("爆发力")).toBe("18");
    expect(displayedAttribute("手控球")).toBe("11");
    expect(displayedAttribute("中前卫")).toBe("18");
    expect(displayedAttribute("门将")).toBe("5");
  });

  it("切换球员更新右侧属性", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getByText("主队球员 01")).toBeInTheDocument();
    expect(displayedAttribute("传中")).toBe("15.6");
    expect(within(homeRoster).getByRole("button", { name: /主队球员 01/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(within(homeRoster).getByRole("button", { name: /主队球员 02/ }));

    expect(within(detailRegion()).getByText("主队球员 02")).toBeInTheDocument();
    expect(displayedAttribute("传中")).toBe("12");
    expect(within(homeRoster).getByRole("button", { name: /主队球员 02/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(homeRoster).getByRole("button", { name: /主队球员 01/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("隐藏属性默认关闭并可切换", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    expect(
      within(await screen.findByRole("complementary", { name: "主队球员名单" })).getByText(
        "主队球员 01",
      ),
    ).toBeInTheDocument();

    const toggle = screen.getByRole("checkbox", { name: "显示隐藏属性" });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("heading", { name: "隐藏" })).not.toBeInTheDocument();
    expect(screen.queryByText("左脚", { selector: "dt" })).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(screen.getByRole("heading", { name: "隐藏" })).toBeInTheDocument();
    expect(displayedAttribute("左脚")).toBe("8");
    expect(displayedAttribute("右脚")).toBe("2");

    fireEvent.click(toggle);

    expect(screen.queryByRole("heading", { name: "隐藏" })).not.toBeInTheDocument();
    expect(screen.queryByText("左脚", { selector: "dt" })).not.toBeInTheDocument();
  });

  it("无草稿时显示空态且不请求详情", async () => {
    stubFetch(() => jsonResponse(makeDraftList([])));
    renderPlayersPage();

    expect(await screen.findByText("暂无草稿")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "选择草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "批量属性编辑" })).not.toBeInTheDocument();
    expect(callsTo("/api/drafts/")).toHaveLength(0);
  });

  it("草稿列表加载失败显示错误并可重试", async () => {
    let attempts = 0;
    stubFetch((url) => {
      if (!url.endsWith("/api/drafts")) return jsonResponse(makeDraft());
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: { code: "http_error", message: "草稿服务不可用" } }, 500);
      }
      return jsonResponse(makeDraftList([makeSummary()]));
    });
    renderPlayersPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("草稿服务不可用");
    expect(screen.queryByRole("combobox", { name: "选择草稿" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(
      within(await screen.findByRole("complementary", { name: "主队球员名单" })).getByText(
        "主队球员 01",
      ),
    ).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("草稿详情加载失败显示错误并可重试", async () => {
    let detailAttempts = 0;
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      detailAttempts += 1;
      if (detailAttempts === 1) {
        return jsonResponse({ error: { code: "http_error", message: "草稿读取失败" } }, 500);
      }
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("草稿读取失败");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(
      within(await screen.findByRole("complementary", { name: "主队球员名单" })).getByText(
        "主队球员 01",
      ),
    ).toBeInTheDocument();
    expect(detailAttempts).toBe(2);
  });

  it("场景缺少两支 23 人球队时显示错误", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(makeDraft({ scenario: { teams: [] } }));
    });
    renderPlayersPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("场景数据无效");
  });

  it("sidecar 未连接时显示空态且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeDraftList([])));
    renderPlayersPage(null);

    expect(await screen.findByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("批量编辑提交分组、性格与显示值并在成功后刷新草稿", async () => {
    const applied = makeAttributeResult({ changed_players: 18 });
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) return jsonResponse(applied);
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    const panel = await screen.findByRole("region", { name: "批量属性编辑" });
    fireEvent.change(within(panel).getByLabelText("显示值"), { target: { value: "12" } });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "门将" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: "包含性格" }));
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    const [call] = attributeCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1/attributes");
    expect(call.init.method).toBe("POST");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(call.init.body))).toEqual({
      side: "home",
      scope: "all",
      operation: "bulk",
      params: {
        value: 12,
        groups: ["technical", "mental", "physical"],
        include_personality: true,
      },
    });

    const notice = await screen.findByText("已更新 18 名球员");
    expect(notice).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(detailCalls()).toHaveLength(2));
  });

  it("位置操作按客队首发提交位置与熟练度", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) return jsonResponse(makeAttributeResult({ changed_players: 11 }));
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    await screen.findByRole("region", { name: "批量属性编辑" });
    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    const panel = screen.getByRole("region", { name: "批量属性编辑" });
    fireEvent.change(within(panel).getByRole("combobox", { name: "操作" }), {
      target: { value: "position" },
    });
    fireEvent.change(within(panel).getByRole("combobox", { name: "范围" }), {
      target: { value: "starters" },
    });
    fireEvent.change(within(panel).getByRole("combobox", { name: "位置" }), {
      target: { value: "ST" },
    });
    fireEvent.change(within(panel).getByLabelText("位置熟练度"), { target: { value: "9" } });
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "away",
      scope: "starters",
      operation: "position",
      params: { position: "ST", value: 9 },
    });
    expect(await screen.findByText("已更新 11 名球员")).toBeInTheDocument();
  });

  it("复制操作提交当前球员范围与参考球员标识", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) return jsonResponse(makeAttributeResult({ changed_players: 1 }));
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.click(within(homeRoster).getByRole("button", { name: /主队球员 03/ }));
    const panel = screen.getByRole("region", { name: "批量属性编辑" });
    fireEvent.change(within(panel).getByRole("combobox", { name: "操作" }), {
      target: { value: "copy" },
    });
    fireEvent.change(within(panel).getByRole("combobox", { name: "范围" }), {
      target: { value: "player" },
    });
    fireEvent.change(within(panel).getByRole("combobox", { name: "参考球员" }), {
      target: { value: "1" },
    });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "门将" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: "复制性格" }));
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "home",
      scope: "player",
      player_index: 2,
      operation: "copy",
      params: {
        source_uid: 101,
        groups: ["technical", "mental", "physical"],
        copy_personality: false,
      },
    });
  });

  it("撤销按钮提交 undo 操作并刷新草稿", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) return jsonResponse(makeAttributeResult());
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    const panel = await screen.findByRole("region", { name: "批量属性编辑" });
    fireEvent.click(within(panel).getByRole("button", { name: "撤销" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "home",
      scope: "all",
      operation: "undo",
      params: {},
    });
    expect(await screen.findByText("已更新 23 名球员")).toBeInTheDocument();
    await waitFor(() => expect(detailCalls()).toHaveLength(2));
  });

  it("批量编辑失败时展示后端错误信息且不刷新草稿", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) {
        return jsonResponse(
          { error: { code: "validation_failed", message: "属性显示值必须在 1–20 之间" } },
          400,
        );
      }
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    const panel = await screen.findByRole("region", { name: "批量属性编辑" });
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("属性显示值必须在 1–20 之间");
    expect(screen.queryByText(/已更新/)).not.toBeInTheDocument();
    expect(detailCalls()).toHaveLength(1);
  });
});

describe("草稿 API 客户端", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listDrafts 携带分页查询与鉴权", async () => {
    stubFetch(() => jsonResponse(makeDraftList([makeSummary()], 3, 2)));

    const result = await listDrafts(connection, { limit: 2, offset: 4 });

    expect(result.total).toBe(3);
    expect(result.next_offset).toBe(2);
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts?limit=2&offset=4");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("getDraft 请求编码后的草稿 ID 并返回场景", async () => {
    stubFetch(() => jsonResponse(makeDraft({ id: "draft/1" })));

    const draft = await getDraft(connection, "draft/1");

    expect(draft.scenario).toEqual(makeScenario());
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft%2F1");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("getDraft 透出后端错误封套", async () => {
    stubFetch(() =>
      jsonResponse({ error: { code: "not_found", message: "draft not found" } }, 404),
    );

    await expect(getDraft(connection, "missing")).rejects.toMatchObject({
      message: "draft not found",
      status: 404,
      code: "not_found",
    });
  });

  it("createDraft 使用 POST 提交名称与场景", async () => {
    stubFetch(() => jsonResponse(makeDraft()));

    await createDraft(connection, {
      name: "草案一",
      scenario: makeScenario(),
      source: { kind: "inline" },
    });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts");
    expect(call.init.method).toBe("POST");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(call.init.body))).toEqual({
      name: "草案一",
      scenario: makeScenario(),
      source: { kind: "inline" },
    });
  });

  it("updateDraft 使用 PATCH 提交变更", async () => {
    stubFetch(() => jsonResponse(makeDraft({ name: "草案二" })));

    await updateDraft(connection, "draft-1", { name: "草案二" });

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1");
    expect(call.init.method).toBe("PATCH");
    expect(JSON.parse(String(call.init.body))).toEqual({ name: "草案二" });
  });

  it("deleteDraft 使用 DELETE 并接受 204", async () => {
    stubFetch(() => noContentResponse());

    await expect(deleteDraft(connection, "draft-1")).resolves.toBeUndefined();

    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1");
    expect(call.init.method).toBe("DELETE");
  });

  it("applyDraftAttributes 使用 POST 提交属性操作", async () => {
    stubFetch(() => jsonResponse(makeAttributeResult({ changed_players: 7 })));

    const result = await applyDraftAttributes(connection, "draft/1", {
      side: "away",
      scope: "player",
      player_index: 6,
      operation: "position",
      params: { position: "ST", value: 9 },
    });

    expect(result.changed_players).toBe(7);
    const [call] = fetchCalls();
    expect(call.url).toBe("http://127.0.0.1:43210/api/drafts/draft%2F1/attributes");
    expect(call.init.method).toBe("POST");
    expect(new Headers(call.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(call.init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(call.init.body))).toEqual({
      side: "away",
      scope: "player",
      player_index: 6,
      operation: "position",
      params: { position: "ST", value: 9 },
    });
  });
});
