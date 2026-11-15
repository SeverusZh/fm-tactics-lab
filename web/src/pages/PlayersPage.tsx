import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UsersThree } from "@phosphor-icons/react";
import {
  useEffect,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  applyDraftAttributes,
  getDraft,
  listDrafts,
  type DraftAttributeOperation,
  type DraftAttributePayload,
  type DraftAttributeScope,
} from "../lib/api";
import "../styles/players.css";

const POSITION_CODES = [
  "GK",
  "SW",
  "DL",
  "DC",
  "DR",
  "DM",
  "ML",
  "MC",
  "MR",
  "AML",
  "AMC",
  "AMR",
  "ST",
  "WBL",
  "WBR",
];

const ATTRIBUTE_LABELS = [
  "门将",
  "旧清道夫位置",
  "左后卫",
  "中后卫",
  "右后卫",
  "后腰",
  "左前卫",
  "中前卫",
  "右前卫",
  "左边锋",
  "前腰",
  "右边锋",
  "中锋",
  "左翼卫",
  "右翼卫",
  "传中",
  "盘带",
  "射门",
  "头球",
  "远射",
  "盯人",
  "无球跑动",
  "传球",
  "点球",
  "抢断",
  "视野",
  "手控球",
  "制空范围",
  "禁区控制",
  "交流",
  "大脚开球",
  "手抛球",
  "预判",
  "决断",
  "一对一",
  "防守站位",
  "反应",
  "停球",
  "技术",
  "左脚",
  "右脚",
  "想象力",
  "角球",
  "团队合作",
  "工作投入",
  "界外球",
  "神经指数",
  "出击",
  "击球倾向",
  "爆发力",
  "任意球",
  "强壮",
  "耐力",
  "速度",
  "弹跳",
  "领导力",
  "肮脏",
  "平衡",
  "勇敢",
  "稳定性",
  "侵略性",
  "灵活",
  "大赛",
  "伤病倾向",
  "多面性",
  "体质",
  "意志力",
  "镇定",
  "集中",
] as const;

type GroupId = "technical" | "mental" | "physical" | "goalkeeping" | "hidden" | "position";

type AttributeGroup = {
  id: GroupId;
  title: string;
  indices: readonly number[];
};

const ATTRIBUTE_GROUPS: readonly AttributeGroup[] = [
  {
    id: "technical",
    title: "技术",
    indices: [15, 16, 17, 18, 19, 20, 22, 23, 24, 37, 38, 42, 45, 50],
  },
  {
    id: "mental",
    title: "精神",
    indices: [21, 25, 32, 33, 35, 41, 43, 44, 55, 58, 60, 66, 67, 68],
  },
  {
    id: "physical",
    title: "身体",
    indices: [49, 51, 52, 53, 54, 57, 61, 65],
  },
  {
    id: "goalkeeping",
    title: "门将",
    indices: [26, 27, 28, 29, 30, 31, 34, 36, 46, 47, 48],
  },
  {
    id: "hidden",
    title: "隐藏",
    indices: [39, 40, 56, 59, 62, 63, 64],
  },
  {
    id: "position",
    title: "位置熟练度",
    indices: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
  },
];

type BulkGroup = "technical" | "mental" | "physical" | "goalkeeping";

type EditableScope = Exclude<DraftAttributeScope, "squad">;

const BULK_GROUPS: readonly { id: BulkGroup; title: string }[] = [
  { id: "technical", title: "技术" },
  { id: "mental", title: "精神" },
  { id: "physical", title: "身体" },
  { id: "goalkeeping", title: "门将" },
];

function defaultBulkGroups(): BulkGroup[] {
  return BULK_GROUPS.map((group) => group.id);
}

function orderedGroups(groups: readonly BulkGroup[]): BulkGroup[] {
  return BULK_GROUPS.filter((group) => groups.includes(group.id)).map((group) => group.id);
}

function GroupPicker({
  selected,
  onChange,
}: {
  selected: readonly BulkGroup[];
  onChange: (groups: BulkGroup[]) => void;
}) {
  return (
    <div className="players-bulk-groups" role="group" aria-label="分组">
      {BULK_GROUPS.map((group) => (
        <label className="field-inline" key={group.id}>
          <input
            type="checkbox"
            checked={selected.includes(group.id)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...selected, group.id]
                  : selected.filter((id) => id !== group.id),
              )
            }
          />
          {group.title}
        </label>
      ))}
    </div>
  );
}

type ScenarioPlayer = {
  uid: string;
  sourceUid: string | number;
  name: string;
  position: number;
  ability: number | null;
  attributes: number[];
  generated: boolean;
};

type RosterTrim = {
  sourceSize: number | null;
  removedCount: number;
  generatedUids: string[];
};

type ScenarioTeam = {
  name: string | null;
  players: ScenarioPlayer[];
  roster: RosterTrim;
};

type Scenario = {
  teams: [ScenarioTeam, ScenarioTeam];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readAttributes(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 69) return null;
  if (!value.every((item) => typeof item === "number" && Number.isInteger(item))) return null;
  return value;
}

function readAbility(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (isRecord(value) && typeof value.current === "number" && Number.isFinite(value.current)) {
    return value.current;
  }
  return null;
}

function strongestPosition(attributes: number[]): number {
  let best = 0;
  for (let index = 1; index < POSITION_CODES.length; index += 1) {
    if (attributes[index] > attributes[best]) best = index;
  }
  return best;
}

function parsePlayer(value: unknown, index: number): ScenarioPlayer | null {
  if (!isRecord(value)) return null;
  const attributes = readAttributes(value.attributes);
  if (attributes === null) return null;
  const uid = value.source_uid;
  const name =
    typeof value.name === "string" && value.name.trim() !== "" ? value.name.trim() : `球员 ${index + 1}`;
  const sourceUid =
    typeof uid === "number" || typeof uid === "string" ? uid : `player-${index}`;
  return {
    uid: String(sourceUid),
    sourceUid,
    name,
    position: strongestPosition(attributes),
    ability: readAbility(value.ability),
    attributes,
    generated: value.generated === true,
  };
}

const EMPTY_ROSTER_TRIM: RosterTrim = {
  sourceSize: null,
  removedCount: 0,
  generatedUids: [],
};

function parseRosterTrim(value: unknown): RosterTrim {
  if (!isRecord(value)) return EMPTY_ROSTER_TRIM;
  const sourceSize =
    typeof value.source_size === "number" &&
    Number.isInteger(value.source_size) &&
    value.source_size >= 0
      ? value.source_size
      : null;
  const removedCount = Array.isArray(value.removed)
    ? value.removed.filter((entry) => isRecord(entry)).length
    : 0;
  const generatedUids = Array.isArray(value.generated)
    ? value.generated.map((entry) => String(entry))
    : [];
  return { sourceSize, removedCount, generatedUids };
}

function rosterNoticeText(roster: RosterTrim): string | null {
  const generatedCount = roster.generatedUids.length;
  if (roster.sourceSize !== null && roster.sourceSize > 23) {
    const base = `原始名单 ${roster.sourceSize} 人，已按 23 人裁剪，移除 ${roster.removedCount} 人`;
    return generatedCount > 0 ? `${base}，其中 ${generatedCount} 名为占位球员` : base;
  }
  if (roster.sourceSize !== null && roster.sourceSize < 23) {
    return `原始名单 ${roster.sourceSize} 人，已用 ${23 - roster.sourceSize} 名占位球员补足 23 人`;
  }
  if (roster.sourceSize === null && generatedCount > 0) {
    return `名单含 ${generatedCount} 名占位球员`;
  }
  return null;
}

function parseTeam(value: unknown): ScenarioTeam | null {
  if (!isRecord(value) || !Array.isArray(value.players) || value.players.length !== 23) {
    return null;
  }
  const players: ScenarioPlayer[] = [];
  for (const [index, entry] of value.players.entries()) {
    const player = parsePlayer(entry, index);
    if (player === null) return null;
    players.push(player);
  }
  const name = typeof value.name === "string" && value.name.trim() !== "" ? value.name.trim() : null;
  return { name, players, roster: parseRosterTrim(value.roster_trim) };
}

function parseScenario(scenario: Record<string, unknown>): Scenario | null {
  const teams = scenario.teams;
  if (!Array.isArray(teams) || teams.length !== 2) return null;
  const home = parseTeam(teams[0]);
  const away = parseTeam(teams[1]);
  if (home === null || away === null) return null;
  return { teams: [home, away] };
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatAbility(value: number | null): string {
  return value === null ? "—" : formatNumber(value);
}

function displayValue(group: GroupId, value: number): string {
  return group === "position" ? String(value) : formatNumber(value / 5);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const POSITION_ATTRIBUTE_COUNT = 15;

function bulkValueMessage(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return "请输入要应用的显示值";
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 1 || value > 20) {
    return "显示值需为 1–20 且按 0.2 步进";
  }
  const scaled = value * 5;
  if (Math.abs(scaled - Math.round(scaled)) > 1e-6) {
    return "显示值需为 1–20 且按 0.2 步进";
  }
  return null;
}

function positionValueMessage(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return "请输入要应用的位置熟练度";
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < 0 || value > 20) {
    return "位置熟练度需为 0–20 的整数";
  }
  return null;
}

function validateCellValue(index: number, raw: string): string | null {
  const label = ATTRIBUTE_LABELS[index];
  const trimmed = raw.trim();
  if (trimmed === "") return `属性“${label}”不能为空`;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return `属性“${label}”必须是数字`;
  if (index < POSITION_ATTRIBUTE_COUNT) {
    if (!Number.isInteger(value) || value < 0 || value > 20) {
      return `属性“${label}”必须是 0–20 的整数`;
    }
    return null;
  }
  if (value < 1 || value > 20) return `属性“${label}”必须是 1–20 之间的显示值`;
  const scaled = value * 5;
  if (Math.abs(scaled - Math.round(scaled)) > 1e-6) {
    return `属性“${label}”必须以 0.2 为步进`;
  }
  return null;
}

function cellValuesCount(payload: DraftAttributePayload): number {
  const values = payload.params.values;
  return isRecord(values) ? Object.keys(values).length : 0;
}

export function PlayersPage() {
  const { connection } = useAppContext();
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [side, setSide] = useState<0 | 1>(0);
  const [selectedPlayer, setSelectedPlayer] = useState(0);
  const [showHidden, setShowHidden] = useState(false);
  const [operation, setOperation] = useState<DraftAttributeOperation>("bulk");
  const [scope, setScope] = useState<EditableScope>("all");
  const [bulkValue, setBulkValue] = useState("");
  const [bulkGroups, setBulkGroups] = useState<BulkGroup[]>(defaultBulkGroups);
  const [includePersonality, setIncludePersonality] = useState(false);
  const [positionCode, setPositionCode] = useState("ST");
  const [positionValue, setPositionValue] = useState("");
  const [copySourceIndex, setCopySourceIndex] = useState(0);
  const [copyGroups, setCopyGroups] = useState<BulkGroup[]>(defaultBulkGroups);
  const [copyPersonality, setCopyPersonality] = useState(true);
  const [attributeError, setAttributeError] = useState<string | null>(null);
  const [attributeNotice, setAttributeNotice] = useState<string | null>(null);
  const [cellEdits, setCellEdits] = useState<Record<string, string>>({});
  const [cellError, setCellError] = useState<string | null>(null);
  const [cellErrorIndex, setCellErrorIndex] = useState<number | null>(null);
  const [cellNotice, setCellNotice] = useState<string | null>(null);

  const drafts = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null,
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

  const queryClient = useQueryClient();
  const applyAttributes = useMutation({
    mutationFn: (payload: DraftAttributePayload) =>
      applyDraftAttributes(connection!, activeDraftId!, payload),
    onSuccess: async (result) => {
      setAttributeError(null);
      setAttributeNotice(`已更新 ${result.changed_players} 名球员`);
      setCellEdits({});
      setCellError(null);
      setCellErrorIndex(null);
      await queryClient.invalidateQueries({
        queryKey: ["draft", connection?.url, activeDraftId],
      });
    },
    onError: (error) => {
      setAttributeNotice(null);
      setAttributeError(errorMessage(error));
    },
  });

  const saveCells = useMutation({
    mutationFn: (payload: DraftAttributePayload) =>
      applyDraftAttributes(connection!, activeDraftId!, payload),
    onSuccess: async (_result, payload) => {
      setCellError(null);
      setCellErrorIndex(null);
      setCellNotice(`已更新 ${cellValuesCount(payload)} 项属性`);
      setCellEdits((previous) => {
        const submitted = payload.params.values;
        if (!isRecord(submitted)) return {};
        const next = { ...previous };
        for (const key of Object.keys(submitted)) delete next[key];
        return next;
      });
      await queryClient.invalidateQueries({
        queryKey: ["draft", connection?.url, activeDraftId],
      });
    },
    onError: (error) => {
      setCellNotice(null);
      setCellErrorIndex(null);
      setCellError(errorMessage(error));
    },
  });

  const dirtyCount = Object.keys(cellEdits).length;

  useEffect(() => {
    if (dirtyCount === 0) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirtyCount]);

  const confirmDiscardCellsForBulk = (): boolean => {
    const count = Object.keys(cellEdits).length;
    if (count === 0) return true;
    return window.confirm(
      `有 ${count} 项单项属性修改尚未保存，继续该操作将放弃这些修改，确定继续吗？`,
    );
  };

  const confirmDiscardEdits = (): boolean => {
    const count = Object.keys(cellEdits).length;
    if (count === 0) return true;
    return window.confirm(`有 ${count} 项属性修改尚未保存，确定放弃吗？`);
  };

  const resetCellEdits = () => {
    setCellEdits({});
    setCellError(null);
    setCellErrorIndex(null);
  };

  const updateCell = (index: number, raw: string, original: string) => {
    setCellError(null);
    setCellErrorIndex(null);
    setCellNotice(null);
    setCellEdits((previous) => {
      const next = { ...previous };
      const trimmed = raw.trim();
      const unchanged =
        trimmed === original ||
        (trimmed !== "" && Number(trimmed) === Number(original));
      if (unchanged) delete next[String(index)];
      else next[String(index)] = raw;
      return next;
    });
  };

  const discardCellEdits = () => {
    resetCellEdits();
    setCellNotice(null);
  };

  const saveCellEdits = () => {
    if (connection === null || activeDraftId === null) return;
    const indexes = Object.keys(cellEdits)
      .map((key) => Number(key))
      .sort((left, right) => left - right);
    if (indexes.length === 0) return;
    const values: Record<string, number> = {};
    for (const index of indexes) {
      const raw = cellEdits[String(index)] ?? "";
      const message = validateCellValue(index, raw);
      if (message !== null) {
        setCellError(message);
        setCellErrorIndex(index);
        setCellNotice(null);
        return;
      }
      values[String(index)] = Number(raw.trim());
    }
    setCellError(null);
    setCellErrorIndex(null);
    saveCells.mutate({
      side: side === 0 ? "home" : "away",
      scope: "player",
      player_index: playerIndex,
      operation: "cells",
      params: { values },
    });
  };

  const changeDraft = (event: ChangeEvent<HTMLSelectElement>) => {
    const draftId = event.target.value;
    if (draftId === activeDraftId) return;
    if (!confirmDiscardEdits()) {
      event.target.value = activeDraftId ?? "";
      return;
    }
    setSelectedDraftId(draftId);
    setSelectedPlayer(0);
    setAttributeError(null);
    setAttributeNotice(null);
    setCellError(null);
    setCellErrorIndex(null);
    setCellNotice(null);
    setCellEdits({});
  };

  const changeSide = (next: 0 | 1) => {
    if (next === side) return;
    if (!confirmDiscardEdits()) return;
    setSide(next);
    setSelectedPlayer(0);
    setAttributeError(null);
    setAttributeNotice(null);
    setCellError(null);
    setCellErrorIndex(null);
    setCellNotice(null);
    setCellEdits({});
  };

  const selectPlayer = (index: number) => {
    if (index === playerIndex) return;
    if (!confirmDiscardEdits()) return;
    setSelectedPlayer(index);
    resetCellEdits();
    setCellNotice(null);
  };

  const scenario = detail.data === undefined ? null : parseScenario(detail.data.scenario);
  const team = scenario === null ? null : scenario.teams[side];
  const players = team?.players ?? [];
  const playerIndex = selectedPlayer < players.length ? selectedPlayer : 0;
  const player = players[playerIndex];
  const rosterNotice = team === null ? null : rosterNoticeText(team.roster);
  const visibleGroups = ATTRIBUTE_GROUPS.filter(
    (group) => group.id !== "hidden" || showHidden,
  );

  const referenceIndex = players[copySourceIndex] === undefined ? 0 : copySourceIndex;
  const missingGroups =
    (operation === "bulk" && bulkGroups.length === 0) ||
    (operation === "copy" && copyGroups.length === 0);
  const valueHint =
    operation === "bulk"
      ? bulkValueMessage(bulkValue)
      : operation === "position"
        ? positionValueMessage(positionValue)
        : null;
  const groupsHint = missingGroups ? "请至少选择一个分组" : null;
  const blockedReason =
    valueHint === null
      ? groupsHint
      : groupsHint === null
        ? valueHint
        : `${valueHint}；${groupsHint}`;

  const submitAttributes = (event: FormEvent) => {
    event.preventDefault();
    if (connection === null || activeDraftId === null) return;
    const payload: DraftAttributePayload = {
      side: side === 0 ? "home" : "away",
      scope,
      operation,
      params: {},
    };
    if (scope === "player") payload.player_index = playerIndex;
    if (operation === "bulk") {
      const message = bulkValueMessage(bulkValue);
      if (message !== null) {
        setAttributeNotice(null);
        setAttributeError(message);
        return;
      }
      payload.params = {
        value: Number(bulkValue.trim()),
        groups: orderedGroups(bulkGroups),
        include_personality: includePersonality,
      };
    } else if (operation === "position") {
      const message = positionValueMessage(positionValue);
      if (message !== null) {
        setAttributeNotice(null);
        setAttributeError(message);
        return;
      }
      payload.params = { position: positionCode, value: Number(positionValue.trim()) };
    } else if (operation === "copy") {
      payload.params = {
        source_uid: players[referenceIndex].sourceUid,
        groups: orderedGroups(copyGroups),
        copy_personality: copyPersonality,
      };
    }
    if (!confirmDiscardCellsForBulk()) return;
    applyAttributes.mutate(payload);
  };

  const undoAttributes = () => {
    if (connection === null || activeDraftId === null) return;
    if (!confirmDiscardCellsForBulk()) return;
    applyAttributes.mutate({
      side: side === 0 ? "home" : "away",
      scope: "all",
      operation: "undo",
      params: {},
    });
  };

  const attributeEditor =
    connection === null ||
    activeDraftId === null ||
    scenario === null ||
    team === null ||
    player === undefined ? null : (
      <details className="players-advanced">
        <summary>高级批量工具</summary>
        <section className="players-bulk" aria-label="批量属性编辑">
        <form
          className="players-bulk-form"
          aria-label="批量属性编辑表单"
          onSubmit={submitAttributes}
        >
          <label className="field">
            操作
            <select
              aria-label="操作"
              value={operation}
              onChange={(event) =>
                setOperation(event.target.value as DraftAttributeOperation)
              }
            >
              <option value="bulk">统一属性</option>
              <option value="position">位置熟练度</option>
              <option value="copy">从参考球员复制</option>
              <option value="undo">撤销</option>
            </select>
          </label>
          {operation === "undo" ? null : (
            <label className="field">
              范围
              <select
                aria-label="范围"
                value={scope}
                onChange={(event) => setScope(event.target.value as EditableScope)}
              >
                <option value="all">全队</option>
                <option value="starters">首发</option>
                <option value="player">当前球员</option>
              </select>
            </label>
          )}
          {operation === "bulk" ? (
            <>
              <label className="field players-bulk-value">
                显示值
                <input
                  aria-label="显示值"
                  type="number"
                  min={1}
                  max={20}
                  step={0.2}
                  placeholder="如 12"
                  value={bulkValue}
                  onChange={(event) => setBulkValue(event.target.value)}
                />
              </label>
              <GroupPicker selected={bulkGroups} onChange={setBulkGroups} />
              <label className="field-inline">
                <input
                  type="checkbox"
                  checked={includePersonality}
                  onChange={(event) => setIncludePersonality(event.target.checked)}
                />
                包含性格
              </label>
            </>
          ) : null}
          {operation === "position" ? (
            <>
              <label className="field">
                位置
                <select
                  aria-label="位置"
                  value={positionCode}
                  onChange={(event) => setPositionCode(event.target.value)}
                >
                  {POSITION_CODES.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field players-bulk-value">
                位置熟练度
                <input
                  aria-label="位置熟练度"
                  type="number"
                  min={0}
                  max={20}
                  step={1}
                  placeholder="如 10"
                  value={positionValue}
                  onChange={(event) => setPositionValue(event.target.value)}
                />
              </label>
            </>
          ) : null}
          {operation === "copy" ? (
            <>
              <label className="field players-bulk-reference">
                参考球员
                <select
                  aria-label="参考球员"
                  value={String(referenceIndex)}
                  onChange={(event) => setCopySourceIndex(Number(event.target.value))}
                >
                  {players.map((item, index) => (
                    <option key={`${item.uid}-${index}`} value={index}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <GroupPicker selected={copyGroups} onChange={setCopyGroups} />
              <label className="field-inline">
                <input
                  type="checkbox"
                  checked={copyPersonality}
                  onChange={(event) => setCopyPersonality(event.target.checked)}
                />
                复制性格
              </label>
            </>
          ) : null}
          <div className="players-bulk-actions">
            <button
              className="button primary"
              type="submit"
              disabled={applyAttributes.isPending || blockedReason !== null}
            >
              应用
            </button>
            <button
              className="button"
              type="button"
              disabled={applyAttributes.isPending}
              onClick={undoAttributes}
            >
              撤销
            </button>
          </div>
        </form>
        {blockedReason === null ? null : (
          <p className="players-bulk-hint" role="status" aria-live="polite">
            {blockedReason}
          </p>
        )}
        {attributeError === null ? null : (
          <div className="inline-alert" role="alert">
            {attributeError}
          </div>
        )}
        {attributeNotice === null ? null : (
          <p className="jobs-notice" role="status" aria-live="polite">
            {attributeNotice}
          </p>
        )}
        </section>
      </details>
    );

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={UsersThree}
        title="sidecar 未连接"
        description="连接 sidecar 后可以查看草稿球队的球员名单与属性分组。"
      />
    );
  } else if (drafts.isPending) {
    body = (
      <p className="jobs-loading" role="status">
        正在加载草稿…
      </p>
    );
  } else if (drafts.isError) {
    body = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(drafts.error)}</span>
        <button className="button small" type="button" onClick={() => void drafts.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (draftItems.length === 0) {
    body = (
      <EmptyState
        icon={UsersThree}
        title="暂无草稿"
        description="创建场景草案后，这里会显示主客队各 23 名球员与六组属性。"
      />
    );
  } else {
    let content: ReactNode;
    if (detail.isPending) {
      content = (
        <p className="jobs-loading" role="status">
          正在加载球员属性…
        </p>
      );
    } else if (detail.isError) {
      content = (
        <div className="inline-alert" role="alert">
          <span>{errorMessage(detail.error)}</span>
          <button className="button small" type="button" onClick={() => void detail.refetch()}>
            重试
          </button>
        </div>
      );
    } else if (scenario === null || team === null || player === undefined) {
      content = (
        <div className="inline-alert" role="alert">
          场景数据无效：需要两支球队各 23 名球员与 69 项属性。
        </div>
      );
    } else {
      const selected = player;
      content = (
        <div className="players-layout">
          <aside
            className="players-roster"
            aria-label={`${side === 0 ? "主队" : "客队"}球员名单`}
          >
            <div className="players-list-head" aria-hidden="true">
              <span>球员</span>
              <span>位置</span>
              <span>能力</span>
            </div>
            <ol className="players-list">
              {team.players.map((item, index) => (
                <li key={`${item.uid}-${index}`}>
                  <button
                    className="players-row"
                    type="button"
                    aria-pressed={index === playerIndex}
                    onClick={() => selectPlayer(index)}
                  >
                    <span className="players-row-name">
                      <span className="players-row-label">{item.name}</span>
                      {item.generated ? <span className="badge">占位</span> : null}
                    </span>
                    <span
                      className="players-row-position"
                      title={ATTRIBUTE_LABELS[item.position]}
                    >
                      {POSITION_CODES[item.position]}
                    </span>
                    <span className="players-row-ability">{formatAbility(item.ability)}</span>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
          <section className="players-detail" aria-label="选中球员属性">
            <div className="players-selected">
              <strong>{selected.name}</strong>
              {selected.generated ? <span className="badge">占位</span> : null}
              <span className="badge" title={ATTRIBUTE_LABELS[selected.position]}>
                {POSITION_CODES[selected.position]}
              </span>
              <span className="players-selected-ability">
                <span className="players-ability-label">能力</span>
                {formatAbility(selected.ability)}
              </span>
              {team.name === null ? null : <span className="players-team">{team.name}</span>}
            </div>
            {dirtyCount === 0 ? null : (
              <div className="players-edit-actions">
                <span className="players-dirty-count" aria-live="polite">
                  已修改 {dirtyCount} 项
                </span>
                {saveCells.isPending ? (
                  <span className="players-edit-pending" role="status" aria-live="polite">
                    正在保存…
                  </span>
                ) : null}
                <button
                  className="button primary"
                  type="button"
                  disabled={saveCells.isPending}
                  onClick={saveCellEdits}
                >
                  保存修改（{dirtyCount}）
                </button>
                <button
                  className="button"
                  type="button"
                  disabled={saveCells.isPending}
                  onClick={discardCellEdits}
                >
                  放弃
                </button>
              </div>
            )}
            {cellError === null ? null : (
              <div className="inline-alert" role="alert" id="players-cell-error">
                {cellError}
              </div>
            )}
            {cellNotice === null ? null : (
              <p className="jobs-notice" role="status" aria-live="polite">
                {cellNotice}
              </p>
            )}
            <div className="players-groups">
              {visibleGroups.map((group) => (
                <section
                  className="players-group"
                  key={group.id}
                  aria-labelledby={`players-group-${group.id}`}
                >
                  <h3 id={`players-group-${group.id}`}>{group.title}</h3>
                  <dl className="players-attributes">
                    {group.indices.map((index) => {
                      const original = displayValue(group.id, selected.attributes[index]);
                      const edited = cellEdits[String(index)];
                      const dirty = edited !== undefined;
                      return (
                        <div
                          className={dirty ? "players-attribute is-dirty" : "players-attribute"}
                          key={index}
                        >
                          <dt>{ATTRIBUTE_LABELS[index]}</dt>
                          <dd className="players-attribute-value">
                            <input
                              className="players-attribute-input"
                              type="number"
                              aria-label={ATTRIBUTE_LABELS[index]}
                              aria-invalid={cellErrorIndex === index ? true : undefined}
                              aria-describedby={
                                cellErrorIndex === index ? "players-cell-error" : undefined
                              }
                              min={group.id === "position" ? 0 : 1}
                              max={20}
                              step={group.id === "position" ? 1 : 0.2}
                              value={edited ?? original}
                              disabled={saveCells.isPending}
                              onChange={(event) => updateCell(index, event.target.value, original)}
                            />
                            {dirty ? <span className="players-attribute-dirty">已修改</span> : null}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                </section>
              ))}
            </div>
          </section>
        </div>
      );
    }
    body = (
      <>
        <div className="players-toolbar">
          <label className="field players-draft">
            草稿
            <select
              aria-label="选择草稿"
              value={activeDraftId ?? ""}
              onChange={changeDraft}
            >
              {draftItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="segmented" role="group" aria-label="球队">
            <button type="button" aria-pressed={side === 0} onClick={() => changeSide(0)}>
              主队
            </button>
            <button type="button" aria-pressed={side === 1} onClick={() => changeSide(1)}>
              客队
            </button>
          </div>
          <label className="field-inline players-hidden-toggle">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => setShowHidden(event.target.checked)}
            />
            显示隐藏属性
          </label>
        </div>
        {rosterNotice === null ? null : (
          <p className="players-roster-notice" role="status" aria-label="名单兼容提示">
            {rosterNotice}
          </p>
        )}
        {attributeEditor}
        {content}
      </>
    );
  }

  return <Panel title="球员属性">{body}</Panel>;
}
