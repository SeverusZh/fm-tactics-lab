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
  generatedIndexes: readonly number[] = [],
  generatedOverrides: Readonly<Record<number, unknown>> = {},
): Record<string, unknown> {
  return {
    name,
    players: Array.from({ length: 23 }, (_, index) => {
      if (generatedIndexes.includes(index)) {
        return {
          source_uid: `generated:${index + 1}`,
          name: `占位球员 ${index + 1}`,
          attributes: makeAttributes(),
          ability: 10,
          generated: index in generatedOverrides ? generatedOverrides[index] : true,
        };
      }
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

type TrimScenarioOptions = {
  home?: Record<string, unknown>;
  away?: Record<string, unknown>;
  homeGenerated?: readonly number[];
  awayGenerated?: readonly number[];
};

function makeTrimScenario(options: TrimScenarioOptions = {}): Record<string, unknown> {
  const home = makeTeam("主队", 100, HOME_FIRST, 88, options.homeGenerated ?? []);
  const away = makeTeam("客队", 200, AWAY_FIRST, { current: 70 }, options.awayGenerated ?? []);
  if (options.home !== undefined) home.roster_trim = options.home;
  if (options.away !== undefined) away.roster_trim = options.away;
  return { schema: 4, teams: [home, away] };
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

function rosterNotice(): HTMLElement | null {
  return screen.queryByRole("status", { name: "名单兼容提示" });
}

function detailRegion(): HTMLElement {
  return screen.getByRole("region", { name: "选中球员属性" });
}

function displayedAttribute(label: string): string {
  return cellInput(label).value;
}

function cellInput(label: string): HTMLInputElement {
  const term = screen.getByText(label, { selector: "dt" });
  const input = term.parentElement?.querySelector<HTMLInputElement>("dd input");
  if (input === null || input === undefined) throw new Error("未找到属性输入：" + label);
  return input;
}

function advancedDetails(): HTMLDetailsElement {
  const details = document.querySelector<HTMLDetailsElement>("details.players-advanced");
  if (details === null) throw new Error("未找到高级批量工具");
  return details;
}

async function openBulkTools(): Promise<HTMLElement> {
  await screen.findByRole("complementary", { name: /球员名单/ });
  advancedDetails().open = true;
  return screen.getByRole("region", { name: "批量属性编辑" });
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

    const panel = await openBulkTools();
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

    await openBulkTools();
    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    const panel = await openBulkTools();
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
    const panel = await openBulkTools();
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

    const panel = await openBulkTools();
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

    const panel = await openBulkTools();
    fireEvent.change(within(panel).getByLabelText("显示值"), { target: { value: "12" } });
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("属性显示值必须在 1–20 之间");
    expect(screen.queryByText(/已更新/)).not.toBeInTheDocument();
    expect(detailCalls()).toHaveLength(1);
  });
});

describe("球员名单兼容与占位提示", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("原始名单超过 23 人时提示裁剪人数与移除人数", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: {
              source_size: 26,
              removed: [
                { source_uid: 1, name: "离队球员 1" },
                { source_uid: 2, name: "离队球员 2" },
                { source_uid: 3, name: "离队球员 3" },
                "invalid-entry",
                7,
              ],
              generated: [],
            },
          }),
        }),
      ),
    );
    renderPlayersPage();

    const notice = await screen.findByRole("status", { name: "名单兼容提示" });
    expect(notice).toHaveTextContent("原始名单 26 人，已按 23 人裁剪，移除 3 人");

    const homeRoster = roster("主队球员名单");
    expect(within(homeRoster).getAllByRole("button")).toHaveLength(23);
    const panel = screen.getByRole("region", { name: "批量属性编辑" });
    expect(
      notice.compareDocumentPosition(homeRoster) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      notice.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("原始名单不足 23 人时提示占位球员补足 23 人", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: {
              source_size: 20,
              removed: [],
              generated: ["generated:1", "generated:2", "generated:3"],
            },
          }),
        }),
      ),
    );
    renderPlayersPage();

    expect(await screen.findByRole("status", { name: "名单兼容提示" })).toHaveTextContent(
      "原始名单 20 人，已用 3 名占位球员补足 23 人",
    );
  });

  it("缺少原始人数时提示占位球员数量", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: { generated: ["generated:1", "generated:2"] },
            homeGenerated: [0, 1],
          }),
        }),
      ),
    );
    renderPlayersPage();

    expect(await screen.findByRole("status", { name: "名单兼容提示" })).toHaveTextContent(
      "名单含 2 名占位球员",
    );
    expect(within(roster("主队球员名单")).getAllByRole("button")).toHaveLength(23);
  });

  it("原始名单为 23 人的真实名单不渲染兼容提示区", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: { source_size: 23, removed: [], generated: [] },
          }),
        }),
      ),
    );
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(rosterNotice()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    await screen.findByRole("complementary", { name: "客队球员名单" });
    expect(rosterNotice()).toBeNull();
  });

  it("原始人数为 23 但含占位球员时不渲染兼容提示区", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: { source_size: 23, removed: [], generated: ["generated:1"] },
          }),
        }),
      ),
    );
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(rosterNotice()).toBeNull();
  });

  it("roster_trim 畸形时名单正常渲染且不显示兼容提示", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: { source_size: "26", removed: "invalid", generated: "invalid" },
            away: { source_size: -5, removed: { invalid: true }, generated: { invalid: true } },
          }),
        }),
      ),
    );
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getAllByRole("button")).toHaveLength(23);
    expect(rosterNotice()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    const awayRoster = await screen.findByRole("complementary", { name: "客队球员名单" });
    expect(within(awayRoster).getAllByRole("button")).toHaveLength(23);
    expect(rosterNotice()).toBeNull();
  });

  it("主客切换后兼容提示跟随当前球队数据", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: {
              source_size: 26,
              removed: [
                { source_uid: 1, name: "离队球员 1" },
                { source_uid: 2, name: "离队球员 2" },
              ],
              generated: [],
            },
            away: { source_size: 21, removed: [], generated: ["generated:1", "generated:2"] },
          }),
        }),
      ),
    );
    renderPlayersPage();

    expect(await screen.findByRole("status", { name: "名单兼容提示" })).toHaveTextContent(
      "原始名单 26 人，已按 23 人裁剪，移除 2 人",
    );

    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    expect(await screen.findByRole("status", { name: "名单兼容提示" })).toHaveTextContent(
      "原始名单 21 人，已用 2 名占位球员补足 23 人",
    );

    fireEvent.click(screen.getByRole("button", { name: "主队" }));
    expect(await screen.findByRole("status", { name: "名单兼容提示" })).toHaveTextContent(
      "原始名单 26 人，已按 23 人裁剪，移除 2 人",
    );
  });

  it("占位球员在名单行与选中标题显示占位标识", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({ homeGenerated: [0, 1] }),
        }),
      ),
    );
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getAllByText("占位")).toHaveLength(2);

    const generatedRow = within(homeRoster).getByRole("button", { name: /占位球员 1/ });
    expect(within(generatedRow).getByText("占位")).toBeInTheDocument();

    const realRow = within(homeRoster).getByRole("button", { name: /主队球员 03/ });
    expect(within(realRow).queryByText("占位")).toBeNull();

    const detail = detailRegion();
    expect(within(detail).getByText("占位球员 1")).toBeInTheDocument();
    expect(within(detail).getByText("占位")).toBeInTheDocument();
  });

  it("原始名单超过 23 人且含占位球员时追加占位数量说明", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: {
              source_size: 26,
              removed: [
                { source_uid: 1, name: "离队球员 1" },
                { source_uid: 2, name: "离队球员 2" },
              ],
              generated: ["generated:1", "generated:2"],
            },
            homeGenerated: [0, 1],
          }),
        }),
      ),
    );
    renderPlayersPage();

    const notice = await screen.findByRole("status", { name: "名单兼容提示" });
    expect(notice.textContent).toBe(
      "原始名单 26 人，已按 23 人裁剪，移除 2 人，其中 2 名为占位球员",
    );
  });

  it("原始人数不是整数时降级且不渲染兼容提示", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({
            home: { source_size: 23.5, removed: [], generated: [] },
          }),
        }),
      ),
    );
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getAllByRole("button")).toHaveLength(23);
    expect(rosterNotice()).toBeNull();
    expect(screen.queryByText(/23\.5/)).toBeNull();
  });

  it("占位标识仅在球员 generated 严格为真时显示", async () => {
    const home = makeTeam("主队", 100, HOME_FIRST, 88, [0, 1, 2], { 0: 1, 1: "yes" });
    const away = makeTeam("客队", 200, AWAY_FIRST, { current: 70 });
    stubFetch(draftHandlers(makeDraft({ scenario: { schema: 4, teams: [home, away] } })));
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getAllByText("占位")).toHaveLength(1);

    const truthyRow = within(homeRoster).getByRole("button", { name: /占位球员 1/ });
    expect(within(truthyRow).queryByText("占位")).toBeNull();

    const strictRow = within(homeRoster).getByRole("button", { name: /占位球员 3/ });
    expect(within(strictRow).getByText("占位")).toBeInTheDocument();

    expect(within(detailRegion()).queryByText("占位")).toBeNull();
  });

  it("主客切换后占位标识跟随当前球队数据", async () => {
    stubFetch(
      draftHandlers(
        makeDraft({
          scenario: makeTrimScenario({ homeGenerated: [0, 1], awayGenerated: [0] }),
        }),
      ),
    );
    renderPlayersPage();

    const homeRoster = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeRoster).getAllByText("占位")).toHaveLength(2);
    expect(within(detailRegion()).getByText("占位")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    const awayRoster = await screen.findByRole("complementary", { name: "客队球员名单" });
    expect(within(awayRoster).getAllByText("占位")).toHaveLength(1);
    expect(within(detailRegion()).getByText("占位")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "主队" }));
    const homeAgain = await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(homeAgain).getAllByText("占位")).toHaveLength(2);
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

describe("球员单项属性编辑", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function attributeHandlers(changedPlayers = 1) {
    return (url: string) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) {
        return jsonResponse(makeAttributeResult({ changed_players: changedPlayers }));
      }
      return jsonResponse(makeDraft());
    };
  }

  it("属性格以显示值渲染可编辑数字输入", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });

    const crossing = screen.getByRole("spinbutton", { name: "传中" });
    expect(crossing).toHaveValue(15.6);
    expect(crossing).toHaveAttribute("type", "number");
    expect(crossing).toHaveAttribute("step", "0.2");
    expect(crossing).toHaveAttribute("min", "1");
    expect(crossing).toHaveAttribute("max", "20");

    const goalkeeper = screen.getByRole("spinbutton", { name: "门将" });
    expect(goalkeeper).toHaveValue(5);
    expect(goalkeeper).toHaveAttribute("step", "1");
    expect(goalkeeper).toHaveAttribute("min", "0");

    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });

  it("修改单个属性后标记 dirty 并出现保存与放弃按钮", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });

    expect(cellInput("传中")).toHaveValue(14);
    expect(screen.getByText("已修改 1 项")).toBeInTheDocument();
    expect(screen.getByText("已修改")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存修改（1）" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "放弃" })).toBeEnabled();
  });

  it("保存只提交改动格并刷新草稿", async () => {
    stubFetch(attributeHandlers(1));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    fireEvent.change(cellInput("门将"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（2）" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "home",
      scope: "player",
      player_index: 0,
      operation: "cells",
      params: { values: { "0": 7, "15": 14 } },
    });
    expect(await screen.findByText("已更新 2 项属性")).toBeInTheDocument();
    await waitFor(() => expect(detailCalls()).toHaveLength(2));
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });

  it("客队第二名球员保存提交对应 side 与 player_index", async () => {
    stubFetch(attributeHandlers(1));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    const awayRoster = await screen.findByRole("complementary", { name: "客队球员名单" });
    fireEvent.click(within(awayRoster).getByRole("button", { name: /客队球员 02/ }));

    fireEvent.change(cellInput("门将"), { target: { value: "7" } });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（2）" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "away",
      scope: "player",
      player_index: 1,
      operation: "cells",
      params: { values: { "0": 7, "15": 14 } },
    });
    expect(await screen.findByText("已更新 2 项属性")).toBeInTheDocument();
    await waitFor(() => expect(detailCalls()).toHaveLength(2));
  });

  it("改回原值后清除改动状态", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    fireEvent.change(cellInput("传中"), { target: { value: "15.6" } });

    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
    expect(attributeCalls()).toHaveLength(0);
  });

  it("点击放弃后恢复原值并清除改动标记", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    expect(screen.getByText("已修改 1 项")).toBeInTheDocument();
    expect(screen.getByText("已修改")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "放弃" }));

    expect(cellInput("传中")).toHaveValue(15.6);
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
    expect(screen.queryByText("已修改 1 项")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
    expect(attributeCalls()).toHaveLength(0);
  });

  it("显示值越界阻止保存并提示", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "21" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("属性“传中”必须是 1–20 之间的显示值");
    expect(alert).toHaveAttribute("id", "players-cell-error");
    expect(cellInput("传中")).toHaveAttribute("aria-invalid", "true");
    expect(cellInput("传中")).toHaveAttribute("aria-describedby", "players-cell-error");
    expect(cellInput("门将")).not.toHaveAttribute("aria-invalid");
    expect(attributeCalls()).toHaveLength(0);
    expect(cellInput("传中")).toHaveValue(21);
    expect(screen.getByRole("button", { name: "保存修改（1）" })).toBeInTheDocument();

    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(cellInput("传中")).not.toHaveAttribute("aria-invalid");
    expect(cellInput("传中")).not.toHaveAttribute("aria-describedby");
  });

  it("位置熟练度必须为 0–20 的整数", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("门将"), { target: { value: "10.5" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    expect(screen.getByRole("alert")).toHaveTextContent("属性“门将”必须是 0–20 的整数");
    expect(attributeCalls()).toHaveLength(0);
  });

  it("显示值必须按 0.2 步进", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14.3" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    expect(screen.getByRole("alert")).toHaveTextContent("属性“传中”必须以 0.2 为步进");
    expect(attributeCalls()).toHaveLength(0);
  });

  it("清空属性输入后不能保存并展示原因", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    expect(screen.getByRole("alert")).toHaveTextContent("属性“传中”不能为空");
    expect(attributeCalls()).toHaveLength(0);
    expect(cellInput("传中").value).toBe("");
    expect(screen.getByText("已修改 1 项")).toBeInTheDocument();
  });

  it("保存进行中禁用保存与放弃并展示进行中文案", async () => {
    const pending = deferred<Response>();
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) return pending.promise;
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(screen.getByRole("button", { name: "保存修改（1）" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "放弃" })).toBeDisabled();
    expect(screen.getByText("正在保存…")).toBeInTheDocument();
    expect(cellInput("传中")).toBeDisabled();

    pending.resolve(jsonResponse(makeAttributeResult({ changed_players: 1 })));
    expect(await screen.findByText("已更新 1 项属性")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument(),
    );
  });

  it("等值不同写法不标记为改动", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "15.60" } });
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();

    fireEvent.change(cellInput("门将"), { target: { value: "5.0" } });
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();

    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    expect(screen.getByText("已修改 1 项")).toBeInTheDocument();
  });

  it("保存失败时展示后端消息并保留 dirty", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      if (url.endsWith("/attributes")) {
        return jsonResponse(
          { error: { code: "validation_failed", message: "至少需要一个属性值" } },
          400,
        );
      }
      return jsonResponse(makeDraft());
    });
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("至少需要一个属性值");
    expect(cellInput("传中")).not.toHaveAttribute("aria-invalid");
    expect(cellInput("传中")).toHaveValue(14);
    expect(screen.getByText("已修改 1 项")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存修改（1）" })).toBeInTheDocument();
    expect(detailCalls()).toHaveLength(1);
  });

  it("存在未保存修改时阻止 beforeunload 关闭且放弃后解除", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    const cleanEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "放弃" }));
    const discardedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(discardedEvent);
    expect(discardedEvent.defaultPrevented).toBe(false);
  });

  it("保存成功后解除 beforeunload 守卫", async () => {
    stubFetch(attributeHandlers(1));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }));
    expect(await screen.findByText("已更新 1 项属性")).toBeInTheDocument();
    await waitFor(() => {
      const savedEvent = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(savedEvent);
      expect(savedEvent.defaultPrevented).toBe(false);
    });
  });

  it("切换球员前确认未保存修改", async () => {
    stubFetch(draftHandlers());
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });

    fireEvent.click(within(roster("主队球员名单")).getByRole("button", { name: /主队球员 02/ }));
    expect(confirmSpy).toHaveBeenCalledWith("有 1 项属性修改尚未保存，确定放弃吗？");
    expect(within(detailRegion()).getByText("主队球员 01")).toBeInTheDocument();
    expect(cellInput("传中")).toHaveValue(14);

    confirmSpy.mockReturnValue(true);
    fireEvent.click(within(roster("主队球员名单")).getByRole("button", { name: /主队球员 02/ }));
    expect(within(detailRegion()).getByText("主队球员 02")).toBeInTheDocument();
    expect(cellInput("传中")).toHaveValue(12);
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
  });

  it("切换草稿前确认未保存修改", async () => {
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
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPlayersPage();

    const select = await screen.findByRole("combobox", { name: "选择草稿" });
    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });

    fireEvent.change(select, { target: { value: "draft-2" } });
    expect(select).toHaveValue("draft-1");
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(0);
    expect(cellInput("传中")).toHaveValue(14);

    confirmSpy.mockReturnValue(true);
    fireEvent.change(select, { target: { value: "draft-2" } });
    await screen.findByRole("complementary", { name: "主队球员名单" });
    expect(within(roster("主队球员名单")).getByText("主队乙球员 01")).toBeInTheDocument();
    expect(select).toHaveValue("draft-2");
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
  });

  it("切换主客队前确认未保存修改", async () => {
    stubFetch(draftHandlers());
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("门将"), { target: { value: "7" } });

    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    expect(confirmSpy).toHaveBeenCalledWith("有 1 项属性修改尚未保存，确定放弃吗？");
    expect(screen.getByRole("button", { name: "主队" })).toHaveAttribute("aria-pressed", "true");
    expect(cellInput("门将")).toHaveValue(7);

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    await screen.findByRole("complementary", { name: "客队球员名单" });
    expect(cellInput("门将")).toHaveValue(20);
    expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument();
  });

  it("撤销批量工具同时清空单项编辑", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    stubFetch(attributeHandlers(23));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    const panel = await openBulkTools();
    fireEvent.click(within(panel).getByRole("button", { name: "撤销" }));

    expect(confirmSpy).toHaveBeenCalledWith(
      "有 1 项单项属性修改尚未保存，继续该操作将放弃这些修改，确定继续吗？",
    );

    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "home",
      scope: "all",
      operation: "undo",
      params: {},
    });
    expect(await screen.findByText("已更新 23 名球员")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument(),
    );
    expect(cellInput("传中")).toHaveValue(15.6);
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });

  it("有未保存单项编辑时批量应用需确认，取消则保留编辑且不发请求", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    stubFetch(attributeHandlers(1));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    const panel = await openBulkTools();
    fireEvent.change(within(panel).getByLabelText("显示值"), { target: { value: "12" } });
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    expect(confirmSpy).toHaveBeenCalledWith(
      "有 1 项单项属性修改尚未保存，继续该操作将放弃这些修改，确定继续吗？",
    );
    expect(attributeCalls()).toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存修改（1）" })).toBeEnabled();
    expect(cellInput("传中")).toHaveValue(14);
  });

  it("确认后批量应用提交并清空单项编辑", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    stubFetch(attributeHandlers(18));
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });
    fireEvent.change(cellInput("传中"), { target: { value: "14" } });
    const panel = await openBulkTools();
    fireEvent.change(within(panel).getByLabelText("显示值"), { target: { value: "12" } });
    fireEvent.click(within(panel).getByRole("button", { name: "应用" }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(attributeCalls()).toHaveLength(1));
    expect(JSON.parse(String(attributeCalls()[0].init.body))).toEqual({
      side: "home",
      scope: "all",
      operation: "bulk",
      params: {
        value: 12,
        groups: ["technical", "mental", "physical", "goalkeeping"],
        include_personality: false,
      },
    });
    expect(await screen.findByText("已更新 18 名球员")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /保存修改/ })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });

  it("高级批量工具默认收起且不预填显示值", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    await screen.findByRole("complementary", { name: "主队球员名单" });

    const details = advancedDetails();
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")).toHaveTextContent("高级批量工具");

    details.open = true;
    const panel = screen.getByRole("region", { name: "批量属性编辑" });
    const displayValue = within(panel).getByLabelText("显示值") as HTMLInputElement;
    expect(displayValue.value).toBe("");
    expect(within(panel).getByRole("button", { name: "应用" })).toBeDisabled();

    fireEvent.change(within(panel).getByRole("combobox", { name: "操作" }), {
      target: { value: "position" },
    });
    const positionValue = within(panel).getByLabelText("位置熟练度") as HTMLInputElement;
    expect(positionValue.value).toBe("");
    expect(within(panel).getByRole("button", { name: "应用" })).toBeDisabled();
  });

  it("批量工具禁用时展示具体原因并在参数合法后消失", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    const panel = await openBulkTools();
    const applyButton = () => within(panel).getByRole("button", { name: "应用" });
    expect(applyButton()).toBeDisabled();
    expect(screen.getByText("请输入要应用的显示值")).toBeInTheDocument();

    const displayValue = within(panel).getByLabelText("显示值");
    fireEvent.change(displayValue, { target: { value: "21" } });
    expect(screen.getByText("显示值需为 1–20 且按 0.2 步进")).toBeInTheDocument();
    expect(applyButton()).toBeDisabled();

    fireEvent.change(displayValue, { target: { value: "14.3" } });
    expect(screen.getByText("显示值需为 1–20 且按 0.2 步进")).toBeInTheDocument();
    expect(applyButton()).toBeDisabled();

    fireEvent.change(displayValue, { target: { value: "12" } });
    expect(screen.queryByText("显示值需为 1–20 且按 0.2 步进")).not.toBeInTheDocument();
    expect(applyButton()).toBeEnabled();

    for (const name of ["技术", "精神", "身体", "门将"]) {
      fireEvent.click(within(panel).getByRole("checkbox", { name }));
    }
    expect(screen.getByText("请至少选择一个分组")).toBeInTheDocument();
    expect(applyButton()).toBeDisabled();

    fireEvent.click(within(panel).getByRole("checkbox", { name: "技术" }));
    expect(screen.queryByText("请至少选择一个分组")).not.toBeInTheDocument();
    expect(applyButton()).toBeEnabled();
  });

  it("位置熟练度禁用原因展示并在合法后消失", async () => {
    stubFetch(draftHandlers());
    renderPlayersPage();

    const panel = await openBulkTools();
    fireEvent.change(within(panel).getByRole("combobox", { name: "操作" }), {
      target: { value: "position" },
    });
    expect(within(panel).getByRole("button", { name: "应用" })).toBeDisabled();
    expect(screen.getByText("请输入要应用的位置熟练度")).toBeInTheDocument();

    const positionInput = within(panel).getByLabelText("位置熟练度");
    fireEvent.change(positionInput, { target: { value: "10.5" } });
    expect(screen.getByText("位置熟练度需为 0–20 的整数")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "应用" })).toBeDisabled();

    fireEvent.change(positionInput, { target: { value: "21" } });
    expect(screen.getByText("位置熟练度需为 0–20 的整数")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "应用" })).toBeDisabled();

    fireEvent.change(positionInput, { target: { value: "10" } });
    expect(screen.queryByText("位置熟练度需为 0–20 的整数")).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "应用" })).toBeEnabled();
  });
});
