import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate, useSearchParams } from "react-router-dom";
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

function DraftQueryNavigator({ draftId }: { draftId: string }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  return (
    <>
      <button type="button" onClick={() => navigate(`/tactics?draft=${draftId}`)}>
        跳转草稿参数
      </button>
      <button type="button" onClick={() => navigate("/tactics")}>
        清除草稿参数
      </button>
      <span aria-label="当前草稿参数">{searchParams.get("draft") ?? ""}</span>
    </>
  );
}

function renderTacticsPage(
  activeConnection: Connection | null = connection,
  initialEntries: string[] = ["/tactics"],
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
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
          <DraftQueryNavigator draftId="draft-2" />
          <TacticsPage />
        </AppContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, client };
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

const ROLE_PHASE_CATALOG = {
  available: true,
  catalog: {
    positions: [],
    roles: [
      { id: "Goalkeeper", label: "门将", phase: 0 },
      { id: "FullBack", label: "边后卫", phase: 0 },
      { id: "CentreBack", label: "中后卫", phase: 0 },
      { id: "DefensiveMidfielder", label: "防守型中场", phase: 0 },
      { id: "CentralMidfielder", label: "中前卫", phase: 0 },
      { id: "Winger", label: "边锋", phase: 0 },
      { id: "CentreForward", label: "中锋", phase: 0 },
      { id: "OPGoalkeeper", label: "防守门将", phase: 1 },
      { id: "OPFullBack", label: "防守边后卫", phase: 1 },
      { id: "OPCentreBack", label: "防守中后卫", phase: 1 },
      { id: "OPScreeningDefensiveMidfielder", label: "防守型后腰", phase: 1 },
      { id: "OPWideMidfielder", label: "防守边前卫", phase: 1 },
      { id: "OPCentralMidfielder", label: "防守中前卫", phase: 1 },
      { id: "OPAttackingMidfielder", label: "防守前腰", phase: 1 },
      { id: "OPCentreForward", label: "防守中锋", phase: 1 },
      { id: "LegacyRole", label: "无阶段角色" },
    ],
    team_instructions: [],
    mentalities: [],
  },
};

const NATIVE_HOME_OUT_OF_POSSESSION: Cell[] = [
  { position: "GK", role: "OPGoalkeeper" },
  ...HOME_OUT_OF_POSSESSION.slice(1),
];

const NATIVE_AWAY_OUT_OF_POSSESSION: Cell[] = [
  { position: "GK", role: "OPGoalkeeper" },
  ...AWAY_OUT_OF_POSSESSION.slice(1),
];

function makeNativeCells(cells: Cell[]) {
  return cells.map((cell) => ({
    ...cell,
    duty: "0",
    instructions: {},
    target_player: 255,
    target_position: 0,
  }));
}

function makeNativeTeam(
  name: string,
  uidBase: number,
  possession: Cell[],
  outOfPossession: Cell[],
  mentality = 5,
) {
  return {
    name,
    mentality,
    players: makePlayers(name, uidBase),
    lineup: Array.from({ length: 11 }, (_, index) => index),
    substitutes: Array.from({ length: 12 }, (_, index) => index + 11),
    roster_size: 23,
    instructions: {},
    phases: [makeNativeCells(possession), makeNativeCells(outOfPossession)],
  };
}

function makeNativeScenario(): Record<string, unknown> {
  return {
    schema: 3,
    fixture: "bundled_match_pkm",
    rules: "game",
    teams: [
      makeNativeTeam("北岸联", 100, HOME_POSSESSION, NATIVE_HOME_OUT_OF_POSSESSION),
      makeNativeTeam("南港队", 200, AWAY_POSSESSION, NATIVE_AWAY_OUT_OF_POSSESSION, 6),
    ],
  };
}

const PHASE_KEYS = ["in_possession", "out_of_possession"] as const;

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("expected record");
  }
  return value as Record<string, unknown>;
}

function cloneRecord(value: Record<string, unknown>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

function requiredTeam(scenario: Record<string, unknown>, side: 0 | 1): Record<string, unknown> {
  const teams = scenario.teams;
  if (!Array.isArray(teams)) throw new Error("teams missing");
  return asRecord(teams[side]);
}

function requiredCells(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new Error("cells missing");
  return value.map((entry) => asRecord(entry));
}

function withLineupSwap(
  scenario: Record<string, unknown>,
  side: 0 | 1,
  from: number,
  to: number,
): Record<string, unknown> {
  const next = cloneRecord(scenario);
  const team = requiredTeam(next, side);
  const lineup = team.lineup;
  if (!Array.isArray(lineup)) throw new Error("lineup missing");
  const value = lineup[from];
  lineup[from] = lineup[to];
  lineup[to] = value;
  return next;
}

function withNativeCellRole(
  scenario: Record<string, unknown>,
  side: 0 | 1,
  phase: 0 | 1,
  slot: number,
  role: string,
): Record<string, unknown> {
  const next = cloneRecord(scenario);
  const team = requiredTeam(next, side);
  const phases = team.phases;
  if (!Array.isArray(phases)) throw new Error("phases missing");
  requiredCells(phases[phase])[slot].role = role;
  return next;
}

function withLegacyCellRole(
  scenario: Record<string, unknown>,
  side: 0 | 1,
  phase: 0 | 1,
  slot: number,
  role: string,
): Record<string, unknown> {
  const next = cloneRecord(scenario);
  const team = requiredTeam(next, side);
  const plans = team.phase_plans;
  if (!Array.isArray(plans)) throw new Error("phase plans missing");
  const wanted = PHASE_KEYS[phase];
  const plan = plans
    .map((entry) => asRecord(entry))
    .find((entry) => entry.phase === wanted);
  if (plan === undefined) throw new Error("phase plan missing");
  requiredCells(plan.assignments)[slot].role = role;
  return next;
}

function patchedBodies(): Record<string, unknown>[] {
  return callsTo("/api/drafts/draft-1")
    .filter((call) => call.init.method === "PATCH")
    .map((call) => asRecord(JSON.parse(String(call.init.body))));
}

function detailGets() {
  return callsTo("/api/drafts/draft-1").filter((call) => call.init.method !== "PATCH");
}

type EditableHandlerOptions = {
  scenario?: Record<string, unknown>;
  catalogBody?: unknown;
  onPatch?: (body: Record<string, unknown>) => Response | Promise<Response>;
  details?: Record<string, Draft>;
  items?: DraftSummary[];
};

function editableHandlers(options: EditableHandlerOptions = {}): FetchHandler {
  const scenario = options.scenario ?? makeNativeScenario();
  const catalogBody = options.catalogBody ?? ROLE_PHASE_CATALOG;
  const items = options.items ?? [makeSummary()];
  return (url, init) => {
    if (url.endsWith("/api/catalog")) return jsonResponse(catalogBody);
    if (url.endsWith("/api/drafts")) return jsonResponse(makeDraftList(items));
    if (init.method === "PATCH") {
      const body = asRecord(JSON.parse(String(init.body)));
      return options.onPatch === undefined
        ? jsonResponse(makeDraft({ id: "draft-1", scenario }))
        : options.onPatch(body);
    }
    const id = url.slice(url.lastIndexOf("/") + 1);
    return jsonResponse(options.details?.[id] ?? makeDraft({ id, scenario }));
  };
}

async function slotButtons(): Promise<HTMLElement[]> {
  const board = await screen.findByRole("group", { name: /战术板/ });
  return within(board).getAllByRole("button");
}

async function startEditing(): Promise<HTMLElement[]> {
  await screen.findByRole("group", { name: /战术板/ });
  fireEvent.click(await screen.findByRole("button", { name: "编辑阵型" }));
  await screen.findByRole("button", { name: "保存" });
  return slotButtons();
}

function liveRegion(): HTMLElement {
  const region = document.querySelector('[aria-live="polite"]');
  if (region === null) throw new Error("aria-live region missing");
  return region as HTMLElement;
}

function roleOptionValues(select: HTMLElement): string[] {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.getAttribute("value") ?? "");
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

  it("编辑阵型进入编辑后显示保存与放弃并可退出只读", async () => {
    stubFetch(editableHandlers());
    renderTacticsPage();
    expect(await screen.findByRole("button", { name: "编辑阵型" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    const buttons = await startEditing();
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "放弃" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑阵型" })).toBeNull();
    expect(buttons).toHaveLength(11);
    expect(buttons[0]).toHaveAttribute("aria-label", "槽位 01，GK，门将");
    expect(buttons[3]).toHaveAttribute("aria-label", "槽位 04，DCL，中后卫");
    expect(buttons.filter((button) => button.tabIndex === 0)).toEqual([buttons[0]]);
    expect(buttons[1].tabIndex).toBe(-1);
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(screen.getByRole("button", { name: "编辑阵型" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
  });

  it("拖拽首发槽位交换 lineup 并高亮合法落点", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    await startEditing();
    const slots = await pitchSlots();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    expect(slots[2]).toHaveClass("is-dragging");
    expect(slots[5]).toHaveClass("is-drop-target");
    fireEvent.drop(slots[5]);
    expect(slots[5]).not.toHaveClass("is-drop-target");
    expect(screen.getByText("有未保存修改，保存或放弃后可切换草稿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()).toHaveLength(1);
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(scenario, 0, 2, 5));
  });

  it("同槽位拖放不交换且不标记未保存", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    await startEditing();
    const slots = await pitchSlots();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[2]);
    expect(slots[2]).not.toHaveClass("is-drop-target");
    fireEvent.drop(slots[2]);
    expect(screen.queryByText("有未保存修改，保存或放弃后可切换草稿")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(scenario);
  });

  it("键盘拿起槽位并交换后播报结果", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.keyDown(slots[1], { key: "Enter" });
    expect(liveRegion()).toHaveTextContent("已选择槽位 02");
    fireEvent.keyDown(slots[4], { key: "Enter" });
    expect(liveRegion()).toHaveTextContent("已与槽位 05 交换");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(scenario, 0, 1, 4));
  });

  it("方向键与 Home End 按坐标移动槽位焦点并维持单一 tabIndex", async () => {
    stubFetch(editableHandlers());
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.focusIn(slots[10]);
    fireEvent.keyDown(slots[10], { key: "ArrowLeft" });
    expect(slots[7]).toHaveFocus();
    expect(slots[7].tabIndex).toBe(0);
    expect(slots[10].tabIndex).toBe(-1);
    fireEvent.keyDown(slots[7], { key: "ArrowRight" });
    expect(slots[5]).toHaveFocus();
    expect(slots[5].tabIndex).toBe(0);
    fireEvent.keyDown(slots[5], { key: "Home" });
    expect(slots[0]).toHaveFocus();
    fireEvent.keyDown(slots[0], { key: "End" });
    expect(slots[10]).toHaveFocus();
    expect(slots.filter((slot) => slot.tabIndex === 0)).toEqual([slots[10]]);
  });

  it("Escape 取消拿起后再次确认只选择不交换", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.keyDown(slots[1], { key: " " });
    expect(liveRegion()).toHaveTextContent("已选择槽位 02");
    fireEvent.keyDown(slots[1], { key: "Escape" });
    expect(liveRegion()).toHaveTextContent("已取消选择");
    fireEvent.keyDown(slots[4], { key: "Enter" });
    expect(liveRegion()).toHaveTextContent("已选择槽位 05");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(scenario);
  });

  it("角色变更只写目标槽位并保留其余字段", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.click(slots[3]);
    const select = screen.getByRole("combobox", { name: "角色" });
    expect(select).toHaveValue("CentreBack");
    fireEvent.change(select, { target: { value: "FullBack" } });
    expect(select).toHaveValue("FullBack");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(withNativeCellRole(scenario, 0, 0, 3, "FullBack"));
  });

  it("角色下拉按当前阶段过滤并排除未标阶段的角色", async () => {
    stubFetch(editableHandlers());
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.click(slots[0]);
    const possessionOptions = roleOptionValues(screen.getByRole("combobox", { name: "角色" }));
    expect(possessionOptions).toContain("Goalkeeper");
    expect(possessionOptions).toContain("CentreForward");
    expect(possessionOptions).not.toContain("OPGoalkeeper");
    expect(possessionOptions).not.toContain("LegacyRole");
    fireEvent.click(screen.getByRole("button", { name: "无球" }));
    const outOfPossessionSelect = screen.getByRole("combobox", { name: "角色" });
    expect(outOfPossessionSelect).toHaveValue("OPGoalkeeper");
    const outOfPossessionOptions = roleOptionValues(outOfPossessionSelect);
    expect(outOfPossessionOptions).toContain("OPGoalkeeper");
    expect(outOfPossessionOptions).not.toContain("FullBack");
    expect(outOfPossessionOptions).not.toContain("LegacyRole");
  });

  it("当前角色不在阶段选项中时仍显示为可选项", async () => {
    const base = ROLE_PHASE_CATALOG.catalog;
    const catalogBody = {
      available: true,
      catalog: {
        ...base,
        roles: base.roles.filter((role) => role.id !== "OPGoalkeeper"),
      },
    };
    stubFetch(editableHandlers({ catalogBody }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.click(slots[0]);
    fireEvent.click(screen.getByRole("button", { name: "无球" }));
    const select = screen.getByRole("combobox", { name: "角色" });
    expect(select).toHaveValue("OPGoalkeeper");
    expect(within(select).getByRole("option", { name: "OPGoalkeeper" })).toBeInTheDocument();
  });

  it("切换阶段与球队保留未保存的首发交换", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const initial = await startEditing();
    fireEvent.keyDown(initial[1], { key: "Enter" });
    fireEvent.keyDown(initial[4], { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "无球" }));
    expect((await slotButtons())[1]).toHaveTextContent("北岸联球员 05");
    fireEvent.click(screen.getByRole("button", { name: "客队" }));
    expect((await slotButtons())[1]).toHaveTextContent("南港队球员 02");
    fireEvent.click(screen.getByRole("button", { name: "主队" }));
    expect((await slotButtons())[1]).toHaveTextContent("北岸联球员 05");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(scenario, 0, 1, 4));
  });

  it("存在未保存修改时禁用草稿切换并提示", async () => {
    const scenario = makeNativeScenario();
    stubFetch(
      editableHandlers({
        scenario,
        items: [makeSummary(), makeSummary({ id: "draft-2", name: "草案二" })],
        details: { "draft-2": makeDraft({ id: "draft-2", name: "草案二", scenario }) },
      }),
    );
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    fireEvent.drop(slots[5]);
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toBeDisabled();
    expect(screen.getByText("有未保存修改，保存或放弃后可切换草稿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toBeEnabled();
    expect(screen.queryByText("有未保存修改，保存或放弃后可切换草稿")).toBeNull();
    expect((await pitchSlots())[1]).toHaveTextContent("北岸联球员 02");
    expect(patchedBodies()).toHaveLength(0);
  });

  it("保存成功后显示已保存并失效详情查询", async () => {
    const scenario = makeNativeScenario();
    stubFetch(editableHandlers({ scenario }));
    const { client } = renderTacticsPage();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const slots = await startEditing();
    fireEvent.keyDown(slots[1], { key: "Enter" });
    fireEvent.keyDown(slots[4], { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["draft", connection.url, "draft-1"],
    });
    expect(screen.getByRole("button", { name: "编辑阵型" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    expect(screen.queryByText("有未保存修改，保存或放弃后可切换草稿")).toBeNull();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toBeEnabled();
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(scenario, 0, 1, 4));
    await waitFor(() => expect(detailGets()).toHaveLength(2));
  });

  it("保存失败展示服务端消息并保留编辑可重试", async () => {
    const scenario = makeNativeScenario();
    let patchCount = 0;
    stubFetch(
      editableHandlers({
        scenario,
        onPatch: () => {
          patchCount += 1;
          if (patchCount === 1) {
            return jsonResponse(
              { error: { code: "validation_failed", message: "角色与阶段不匹配" } },
              400,
            );
          }
          return jsonResponse(makeDraft({ scenario }));
        },
      }),
    );
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.keyDown(slots[1], { key: "Enter" });
    fireEvent.keyDown(slots[4], { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("角色与阶段不匹配");
    expect(screen.getByRole("button", { name: "保存" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "编辑阵型" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(patchCount).toBe(2);
    expect(patchedBodies()).toHaveLength(2);
  });

  it("保存请求中禁用操作并阻止重复提交", async () => {
    const pending = deferred<Response>();
    stubFetch(editableHandlers({ onPatch: () => pending.promise }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.keyDown(slots[1], { key: "Enter" });
    fireEvent.keyDown(slots[4], { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "保存" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "放弃" })).toBeDisabled();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(patchedBodies()).toHaveLength(1);
    pending.resolve(jsonResponse(makeDraft({ scenario: makeNativeScenario() })));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
    expect(patchedBodies()).toHaveLength(1);
  });

  it("引擎目录缺失时禁用角色下拉并保留降级说明", async () => {
    stubFetch(editableHandlers({ catalogBody: CATALOG_UNAVAILABLE }));
    renderTacticsPage();
    await startEditing();
    expect(screen.getByRole("combobox", { name: "角色" })).toBeDisabled();
    expect(screen.getByText("未载入引擎目录，指令与角色显示原生编号")).toBeInTheDocument();
  });

  it("窄屏编辑槽位保持紧凑样式与可访问名称", async () => {
    stubCompactViewport(true);
    stubFetch(editableHandlers());
    renderTacticsPage();
    await startEditing();
    const items = await pitchSlots();
    expect(items[0]).toHaveClass("tactics-slot--compact");
    expect(items[0]).toHaveClass("tactics-slot--editable");
    const button = within(items[0]).getByRole("button");
    expect(button).toHaveAttribute("aria-label", "槽位 01，GK，门将");
    expect(within(items[0]).queryByText("门将")).toBeNull();
  });

  it("旧版 phase_plans 场景拖拽交换写回原形状", async () => {
    const scenario = makeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    fireEvent.drop(slots[5]);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(scenario, 0, 2, 5));
  });

  it("旧版 phase_plans 场景角色变更写回对应槽位", async () => {
    const scenario = makeScenario();
    stubFetch(editableHandlers({ scenario }));
    renderTacticsPage();
    const slots = await startEditing();
    fireEvent.click(slots[3]);
    const select = screen.getByRole("combobox", { name: "角色" });
    expect(select).toHaveValue("CentreBack");
    fireEvent.change(select, { target: { value: "FullBack" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");
    expect(patchedBodies()[0]?.scenario).toEqual(withLegacyCellRole(scenario, 0, 0, 3, "FullBack"));
  });
});

describe("TacticsPage 初始草稿参数", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function parameterHandlers() {
    return (url: string) => {
      if (url.endsWith("/api/catalog")) return jsonResponse(CATALOG_UNAVAILABLE);
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
    };
  }

  it("按地址栏 draft 参数选中对应草稿", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage(connection, ["/tactics?draft=draft-2"]);

    const slots = await pitchSlots();

    expect(within(slots[0]).getByText("西城队球员 01")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2");
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(1);
    expect(callsTo("/api/drafts/draft-1")).toHaveLength(0);
  });

  it("draft 参数无效时回退首个草稿", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage(connection, ["/tactics?draft=missing"]);

    const slots = await pitchSlots();

    expect(within(slots[0]).getByText("北岸联球员 01")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");
    expect(callsTo("/api/drafts/draft-1")).toHaveLength(1);
    expect(callsTo("/api/drafts/missing")).toHaveLength(0);
  });

  it("地址栏参数变化后更新选中草稿", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage();

    expect(await screen.findByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");

    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2"),
    );
    const slots = await pitchSlots();
    expect(within(slots[0]).getByText("西城队球员 01")).toBeInTheDocument();
  });

  it("参数移除后重新加入同一草稿参数仍会应用", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage(connection, ["/tactics?draft=draft-2"]);

    expect(await screen.findByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2");

    fireEvent.click(screen.getByRole("button", { name: "清除草稿参数" }));
    await waitFor(() =>
      expect(screen.getByLabelText("当前草稿参数")).toHaveTextContent(""),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "选择草稿" }), {
      target: { value: "draft-1" },
    });

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1"),
    );
    const before = await pitchSlots();
    expect(within(before[0]).getByText("北岸联球员 01")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2"),
    );
    const slots = await pitchSlots();
    expect(within(slots[0]).getByText("西城队球员 01")).toBeInTheDocument();
  });

  it("切换参数时重置编辑态并加载新草稿场景", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage();

    await startEditing();
    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2"),
    );
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    expect(screen.queryByText("编辑阵型中，修改后请保存或放弃")).toBeNull();
    expect(screen.getByRole("button", { name: "编辑阵型" })).toBeInTheDocument();
    const slots = await pitchSlots();
    expect(within(slots[0]).getByText("西城队球员 01")).toBeInTheDocument();
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(1);
    expect(patchedBodies()).toHaveLength(0);
  });

  it("存在未保存修改时参数变化不抢占当前草稿", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage();

    const slots = await startEditing();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    fireEvent.drop(slots[5]);
    expect(screen.getByText("有未保存修改，保存或放弃后可切换草稿")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 25);
    });

    expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-1");
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
    expect(screen.getByText("有未保存修改，保存或放弃后可切换草稿")).toBeInTheDocument();
    const items = await pitchSlots();
    expect(items[2]).toHaveTextContent("北岸联球员 06");
    expect(items[5]).toHaveTextContent("北岸联球员 03");
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(0);
  });

  it("放弃未保存修改后应用待切换的草稿参数", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage();

    const slots = await startEditing();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    fireEvent.drop(slots[5]);

    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));
    expect(screen.getByRole("button", { name: "放弃" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2"),
    );
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    const items = await pitchSlots();
    expect(within(items[0]).getByText("西城队球员 01")).toBeInTheDocument();
    expect(callsTo("/api/drafts/draft-2")).toHaveLength(1);
    expect(patchedBodies()).toHaveLength(0);
  });

  it("保存成功后应用待切换的草稿参数", async () => {
    stubFetch(parameterHandlers());
    renderTacticsPage();

    const slots = await startEditing();
    fireEvent.dragStart(slots[2]);
    fireEvent.dragOver(slots[5]);
    fireEvent.drop(slots[5]);

    fireEvent.click(screen.getByRole("button", { name: "跳转草稿参数" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "选择草稿" })).toHaveValue("draft-2"),
    );
    expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    const items = await pitchSlots();
    expect(within(items[0]).getByText("西城队球员 01")).toBeInTheDocument();
    expect(patchedBodies()[0]?.scenario).toEqual(withLineupSwap(makeScenario(), 0, 2, 5));
  });
});