import { useQuery } from "@tanstack/react-query";
import { SquaresFour } from "@phosphor-icons/react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { getCatalog, getDraft, listDrafts, type Catalog, type CatalogTeamInstruction } from "../lib/api";

const SLOT_COUNT = 11;
const MAX_INSTRUCTION_ROWS = 8;
const COMPACT_MAX_WIDTH = 640;
const PHASE_LABELS = ["有球", "无球"] as const;
const CATALOG_MISSING_NOTE = "未载入引擎目录，指令与角色显示原生编号";

const MENTALITY_LABELS: Record<number, string> = {
  1: "极度防守",
  2: "防守",
  3: "谨慎",
  4: "均衡",
  5: "积极",
  6: "进攻",
  7: "全力进攻",
};

const TEAM_INSTRUCTIONS: Record<string, { label: string; phase: 0 | 1 }> = {
  "1": { label: "传球方式", phase: 0 },
  "3": { label: "得球后", phase: 0 },
  "4": { label: "进攻宽度", phase: 0 },
  "5": { label: "创造自由度", phase: 0 },
  "6": { label: "争取定位球", phase: 0 },
  "7": { label: "拖延时间", phase: 0 },
  "8": { label: "防守介入线", phase: 1 },
  "9": { label: "防线高度", phase: 1 },
  "10": { label: "逼抢频率", phase: 1 },
  "11": { label: "丢球后", phase: 1 },
  "12": { label: "铲抢", phase: 1 },
  "15": { label: "防线行为", phase: 1 },
  "16": { label: "门将出球目标", phase: 0 },
  "17": { label: "门将出球速度", phase: 0 },
  "18": { label: "进攻耐心", phase: 0 },
  "19": { label: "盘带", phase: 0 },
  "20": { label: "接球方式", phase: 0 },
  "21": { label: "比赛节奏", phase: 0 },
  "22": { label: "防守传中", phase: 1 },
  "23": { label: "阻止门将短传", phase: 1 },
  "24": { label: "后场组织", phase: 0 },
  "25": { label: "逼抢陷阱", phase: 1 },
  "26": { label: "传中方式", phase: 0 },
  "27": { label: "远射", phase: 0 },
  "28": { label: "肋部套上", phase: 0 },
  "29": { label: "球门球", phase: 0 },
  "30": { label: "推进方向", phase: 0 },
  "31": { label: "外侧套上", phase: 0 },
  "32": { label: "门将参与进攻定位球", phase: 0 },
};

// 原生位置表按边中卫、左右后腰等拆分；经典 SW 与 DM 不在其中，沿用 DC 与 DMC 的坐标。
const POSITION_POINTS: Record<string, { x: number; y: number }> = {
  GK: { x: 50, y: 92 },
  SW: { x: 50, y: 78 },
  DL: { x: 14, y: 76 },
  DCL: { x: 33, y: 78 },
  DC: { x: 50, y: 78 },
  DCR: { x: 67, y: 78 },
  DR: { x: 86, y: 76 },
  WBL: { x: 9, y: 62 },
  DML: { x: 33, y: 61 },
  DM: { x: 50, y: 61 },
  DMC: { x: 50, y: 61 },
  DMR: { x: 67, y: 61 },
  WBR: { x: 91, y: 62 },
  ML: { x: 11, y: 45 },
  MCL: { x: 33, y: 45 },
  MC: { x: 50, y: 45 },
  MCR: { x: 67, y: 45 },
  MR: { x: 89, y: 45 },
  AML: { x: 12, y: 28 },
  AMCL: { x: 33, y: 28 },
  AMC: { x: 50, y: 28 },
  AMCR: { x: 67, y: 28 },
  AMR: { x: 88, y: 28 },
  STL: { x: 33, y: 12 },
  ST: { x: 50, y: 12 },
  STR: { x: 67, y: 12 },
};

type PhaseCell = { position: string; role: string };
type PhasePlan = { cells: PhaseCell[]; instructions: Record<string, unknown> };
type TeamView = {
  name: string | null;
  players: string[];
  lineup: number[];
  mentality: number | null;
  plans: [PhasePlan, PhasePlan];
};
type ScenarioView = { teams: [TeamView, TeamView] };
type InstructionRow = { key: string; label: string; value: string };
type CatalogGroup = { label: string; phase: number | null; options: Map<string, string> };
type CatalogLookup = {
  roleLabels: Map<string, string>;
  groups: Map<string, CatalogGroup>;
  mentalityLabels: Map<string, string>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function catalogEntries(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function catalogId(value: unknown): string | null {
  if (typeof value === "string" && value !== "") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function catalogLabel(entry: Record<string, unknown>, fallback: string): string {
  for (const key of ["label", "name"] as const) {
    const value = entry[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return fallback;
}

function buildCatalogLookup(catalog: Catalog | null): CatalogLookup | null {
  if (catalog === null) return null;
  const roleLabels = new Map<string, string>();
  for (const entry of catalogEntries(catalog.roles)) {
    const id = catalogId(entry.id);
    if (id === null) continue;
    roleLabels.set(id, catalogLabel(entry, id));
  }
  const groups = new Map<string, CatalogGroup>();
  for (const entry of catalogEntries(catalog.team_instructions)) {
    const id = catalogId(entry.id);
    if (id === null) continue;
    const options = new Map<string, string>();
    for (const option of catalogEntries(entry.options)) {
      const optionId = catalogId(option.id);
      if (optionId === null) continue;
      options.set(optionId, catalogLabel(option, optionId));
    }
    groups.set(id, { label: catalogLabel(entry, id), phase: entryPhase(entry), options });
  }
  const mentalityLabels = new Map<string, string>();
  for (const entry of catalogEntries(catalog.mentalities)) {
    const id = catalogId(entry.id);
    if (id === null) continue;
    mentalityLabels.set(id, catalogLabel(entry, id));
  }
  return { roleLabels, groups, mentalityLabels };
}

function entryPhase(entry: CatalogTeamInstruction | Record<string, unknown>): 0 | 1 | null {
  const value = entry.possession_phase ?? entry.phase;
  return value === 0 || value === 1 ? value : null;
}

function parseCells(value: unknown): PhaseCell[] | null {
  if (!Array.isArray(value) || value.length !== SLOT_COUNT) return null;
  const cells: PhaseCell[] = [];
  for (const entry of value) {
    if (!isRecord(entry)) return null;
    const position = entry.position;
    if (typeof position !== "string" || position === "") return null;
    cells.push({ position, role: typeof entry.role === "string" ? entry.role : "" });
  }
  return cells;
}

function parseInstructions(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function parsePlans(team: Record<string, unknown>): [PhasePlan, PhasePlan] | null {
  if (Array.isArray(team.phase_plans) && team.phase_plans.length === 2) {
    const plans: Array<PhasePlan | null> = [null, null];
    for (const entry of team.phase_plans) {
      if (!isRecord(entry)) return null;
      const index =
        entry.phase === "in_possession" ? 0 : entry.phase === "out_of_possession" ? 1 : null;
      if (index === null) return null;
      const cells = parseCells(entry.assignments);
      if (cells === null) return null;
      plans[index] = { cells, instructions: parseInstructions(entry.team_instructions) };
    }
    const [possession, outOfPossession] = plans;
    if (possession === null || outOfPossession === null) return null;
    return [possession, outOfPossession];
  }
  if (Array.isArray(team.phases) && team.phases.length === 2) {
    const possession = parseCells(team.phases[0]);
    const outOfPossession = parseCells(team.phases[1]);
    if (possession === null || outOfPossession === null) return null;
    const instructions = parseInstructions(team.instructions);
    return [
      { cells: possession, instructions },
      { cells: outOfPossession, instructions },
    ];
  }
  return null;
}

function parseTeam(value: unknown): TeamView | null {
  if (!isRecord(value)) return null;
  const plans = parsePlans(value);
  if (plans === null) return null;
  const players = Array.isArray(value.players)
    ? value.players.map((entry, index) => {
        const name = isRecord(entry) ? entry.name : undefined;
        return typeof name === "string" && name.trim() !== "" ? name.trim() : `球员 ${index + 1}`;
      })
    : [];
  const lineup = Array.isArray(value.lineup)
    ? value.lineup.filter((entry): entry is number => typeof entry === "number" && Number.isInteger(entry))
    : [];
  const name = typeof value.name === "string" && value.name.trim() !== "" ? value.name.trim() : null;
  const mentality =
    typeof value.mentality === "number" && Number.isFinite(value.mentality) ? value.mentality : null;
  return { name, players, lineup, mentality, plans };
}

function parseScenario(value: Record<string, unknown>): ScenarioView | null {
  const teams = value.teams;
  if (!Array.isArray(teams) || teams.length !== 2) return null;
  const home = parseTeam(teams[0]);
  const away = parseTeam(teams[1]);
  if (home === null || away === null) return null;
  return { teams: [home, away] };
}

function positionPoint(position: string): { x: number; y: number } {
  return POSITION_POINTS[position] ?? { x: 50, y: 50 };
}

function playerName(team: TeamView, slot: number): string {
  const index = team.lineup[slot];
  if (index === undefined) return "—";
  return team.players[index] ?? "—";
}

function roleLabel(role: string, lookup: CatalogLookup | null): string {
  if (role === "") return "—";
  return lookup?.roleLabels.get(role) ?? role;
}

function mentalityLabel(mentality: number | null, lookup: CatalogLookup | null): string {
  if (mentality === null) return "—";
  return (
    lookup?.mentalityLabels.get(String(mentality)) ?? MENTALITY_LABELS[mentality] ?? String(mentality)
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value);
}

function instructionValueLabel(value: unknown, group: CatalogGroup | undefined): string {
  if (typeof value === "number" || typeof value === "string") {
    const text = String(value);
    return group?.options.get(text) ?? `原生选项 #${text}`;
  }
  return formatValue(value);
}

function instructionRows(
  plan: PhasePlan,
  phase: 0 | 1,
  lookup: CatalogLookup | null,
): InstructionRow[] {
  const rows: InstructionRow[] = [];
  for (const [key, value] of Object.entries(plan.instructions)) {
    const catalogGroup = lookup?.groups.get(key);
    const builtin = TEAM_INSTRUCTIONS[key];
    const groupPhase = catalogGroup !== undefined ? catalogGroup.phase : (builtin?.phase ?? null);
    if (groupPhase !== null && groupPhase !== phase) continue;
    rows.push({
      key,
      label: catalogGroup?.label ?? builtin?.label ?? key,
      value: instructionValueLabel(value, catalogGroup),
    });
  }
  return rows;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function slotCode(slot: number): string {
  return String(slot + 1).padStart(2, "0");
}

function useCompactSlots(): boolean {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      setCompact(window.innerWidth <= COMPACT_MAX_WIDTH);
      return;
    }
    const query = window.matchMedia(`(max-width: ${COMPACT_MAX_WIDTH}px)`);
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return compact;
}

export function TacticsPage() {
  const { connection } = useAppContext();
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [side, setSide] = useState<0 | 1>(0);
  const [phase, setPhase] = useState<0 | 1>(0);
  const compact = useCompactSlots();

  const drafts = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null,
  });

  const catalog = useQuery({
    queryKey: ["catalog", connection?.url],
    queryFn: () => getCatalog(connection!),
    enabled: connection !== null,
    staleTime: Infinity,
  });

  const draftItems = Array.isArray(drafts.data?.items) ? drafts.data.items : [];
  const activeDraftId = draftItems.some((item) => item.id === selectedDraftId)
    ? selectedDraftId
    : (draftItems[0]?.id ?? null);

  const detail = useQuery({
    queryKey: ["draft", connection?.url, activeDraftId],
    queryFn: () => getDraft(connection!, activeDraftId!),
    enabled: connection !== null && activeDraftId !== null,
  });

  const scenario =
    detail.data === undefined || !isRecord(detail.data.scenario)
      ? null
      : parseScenario(detail.data.scenario);
  const team = scenario === null ? null : scenario.teams[side];
  const lookup = buildCatalogLookup(catalog.data ?? null);
  const catalogMissing = catalog.isSuccess && (catalog.data ?? null) === null;

  const toolbar =
    draftItems.length === 0 ? null : (
      <div className="tactics-toolbar">
        <label className="field tactics-draft">
          草稿
          <select
            aria-label="选择草稿"
            value={activeDraftId ?? ""}
            onChange={(event) => setSelectedDraftId(event.target.value)}
          >
            {draftItems.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented" role="group" aria-label="球队">
          <button type="button" aria-pressed={side === 0} onClick={() => setSide(0)}>
            主队
          </button>
          <button type="button" aria-pressed={side === 1} onClick={() => setSide(1)}>
            客队
          </button>
        </div>
        <div className="segmented" role="group" aria-label="阶段">
          <button type="button" aria-pressed={phase === 0} onClick={() => setPhase(0)}>
            有球
          </button>
          <button type="button" aria-pressed={phase === 1} onClick={() => setPhase(1)}>
            无球
          </button>
        </div>
      </div>
    );

  if (connection === null) {
    return (
      <Panel title="双阶段战术板">
        <EmptyState
          icon={SquaresFour}
          title="sidecar 未连接"
          description="连接 sidecar 后可以查看草稿球队的两套阶段阵型与球队指令。"
        />
      </Panel>
    );
  }

  if (drafts.isPending) {
    return (
      <Panel title="双阶段战术板">
        <p className="jobs-loading" role="status">
          正在加载草稿…
        </p>
      </Panel>
    );
  }

  if (drafts.isError) {
    return (
      <Panel title="双阶段战术板">
        <div className="inline-alert" role="alert">
          <span>{errorMessage(drafts.error)}</span>
          <button className="button small" type="button" onClick={() => void drafts.refetch()}>
            重试
          </button>
        </div>
      </Panel>
    );
  }

  if (draftItems.length === 0) {
    return (
      <Panel title="双阶段战术板">
        <EmptyState
          icon={SquaresFour}
          title="暂无草稿"
          description="创建场景草案后，这里会显示两套阶段阵型与球队指令。"
          action={
            <Link className="button tactics-library-link" to="/library">
              前往战术库
            </Link>
          }
        />
      </Panel>
    );
  }

  const boardPanel = (content: ReactNode) => (
    <Panel title="双阶段战术板" className="span-7 tactics-board">
      {toolbar}
      {content}
    </Panel>
  );

  if (detail.isPending) {
    return (
      <div className="page-grid">
        {boardPanel(<div className="tactics-skeleton" aria-hidden="true" />)}
        <Panel title="球队指令" className="span-5">
          <p className="jobs-loading" role="status">
            正在加载战术…
          </p>
        </Panel>
      </div>
    );
  }

  if (detail.isError) {
    return (
      <Panel title="双阶段战术板">
        {toolbar}
        <div className="inline-alert" role="alert">
          <span>{errorMessage(detail.error)}</span>
          <button className="button small" type="button" onClick={() => void detail.refetch()}>
            重试
          </button>
        </div>
      </Panel>
    );
  }

  if (scenario === null || team === null) {
    return (
      <Panel title="双阶段战术板">
        {toolbar}
        <div className="inline-alert" role="alert">
          场景数据无效：需要两支球队与两套各 11 个位置的阶段。
        </div>
      </Panel>
    );
  }

  const plan = team.plans[phase];
  const rows = instructionRows(plan, phase, lookup);
  const visibleRows = rows.slice(0, MAX_INSTRUCTION_ROWS);
  const hiddenRows = rows.length - visibleRows.length;

  return (
    <div className="page-grid">
      {boardPanel(
        <>
          <div className="tactics-pitch" role="group" aria-label={`${PHASE_LABELS[phase]}战术板`}>
            <div className="tactics-pitch-lines" aria-hidden="true">
              <span className="tactics-pitch-halfway" />
              <span className="tactics-pitch-circle" />
              <span className="tactics-pitch-box tactics-pitch-box-top" />
              <span className="tactics-pitch-box tactics-pitch-box-bottom" />
            </div>
            <ol className="tactics-slots">
              {plan.cells.map((cell, index) => {
                const point = positionPoint(cell.position);
                const name = playerName(team, index);
                const role = roleLabel(cell.role, lookup);
                return (
                  <li
                    key={index}
                    className={compact ? "tactics-slot tactics-slot--compact" : "tactics-slot"}
                    style={{ left: `${point.x}%`, top: `${point.y}%` }}
                    title={`${slotCode(index)} · ${name} · ${cell.position} · ${role}`}
                  >
                    <span className="tactics-slot-shirt">{slotCode(index)}</span>
                    {compact ? null : <span className="tactics-slot-name">{name}</span>}
                    <span className="tactics-slot-position">{cell.position}</span>
                    {compact ? null : <span className="tactics-slot-role">{role}</span>}
                  </li>
                );
              })}
            </ol>
          </div>
          <p className="tactics-direction">进攻方向 ↑</p>
        </>
      )}
      <Panel
        title="球队指令"
        className="span-5"
        action={team.name === null ? undefined : <span className="badge">{team.name}</span>}
      >
        {catalogMissing ? (
          <p className="tactics-note tactics-catalog-note">{CATALOG_MISSING_NOTE}</p>
        ) : null}
        <div className="tactics-mentality">
          <span className="tactics-mentality-label">心态</span>
          <span className="tactics-mentality-value">{mentalityLabel(team.mentality, lookup)}</span>
        </div>
        {visibleRows.length === 0 ? (
          <p className="tactics-note">该阶段没有可读的球队指令。</p>
        ) : (
          <dl className="tactics-instructions">
            {visibleRows.map((row) => (
              <div className="tactics-instruction" key={row.key}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {hiddenRows > 0 ? <p className="tactics-note">另有 {hiddenRows} 项未显示</p> : null}
      </Panel>
    </div>
  );
}
