import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext } from "../app-context";
import {
  getCatalog,
  getDraft,
  listDrafts,
  type Draft,
  type DraftList,
  type DraftSummary,
  type Health,
} from "../lib/api";
import type { Connection } from "../lib/connection";
import { TacticsPage } from "./TacticsPage";

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

const CATALOG_RESPONSE = {
  available: true,
  catalog: {
    positions: [
      { id: "GK", x: 50, y: 92 },
      { id: "ST", x: 50, y: 12 },
    ],
    roles: [
      { id: "Goalkeeper", label: "门将" },
      { id: "FullBack", label: "边后卫" },
      { id: "CentreBack", label: "中后卫" },
      { id: "DefensiveMidfielder", label: "防守型中场" },
      { id: "CentralMidfielder", label: "中前卫" },
      { id: "Winger", label: "边锋" },
      { id: "CentreForward", label: "中锋" },
      { id: "OPCentreForward", label: "无球中锋" },
    ],
    team_instructions: [
      {
        id: 1,
        name: "PassingDirectness",
        label: "传球倾向",
        possession_phase: 0,
        options: [
          { id: 1483944022, label: "直接传球" },
          { id: 1146434657, label: "短传" },
        ],
      },
      {
        id: 4,
        name: "AttackingWidth",
        label: "进攻宽度",
        possession_phase: 0,
        options: [{ id: 1716541542, label: "偏窄" }],
      },
      {
        id: 9,
        name: "DefensiveLine",
        label: "防线高度",
        possession_phase: 1,
        options: [{ id: 894978671, label: "较高" }],
      },
      {
        id: 22,
        name: "DefendingCrosses",
        label: "防守传中",
        possession_phase: 1,
        options: [{ id: 1123, label: "限制" }],
      },
    ],
    mentalities: [
      { id: 3, label: "谨慎" },
      { id: 5, label: "进取" },
      { id: 6, label: "进攻" },
    ],
  },
};

const CATALOG_UNAVAILABLE = { available: false, catalog: null };
const CATALOG_PHASE_MATRIX = {
  available: true,
  catalog: {
    positions: [],
    roles: [],
    team_instructions: [
      { id: 40, label: "优先有球", possession_phase: 0, phase: 1, options: [{ id: 1, label: "值一" }] },
      { id: 41, label: "回退有球", phase: 0, options: [{ id: 2, label: "值二" }] },
      { id: 42, label: "优先无球", possession_phase: 1, phase: 0, options: [{ id: 3, label: "值三" }] },
      { id: 43, label: "回退无球", phase: 1, options: [{ id: 4, label: "值四" }] },
      { id: 44, label: "无阶段标记", options: [{ id: 5, label: "值五" }] },
      { id: 45, label: "真实无球形态", possession_phase: 1, phase: 4, options: [{ id: 6, label: "值六" }] },
    ],
    mentalities: [],
  },
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

function stubCompactViewport(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })) as unknown as typeof window.matchMedia;
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

type Cell = { position: string; role: string };

const HOME_POSSESSION: Cell[] = [
  { position: "GK", role: "Goalkeeper" },
  { position: "DR", role: "FullBack" },
  { position: "DCR", role: "CentreBack" },
  { position: "DCL", role: "CentreBack" },
  { position: "DL", role: "FullBack" },
  { position: "DMC", role: "DefensiveMidfielder" },
  { position: "MCR", role: "CentralMidfielder" },
  { position: "MCL", role: "CentralMidfielder" },
  { position: "AMR", role: "Winger" },
  { position: "AML", role: "Winger" },
  { position: "ST", role: "CentreForward" },
];

const HOME_OUT_OF_POSSESSION: Cell[] = [
  { position: "GK", role: "Goalkeeper" },
  { position: "DR", role: "OPFullBack" },
  { position: "DCR", role: "OPCentreBack" },
  { position: "DCL", role: "OPCentreBack" },
  { position: "DL", role: "OPFullBack" },
  { position: "DMC", role: "OPScreeningDefensiveMidfielder" },
  { position: "MR", role: "OPWideMidfielder" },
  { position: "MC", role: "OPCentralMidfielder" },
  { position: "ML", role: "OPWideMidfielder" },
  { position: "AMC", role: "OPAttackingMidfielder" },
  { position: "ST", role: "OPCentreForward" },
];

const AWAY_POSSESSION: Cell[] = [
  { position: "GK", role: "Goalkeeper" },
  { position: "DR", role: "FullBack" },
  { position: "DCR", role: "CentreBack" },
  { position: "DCL", role: "CentreBack" },
  { position: "DL", role: "FullBack" },
  { position: "MR", role: "WideMidfielder" },
  { position: "MCR", role: "CentralMidfielder" },
  { position: "MCL", role: "CentralMidfielder" },
  { position: "ML", role: "WideMidfielder" },
  { position: "STR", role: "CentreForward" },
  { position: "STL", role: "CentreForward" },
];

const AWAY_OUT_OF_POSSESSION: Cell[] = [
  { position: "GK", role: "Goalkeeper" },
  { position: "DR", role: "OPFullBack" },
  { position: "DCR", role: "OPCentreBack" },
  { position: "DCL", role: "OPCentreBack" },
  { position: "DL", role: "OPFullBack" },
  { position: "MR", role: "OPWideMidfielder" },
  { position: "MCR", role: "OPCentralMidfielder" },
  { position: "MCL", role: "OPCentralMidfielder" },
  { position: "ML", role: "OPWideMidfielder" },
  { position: "STR", role: "OPCentreForward" },
  { position: "STL", role: "OPCentreForward" },
];

function makeAssignments(cells: Cell[]) {
  return cells.map((cell) => ({
    ...cell,
    duty: "Defend",
    instructions: {},
    target_player: 255,
    target_position: 0,
  }));
}

function makePlan(
  phase: "in_possession" | "out_of_possession",
  cells: Cell[],
  instructions: Record<string, number>,
) {
  return { phase, team_instructions: instructions, assignments: makeAssignments(cells) };
}

function makePlayers(teamName: string, uidBase: number) {
  return Array.from({ length: 23 }, (_, index) => ({
    source_uid: uidBase + index,
    name: `${teamName}球员 ${String(index + 1).padStart(2, "0")}`,
    attributes: new Array<number>(69).fill(10),
  }));
}

function makeTeam(
  name: string,
  uidBase: number,
  possession: Cell[],
  outOfPossession: Cell[],
  possessionInstructions: Record<string, number>,
  outInstructions: Record<string, number>,
  mentality = 5,
) {
  return {
    name,
    mentality,
    players: makePlayers(name, uidBase),
    lineup: Array.from({ length: 11 }, (_, index) => index),
    roster_size: 23,
    phase_plans: [
      makePlan("in_possession", possession, possessionInstructions),
      makePlan("out_of_possession", outOfPossession, outInstructions),
    ],
  };
}

function makeScenario(homeName = "北岸联", awayName = "南港队"): Record<string, unknown> {
  return {
    schema: 4,
    teams: [
      makeTeam(
        homeName,
        100,
        HOME_POSSESSION,
        HOME_OUT_OF_POSSESSION,
        { "1": 1483944022, "4": 1716541542, "99": 7 },
        { "9": 894978671, "22": 1123 },
      ),
      makeTeam(
        awayName,
        200,
        AWAY_POSSESSION,
        AWAY_OUT_OF_POSSESSION,
        { "1": 1146434657 },
        { "8": 927550517 },
        6,
      ),
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

function makeDraftList(items: DraftSummary[], total = items.length): DraftList {
  return { items, total, next_offset: null };
}

function renderTacticsPage(activeConnection: Connection | null = connection) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tactics"]}>
        <AppContext.Provider
          value={{
            connection: activeConnection,
            health,
            connectionError: null,
            refreshing: false,
            refresh: vi.fn(),
          }}
        >
          <TacticsPage />
        </AppContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function pitchSlots(): Promise<HTMLElement[]> {
  const board = await screen.findByRole("group", { name: /战术板/ });
  return within(board).getAllByRole("listitem");
}

function draftHandlers(
  details: Record<string, Draft> = {},
  catalogBody: unknown = CATALOG_UNAVAILABLE,
) {
  return (url: string) => {
    if (url.endsWith("/api/catalog")) return jsonResponse(catalogBody);
    if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
    const id = url.slice(url.lastIndexOf("/") + 1);
    const detail = details[id] ?? makeDraft({ id });
    return jsonResponse(detail);
  };
}

describe("TacticsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("加载草稿列表后请求首个草稿并渲染球场", async () => {
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
    renderTacticsPage();

    expect(screen.getByRole("status")).toHaveTextContent("正在加载草稿");
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("正在加载战术"),
    );

    pendingDetail.resolve(jsonResponse(makeDraft()));

    const loadingGrid = document.querySelector(".page-grid");
    expect(loadingGrid).not.toBeNull();
    expect(within(loadingGrid as HTMLElement).getByText("双阶段战术板")).toBeInTheDocument();
    expect(within(loadingGrid as HTMLElement).getByText("球队指令")).toBeInTheDocument();

    pendingDetail.resolve(jsonResponse(makeDraft()));

    const slots = await pitchSlots();
    expect(slots).toHaveLength(11);
    expect(within(slots[0]).getByText("北岸联球员 01")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");
    expect(document.querySelector(".tactics-skeleton")).toBeNull();

    const listCall = fetchCalls().find((call) => call.url.endsWith("/api/drafts"));
    const detailCall = fetchCalls().find((call) => call.url.endsWith("/api/drafts/draft-1"));
    expect(listCall?.url).toBe("http://127.0.0.1:43210/api/drafts");
    expect(new Headers(listCall?.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(detailCall?.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1");
    expect(new Headers(detailCall?.init.headers).get("Authorization")).toBe("Bearer test-token");
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
          makeDraft({ id: "draft-2", name: "草案二", scenario: makeScenario("西城队", "东城队") }),
        );
      }
      return jsonResponse(makeDraft());
    });
    renderTacticsPage();

    expect((await pitchSlots())[0]).toHaveTextContent("北岸联球员 01");

    fireEvent.change(screen.getByRole("combobox", { name: "选择草稿" }), {
      target: { value: "draft-2" },
    });

    await waitFor(() =>
      expect(screen.queryByText("北岸联球员 01")).not.toBeInTheDocument(),
    );
    const slots = await pitchSlots();
    expect(within(slots[0]).getByText("西城队球员 01")).toBeInTheDocument();
    expect(within(slots[0]).queryByText("北岸联球员 01")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2");
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(1);
  });

  it("默认展示有球阶段，切换无球阶段更新槽位与球队指令", async () => {
    stubFetch(draftHandlers());
    renderTacticsPage();

    const possessionSlots = await pitchSlots();
    expect(screen.getByRole("group", { name: "有球战术板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "有球" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "无球" })).toHaveAttribute("aria-pressed", "false");
    expect(within(possessionSlots[9]).getByText("AML")).toBeInTheDocument();
    expect(within(possessionSlots[10]).getByText("CentreForward")).toBeInTheDocument();
    expect(screen.getByText("传球方式")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "无球" }));

    expect(screen.getByRole("button", { name: "无球" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "有球" })).toHaveAttribute("aria-pressed", "false");
    const outSlots = await pitchSlots();
    expect(screen.getByRole("group", { name: "无球战术板" })).toBeInTheDocument();
    expect(within(outSlots[9]).getByText("AMC")).toBeInTheDocument();
    expect(within(outSlots[10]).getByText("OPCentreForward")).toBeInTheDocument();
    expect(within(outSlots[10]).queryByText("CentreForward")).not.toBeInTheDocument();
    expect(screen.getByText("防线高度")).toBeInTheDocument();
    expect(screen.queryByText("传球方式")).not.toBeInTheDocument();
  });


  it("catalog 指令按 possession_phase 优先过滤并回退 phase", async () => {
    const keys = ["40", "41", "42", "43", "44", "45"];
    const instructions = Object.fromEntries(keys.map((key, index) => [key, index + 1]));
    const scenario = makeScenario();
    const teams = scenario.teams as Array<Record<string, unknown>>;
    teams[0] = makeTeam(
      "北岸联",
      100,
      HOME_POSSESSION,
      HOME_OUT_OF_POSSESSION,
      instructions,
      instructions,
    );
    stubFetch((url) => {
      if (url.endsWith("/api/catalog")) return jsonResponse(CATALOG_PHASE_MATRIX);
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(makeDraft({ scenario }));
    });
    renderTacticsPage();

    const rowLabels = async () =>
      Array.from(document.querySelectorAll(".tactics-instruction dt")).map((node) => node.textContent);

    await pitchSlots();
    expect(await screen.findByText("优先有球")).toBeInTheDocument();
    expect(await rowLabels()).toEqual(["优先有球", "回退有球", "无阶段标记"]);
    expect(screen.queryByText("优先无球")).not.toBeInTheDocument();
    expect(screen.queryByText("回退无球")).not.toBeInTheDocument();
    expect(screen.queryByText("真实无球形态")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "无球" }));

    expect(await screen.findByText("优先无球")).toBeInTheDocument();
    expect(await rowLabels()).toEqual(["优先无球", "回退无球", "无阶段标记", "真实无球形态"]);
    expect(screen.queryByText("优先有球")).not.toBeInTheDocument();
    expect(screen.queryByText("回退有球")).not.toBeInTheDocument();
  });

  it("载入引擎目录后角色、球队指令与心态显示中文标签", async () => {
    stubFetch(draftHandlers({}, CATALOG_RESPONSE));
    renderTacticsPage();

    const slots = await pitchSlots();
    expect(await screen.findByText("门将")).toBeInTheDocument();
    expect(within(slots[0]).queryByText("Goalkeeper")).not.toBeInTheDocument();
    expect(within(slots[10]).getByText("中锋")).toBeInTheDocument();
    expect(within(slots[10]).queryByText("CentreForward")).not.toBeInTheDocument();
    expect(screen.getByText("传球倾向")).toBeInTheDocument();
    expect(screen.queryByText("传球方式")).not.toBeInTheDocument();
    expect(screen.getByText("直接传球")).toBeInTheDocument();
    expect(screen.queryByText("原生选项 #1483944022")).not.toBeInTheDocument();
    expect(screen.getByText("偏窄")).toBeInTheDocument();
    expect(screen.getByText("进取")).toBeInTheDocument();
    expect(screen.queryByText("积极")).not.toBeInTheDocument();
    expect(screen.getByText("原生选项 #7")).toBeInTheDocument();
    expect(
      screen.queryByText("未载入引擎目录，指令与角色显示原生编号"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "无球" }));

    expect(await screen.findByText("较高")).toBeInTheDocument();
    expect(screen.getByText("防守传中")).toBeInTheDocument();
    expect(screen.queryByText("直接传球")).not.toBeInTheDocument();
  });

  it("渲染 11 个槽位的球衣号、姓名、位置码与角色码", async () => {
    stubFetch(draftHandlers());
    renderTacticsPage();

    const slots = await pitchSlots();
    expect(slots).toHaveLength(11);
    expect(within(slots[0]).getByText("01")).toBeInTheDocument();
    expect(within(slots[0]).getByText("北岸联球员 01")).toBeInTheDocument();
    expect(within(slots[0]).getByText("GK")).toBeInTheDocument();
    expect(within(slots[0]).getByText("Goalkeeper")).toBeInTheDocument();
    expect(slots[0]).not.toHaveClass("tactics-slot--compact");
    expect(within(slots[10]).getByText("11")).toBeInTheDocument();
    expect(within(slots[10]).getByText("ST")).toBeInTheDocument();
    expect(within(slots[10]).getByText("北岸联球员 11")).toBeInTheDocument();
  });

  it("按位置表渲染球场坐标", async () => {
    stubFetch(draftHandlers());
    renderTacticsPage();

    const slots = await pitchSlots();
    expect(slots[0].style.left).toBe("50%");
    expect(slots[0].style.top).toBe("92%");
    expect(slots[1].style.left).toBe("86%");
    expect(slots[1].style.top).toBe("76%");
    expect(slots[4].style.left).toBe("14%");
    expect(slots[9].style.left).toBe("12%");
    expect(slots[10].style.left).toBe("50%");
    expect(slots[10].style.top).toBe("12%");
  });

  it("窄屏下槽位切换紧凑样式并隐藏姓名与角色文本", async () => {
    stubCompactViewport(true);
    stubFetch(draftHandlers({}, CATALOG_RESPONSE));
    renderTacticsPage();

    await pitchSlots();
    await waitFor(() => {
      expect(document.querySelectorAll(".tactics-slot--compact")).toHaveLength(11);
    });

    const board = screen.getByRole("group", { name: /战术板/ });
    const compactSlots = within(board).getAllByRole("listitem");
    expect(within(compactSlots[0]).getByText("01")).toBeInTheDocument();
    expect(within(compactSlots[0]).getByText("GK")).toBeInTheDocument();
    expect(within(compactSlots[0]).queryByText("北岸联球员 01")).not.toBeInTheDocument();
    expect(within(compactSlots[0]).queryByText("Goalkeeper")).not.toBeInTheDocument();
    expect(within(compactSlots[0]).queryByText("门将")).not.toBeInTheDocument();
    expect(compactSlots[0]).toHaveAttribute("title", expect.stringContaining("北岸联球员 01"));
    expect(compactSlots[0]).toHaveAttribute("title", expect.stringContaining("门将"));
  });

  it("主客切换展示对应球队球员与名称", async () => {
    stubFetch(draftHandlers());
    renderTacticsPage();

    expect((await pitchSlots())[0]).toHaveTextContent("北岸联球员 01");
    expect(screen.getByRole("button", { name: "主队" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("北岸联")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "客队" }));

    const awaySlots = await pitchSlots();
    expect(within(awaySlots[0]).getByText("南港队球员 01")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "客队" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "主队" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("南港队")).toBeInTheDocument();
    expect(within(awaySlots[9]).getByText("STR")).toBeInTheDocument();
    expect(screen.getByText("进攻")).toBeInTheDocument();
  });

  it("目录不可用时指令显示原生选项编号并提示降级", async () => {
    stubFetch(draftHandlers({}, { available: false, catalog: null }));
    renderTacticsPage();

    await pitchSlots();
    expect(
      await screen.findByText("未载入引擎目录，指令与角色显示原生编号"),
    ).toBeInTheDocument();
    expect(screen.getByText("心态")).toBeInTheDocument();
    expect(screen.getByText("积极")).toBeInTheDocument();
    expect(screen.getByText("传球方式")).toBeInTheDocument();
    expect(screen.getByText("原生选项 #1483944022")).toBeInTheDocument();
    expect(screen.getByText("进攻宽度")).toBeInTheDocument();
    expect(screen.getByText("原生选项 #1716541542")).toBeInTheDocument();
    expect(screen.getByText("99")).toBeInTheDocument();
    expect(screen.getByText("原生选项 #7")).toBeInTheDocument();
    expect(screen.queryByText("直接传球")).not.toBeInTheDocument();
  });

  it("目录请求失败时降级为原生编号且不显示错误", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/catalog")) {
        return jsonResponse({ error: { code: "http_error", message: "目录不可用" } }, 500);
      }
      return draftHandlers()(url);
    });
    renderTacticsPage();

    await pitchSlots();
    expect(
      await screen.findByText("未载入引擎目录，指令与角色显示原生编号"),
    ).toBeInTheDocument();
    expect(screen.getByText("原生选项 #1483944022")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("球队指令最多展示八项并提示未展示数量", async () => {
    const instructions = {
      "1": 11,
      "3": 12,
      "4": 13,
      "5": 14,
      "6": 15,
      "7": 16,
      "16": 17,
      "17": 18,
      "18": 19,
      "19": 20,
    };
    const scenario = makeScenario();
    const teams = scenario.teams as Array<Record<string, unknown>>;
    teams[0] = makeTeam(
      "北岸联",
      100,
      HOME_POSSESSION,
      HOME_OUT_OF_POSSESSION,
      instructions,
      {},
    );
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(makeDraft({ scenario }));
    });
    renderTacticsPage();

    await pitchSlots();
    expect(screen.getByText("传球方式")).toBeInTheDocument();
    expect(screen.getByText("门将出球速度")).toBeInTheDocument();
    expect(screen.queryByText("进攻耐心")).not.toBeInTheDocument();
    expect(screen.getByText("另有 2 项未显示")).toBeInTheDocument();
  });

  it("无草稿时显示空态与战术库入口且不请求详情", async () => {
    stubFetch(() => jsonResponse(makeDraftList([])));
    renderTacticsPage();

    expect(await screen.findByText("暂无草稿")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "选择草稿" })).not.toBeInTheDocument();
    expect(callsTo("/api/drafts/")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "前往战术库" })).toHaveAttribute("href", "/library");
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
    renderTacticsPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("草稿服务不可用");
    expect(screen.queryByRole("combobox", { name: "选择草稿" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect((await pitchSlots())[0]).toHaveTextContent("北岸联球员 01");
    expect(attempts).toBe(2);
  });

  it("草稿详情加载失败显示错误并可重试", async () => {
    let detailAttempts = 0;
    stubFetch((url) => {
      if (url.endsWith("/api/catalog")) return jsonResponse(CATALOG_UNAVAILABLE);
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      detailAttempts += 1;
      if (detailAttempts === 1) {
        return jsonResponse({ error: { code: "http_error", message: "战术读取失败" } }, 500);
      }
      return jsonResponse(makeDraft());
    });
    renderTacticsPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("战术读取失败");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect((await pitchSlots())[0]).toHaveTextContent("北岸联球员 01");
    expect(detailAttempts).toBe(2);
  });

  it("场景缺少阶段或 11 个位置时显示数据无效提示", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(
        makeDraft({ scenario: { schema: 4, teams: [{ name: "北岸联", players: [] }, {}] } }),
      );
    });
    renderTacticsPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("场景数据无效");
  });

  it("兼容旧版 phases 与 instructions 场景结构", async () => {
    const legacyTeam = (name: string, uidBase: number) => ({
      name,
      mentality: 3,
      players: makePlayers(name, uidBase),
      lineup: Array.from({ length: 11 }, (_, index) => index),
      roster_size: 23,
      phases: [makeAssignments(HOME_POSSESSION), makeAssignments(HOME_OUT_OF_POSSESSION)],
      instructions: { "1": 11, "9": 22 },
    });
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(
        makeDraft({
          scenario: {
            schema: 3,
            teams: [legacyTeam("旧版主队", 100), legacyTeam("旧版客队", 200)],
          },
        }),
      );
    });
    renderTacticsPage();

    const slots = await pitchSlots();
    expect(within(slots[0]).getByText("GK")).toBeInTheDocument();
    expect(screen.getByText("谨慎")).toBeInTheDocument();
    expect(screen.getByText("传球方式")).toBeInTheDocument();
    expect(screen.queryByText("防线高度")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "无球" }));

    expect(await screen.findByText("防线高度")).toBeInTheDocument();
    expect(screen.queryByText("传球方式")).not.toBeInTheDocument();
  });

  it("sidecar 未连接时显示空态且不发起请求", async () => {
    stubFetch(() => jsonResponse(makeDraftList([])));
    renderTacticsPage(null);

    expect(await screen.findByText("sidecar 未连接")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("草稿客户端请求列表与详情", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList([makeSummary()]));
      return jsonResponse(makeDraft());
    });

    const list = await listDrafts(connection);
    expect(list.items[0]?.id).toBe("draft-1");
    const draft = await getDraft(connection, "draft-1");
    expect(draft.name).toBe("草案一");

    const [listCall, detailCall] = fetchCalls();
    expect(listCall.url).toBe("http://127.0.0.1:43210/api/drafts");
    expect(detailCall.url).toBe("http://127.0.0.1:43210/api/drafts/draft-1");
    expect(new Headers(listCall.init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(new Headers(detailCall.init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("目录客户端请求鉴权接口并在不可用或失败时返回 null", async () => {
    stubFetch((url) => {
      if (url.endsWith("/api/catalog")) return jsonResponse(CATALOG_RESPONSE);
      return jsonResponse({}, 404);
    });

    const catalog = await getCatalog(connection);
    expect(catalog?.roles[0]).toEqual({ id: "Goalkeeper", label: "门将" });
    expect(catalog?.team_instructions[0]?.options?.[0]?.label).toBe("直接传球");
    const [catalogCall] = callsTo("/api/catalog");
    expect(catalogCall.url).toBe("http://127.0.0.1:43210/api/catalog");
    expect(new Headers(catalogCall.init.headers).get("Authorization")).toBe("Bearer test-token");

    fetchMock.mockImplementation(async () => jsonResponse(CATALOG_UNAVAILABLE));
    await expect(getCatalog(connection)).resolves.toBeNull();

    fetchMock.mockImplementation(async () =>
      jsonResponse({ error: { code: "http_error", message: "目录不可用" } }, 500),
    );
    await expect(getCatalog(connection)).resolves.toBeNull();
  });
});