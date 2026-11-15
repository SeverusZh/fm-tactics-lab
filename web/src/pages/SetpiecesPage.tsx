import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Target } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { Skeleton } from "../components/Skeleton";
import {
  exportSetpieceFile,
  getSetpiece,
  importSetpieceFile,
  listSetpieces,
  saveSetpiece,
  type SetpieceCatalog,
  type SetpieceDetail,
  type SetpieceImportInput,
  type SetpieceOption,
  type SetpieceRoutine,
  type SetpieceType,
  type SetpieceValue,
} from "../lib/api-setpieces";
import { downloadBlob } from "../lib/download";
import { chooseLocalFile, isDesktopShell } from "../lib/file-dialog";
import "../styles/setpieces.css";

const ROLE_GROUP_IDS = [0, 1, 2, 3, 4, 5, 6, 7];
const MAX_ROUTINE_VARIANTS = 3;
const MAX_GROUP_TASKS = 10;
const BACKUP_TASK_LIMIT = 16;
const NAME_LIMIT = 64;
const DEFAULT_SETPIECE_ID = "home";
const DOCUMENT_FILTER = [{ name: "定位球文档", extensions: ["json"] }];
const SPECIAL_STRATEGY_VALUES = new Set([3, 4, 6]);
const THROW_STYLE_OPTIONS = [
  ["保持球权", "沿边线推进"],
  ["保持球权", "沿边线推进"],
  ["短距离", "长距离"],
];
const THROW_STYLE_LABELS = ["后场", "中场", "前场"];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function totalTasks(routine: SetpieceRoutine): number {
  return routine.groups.reduce((total, tasks) => total + tasks.length, 0);
}

function groupLabel(catalog: SetpieceCatalog, group: number): string {
  return catalog.categories.find((entry) => entry.id === group)?.label ?? "角色类别 " + (group + 1);
}

function typeLabel(catalog: SetpieceCatalog, typeId: number): string {
  return catalog.types.find((entry) => entry.id === typeId)?.label ?? "定位球 " + (typeId + 1);
}

function taskOptions(catalog: SetpieceCatalog, group: number): SetpieceOption[] {
  const source = group < 4 ? catalog.defend : catalog.attack;
  const allowed = catalog.allowed[String(group)] ?? [];
  return source.filter((option) => allowed.includes(option.id));
}

function taskLabel(catalog: SetpieceCatalog, task: number): string {
  const option = [...catalog.attack, ...catalog.defend].find((entry) => entry.id === task);
  return option === undefined ? "任务 " + task : option.label;
}

function strategyOptions(catalog: SetpieceCatalog, type: SetpieceType): SetpieceOption[] {
  if (type.strategy_kind === null) {
    return [];
  }
  const options = (catalog as unknown as Record<string, unknown>)[type.strategy_kind];
  return Array.isArray(options) ? (options as SetpieceOption[]) : [];
}

function strategyChoices(
  catalog: SetpieceCatalog,
  type: SetpieceType,
  base: SetpieceRoutine | null,
): SetpieceOption[] {
  const options = strategyOptions(catalog, type);
  if (base === null || base.strategy !== 255) {
    return options;
  }
  return options.filter((option) => SPECIAL_STRATEGY_VALUES.has(option.id));
}

function routineAt(value: SetpieceValue, typeId: number, variant: number): SetpieceRoutine | null {
  const rows = value.routines[String(typeId)];
  if (rows === undefined || rows.length === 0) {
    return null;
  }
  return rows[Math.min(variant, rows.length - 1)] ?? null;
}

function validationProblem(
  draft: SetpieceValue,
  detail: SetpieceDetail,
  catalog: SetpieceCatalog,
  typeId: number,
  variant: number,
): string | null {
  const routine = routineAt(draft, typeId, variant);
  const base = detail.default.routines[String(typeId)]?.[0] ?? null;
  if (routine === null || base === null) {
    return "当前套路不存在";
  }
  if (routine.name.trim() === "") {
    return "套路名称不能为空";
  }
  const expected = totalTasks(base);
  const actual = totalTasks(routine);
  if (actual > expected) {
    return typeLabel(catalog, typeId) + "最多分配" + expected + "项任务，当前为" + actual + "项；请先移除多余任务";
  }
  if (actual < expected) {
    return typeLabel(catalog, typeId) + "需要分配" + expected + "项任务，当前为" + actual + "项；请继续添加任务";
  }
  return null;
}

function formatTime(value: string | null): string {
  if (value === null) {
    return "尚未保存";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function readFileBytes(file: File): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("定位球文档无法读取"));
    reader.readAsArrayBuffer(file);
  });
}

function base64FromBytes(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

export function SetpiecesPage() {
  const { connection } = useAppContext();
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState(DEFAULT_SETPIECE_ID);
  const [typeId, setTypeId] = useState(0);
  const [variant, setVariant] = useState(0);
  const [draft, setDraft] = useState<SetpieceValue | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [pendingTasks, setPendingTasks] = useState<Record<string, number>>({});
  const [pendingRoles, setPendingRoles] = useState<Record<string, number>>({});
  const [pendingTeam, setPendingTeam] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);
  const teamSelectRef = useRef<HTMLSelectElement | null>(null);
  const lastAppliedRef = useRef<SetpieceValue | null>(null);
  const forceApplyRef = useRef(false);
  const connectionUrl = connection?.url ?? "";

  const listQuery = useQuery({
    queryKey: ["setpieces", connectionUrl],
    queryFn: () => listSetpieces(connection!),
    enabled: connection !== null,
  });
  const detailQuery = useQuery({
    queryKey: ["setpiece", connectionUrl, activeId],
    queryFn: () => getSetpiece(connection!, activeId),
    enabled: connection !== null,
  });

  useEffect(() => {
    const data = detailQuery.data;
    if (data === undefined) {
      return;
    }
    const serverValue = cloneValue(data.value);
    setDraft((current) => {
      if (forceApplyRef.current) {
        forceApplyRef.current = false;
        lastAppliedRef.current = cloneValue(serverValue);
        return serverValue;
      }
      if (
        current !== null &&
        lastAppliedRef.current !== null &&
        JSON.stringify(current) !== JSON.stringify(lastAppliedRef.current)
      ) {
        return current;
      }
      lastAppliedRef.current = cloneValue(serverValue);
      return serverValue;
    });
  }, [detailQuery.data]);

  const detail = detailQuery.data ?? null;

  const applyDetail = (data: SetpieceDetail) => {
    queryClient.setQueryData<SetpieceDetail>(["setpiece", connectionUrl, activeId], data);
    void queryClient.invalidateQueries({ queryKey: ["setpieces", connectionUrl] });
  };
  const saveMutation = useMutation({
    mutationFn: () => saveSetpiece(connection!, activeId, draft!),
    onSuccess: (data) => {
      setNotice("已保存定位球配置");
      setError(null);
      lastAppliedRef.current = cloneValue(data.value);
      setDraft(cloneValue(data.value));
      applyDetail(data);
    },
    onError: (mutationError) => {
      setNotice(null);
      setError(errorMessage(mutationError));
    },
  });
  const importMutation = useMutation({
    mutationFn: (input: SetpieceImportInput) => importSetpieceFile(connection!, activeId, input),
    onSuccess: (data) => {
      setNotice("已导入定位球文档");
      setError(null);
      lastAppliedRef.current = cloneValue(data.value);
      setDraft(cloneValue(data.value));
      applyDetail(data);
    },
    onError: (mutationError) => {
      setNotice(null);
      setError(errorMessage(mutationError));
    },
  });

  const catalog = listQuery.data?.catalog ?? null;
  const rows = draft === null ? null : draft.routines[String(typeId)] ?? null;
  const safeVariant = rows === null ? 0 : Math.min(variant, Math.max(rows.length - 1, 0));
  const routine = rows === null ? null : routineAt(draft!, typeId, safeVariant);
  const setpieceType = catalog === null ? null : catalog.types.find((entry) => entry.id === typeId) ?? null;
  const baseRoutine = detail === null ? null : detail.default.routines[String(typeId)]?.[0] ?? null;
  const problem =
    draft !== null && detail !== null && catalog !== null
      ? validationProblem(draft, detail, catalog, typeId, safeVariant)
      : "定位球配置尚未加载";
  const dirty =
    draft !== null && detail !== null && JSON.stringify(draft) !== JSON.stringify(detail.value);

  useEffect(() => {
    if (!dirty) {
      return;
    }
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  useEffect(() => {
    if (pendingTeam !== null) {
      confirmButtonRef.current?.focus();
    }
  }, [pendingTeam]);

  function switchTeam(nextId: string): void {
    forceApplyRef.current = true;
    setActiveId(nextId);
    setVariant(0);
    setNotice(null);
    setError(null);
    setPendingTeam(null);
    teamSelectRef.current?.focus();
  }

  function closeSwitchDialog(): void {
    setPendingTeam(null);
    teamSelectRef.current?.focus();
  }

  function updateRoutine(updater: (current: SetpieceRoutine) => SetpieceRoutine): void {
    if (draft === null) {
      return;
    }
    const currentRows = draft.routines[String(typeId)];
    if (currentRows === undefined) {
      return;
    }
    const nextRows = currentRows.map((row, index) => (index === safeVariant ? updater(row) : row));
    setDraft({ ...draft, routines: { ...draft.routines, [String(typeId)]: nextRows } });
  }

  function movePriority(index: number, delta: number): void {
    updateRoutine((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.priority.length) {
        return current;
      }
      const priority = [...current.priority];
      const moved = priority[index];
      const replaced = priority[target];
      priority[index] = replaced;
      priority[target] = moved;
      return { ...current, priority };
    });
  }

  function setTask(group: number, slot: number, task: number): void {
    updateRoutine((current) => ({
      ...current,
      groups: current.groups.map((tasks, index) =>
        index === group ? tasks.map((value, position) => (position === slot ? task : value)) : tasks,
      ),
    }));
  }

  function setBackup(group: number, slot: number, backup: number): void {
    updateRoutine((current) => ({
      ...current,
      backups: current.backups.map((values, index) =>
        index === group ? values.map((value, position) => (position === slot ? backup : value)) : values,
      ),
    }));
  }

  function addTask(group: number): void {
    if (catalog === null) {
      return;
    }
    const options = taskOptions(catalog, group);
    const selected = pendingTasks[String(group)] ?? options[0]?.id;
    if (selected === undefined) {
      return;
    }
    updateRoutine((current) => {
      const tasks = current.groups[group];
      if (tasks.length >= MAX_GROUP_TASKS) {
        return current;
      }
      return {
        ...current,
        groups: current.groups.map((values, index) => (index === group ? [...values, selected] : values)),
        backups: current.backups.map((values, index) => (index === group ? [...values, 0] : values)),
      };
    });
  }

  function removeTask(group: number, slot: number): void {
    updateRoutine((current) => ({
      ...current,
      groups: current.groups.map((tasks, index) =>
        index === group ? tasks.filter((_, position) => position !== slot) : tasks,
      ),
      backups: current.backups.map((values, index) =>
        index === group ? values.filter((_, position) => position !== slot) : values,
      ),
    }));
  }

  function copyRoutine(): void {
    if (draft === null || routine === null || rows === null || rows.length >= MAX_ROUTINE_VARIANTS) {
      return;
    }
    const copy = { ...cloneValue(routine), name: (routine.name + " 副本").slice(0, NAME_LIMIT) };
    const nextRows = [...rows, copy];
    setDraft({ ...draft, routines: { ...draft.routines, [String(typeId)]: nextRows } });
    setVariant(nextRows.length - 1);
  }

  function deleteRoutine(): void {
    if (draft === null || rows === null || rows.length <= 1) {
      return;
    }
    const nextRows = rows.filter((_, index) => index !== safeVariant);
    setDraft({ ...draft, routines: { ...draft.routines, [String(typeId)]: nextRows } });
    setVariant(Math.max(0, safeVariant - 1));
  }

  function restoreRoutine(): void {
    if (draft === null || baseRoutine === null || rows === null) {
      return;
    }
    const nextRows = rows.map((row, index) => (index === safeVariant ? cloneValue(baseRoutine) : row));
    setDraft({ ...draft, routines: { ...draft.routines, [String(typeId)]: nextRows } });
  }

  function restoreAll(): void {
    if (detail === null) {
      return;
    }
    setDraft(cloneValue(detail.default));
    setNotice("已恢复为默认定位球配置，保存后生效");
    setError(null);
  }

  function setThrowStyle(index: number, value: number): void {
    if (draft === null) {
      return;
    }
    setDraft({ ...draft, throw_styles: draft.throw_styles.map((style, position) => (position === index ? value : style)) });
  }

  function moveRole(group: number, index: number, delta: number): void {
    if (draft === null) {
      return;
    }
    const current = draft.role_priorities[String(group)] ?? [];
    const target = index + delta;
    if (target < 0 || target >= current.length) {
      return;
    }
    const next = [...current];
    const moved = next[index];
    const replaced = next[target];
    next[index] = replaced;
    next[target] = moved;
    setDraft({ ...draft, role_priorities: { ...draft.role_priorities, [String(group)]: next } });
  }

  function removeRole(group: number, index: number): void {
    if (draft === null) {
      return;
    }
    const current = draft.role_priorities[String(group)] ?? [];
    setDraft({
      ...draft,
      role_priorities: { ...draft.role_priorities, [String(group)]: current.filter((_, position) => position !== index) },
    });
  }

  function addRole(group: number): void {
    if (draft === null || detail === null) {
      return;
    }
    const assigned = new Set(Object.values(draft.role_priorities).flat());
    const available = detail.players.filter((player) => !assigned.has(player.index));
    const selected = pendingRoles[String(group)] ?? available[0]?.index;
    if (selected === undefined) {
      return;
    }
    const current = draft.role_priorities[String(group)] ?? [];
    if (current.length >= detail.roster_size) {
      return;
    }
    setDraft({
      ...draft,
      role_priorities: { ...draft.role_priorities, [String(group)]: [...current, selected] },
    });
    setPendingRoles((values) => {
      const next = { ...values };
      delete next[String(group)];
      return next;
    });
  }

  async function pickDocument(): Promise<void> {
    setError(null);
    setNotice(null);
    if (isDesktopShell()) {
      try {
        const path = await chooseLocalFile({ title: "选择定位球文档", filters: DOCUMENT_FILTER });
        if (path !== null) {
          importMutation.mutate({ source_path: path });
        }
      } catch (dialogError) {
        setError(errorMessage(dialogError));
      }
      return;
    }
    fileInputRef.current?.click();
  }

  async function onDocumentSelected(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) {
      return;
    }
    try {
      const bytes = await readFileBytes(file);
      importMutation.mutate({ content_base64: base64FromBytes(bytes) });
    } catch (readError) {
      setError(errorMessage(readError));
    }
  }

  async function exportDocument(): Promise<void> {
    if (connection === null) {
      return;
    }
    setError(null);
    setNotice(null);
    setExporting(true);
    try {
      const { blob, filename } = await exportSetpieceFile(connection, activeId);
      downloadBlob(blob, filename);
      setNotice("已导出定位球文档");
    } catch (exportError) {
      setError(errorMessage(exportError));
    } finally {
      setExporting(false);
    }
  }

  if (connection === null) {
    return (
      <EmptyState
        icon={Target}
        title="sidecar 未连接"
        description="连接 sidecar 后即可编辑定位球配置，并导入导出定位球文档。"
      />
    );
  }

  if (listQuery.isPending) {
    return <Skeleton label="正在加载定位球配置" variant="rows" count={6} />;
  }

  if (listQuery.isError) {
    return (
      <Panel title="定位球配置">
        <p className="setpieces-alert" role="alert">
          {errorMessage(listQuery.error)}
        </p>
        <button className="button" type="button" onClick={() => void listQuery.refetch()}>
          重试
        </button>
      </Panel>
    );
  }

  if (detailQuery.isError) {
    return (
      <Panel title="定位球配置">
        <p className="setpieces-alert" role="alert">
          {errorMessage(detailQuery.error)}
        </p>
        <button className="button" type="button" onClick={() => void detailQuery.refetch()}>
          重试
        </button>
      </Panel>
    );
  }

  if (catalog === null || detail === null || draft === null || routine === null || rows === null) {
    return <Skeleton label="正在加载定位球配置" variant="rows" count={6} />;
  }

  const strategyField = setpieceType === null ? [] : strategyChoices(catalog, setpieceType, baseRoutine);
  const showSwing = baseRoutine !== null && baseRoutine.swing !== 255 && setpieceType !== null && setpieceType.swing;
  const totalExpected = baseRoutine === null ? 0 : totalTasks(baseRoutine);
  const assigned = new Set(Object.values(draft.role_priorities).flat());
  const availablePlayers = detail.players.filter((player) => !assigned.has(player.index));
  const saveDisabled = saveMutation.isPending || problem !== null;

  return (
    <div className="page-grid">
      <Panel
        title="定位球配置"
        className="span-7"
        action={
          <span className="badge" data-tone={dirty ? "warn" : "ok"}>
            {dirty ? "未保存" : "已保存"}
          </span>
        }
      >
        <div className="setpieces-toolbar">
          <div className="field">
            <label htmlFor="setpiece-team">队伍</label>
            <select
              id="setpiece-team"
              ref={teamSelectRef}
              value={activeId}
              onChange={(event) => {
                const nextId = event.target.value;
                if (nextId === activeId) {
                  return;
                }
                if (dirty) {
                  setPendingTeam(nextId);
                  return;
                }
                switchTeam(nextId);
              }}
            >
              {listQuery.data.setpieces.map((entry) => (
                <option key={entry.setpiece_id} value={entry.setpiece_id}>
                  {entry.team}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="setpiece-type">定位球类型</label>
            <select
              id="setpiece-type"
              value={typeId}
              onChange={(event) => {
                setTypeId(Number(event.target.value));
                setVariant(0);
              }}
            >
              {catalog.types.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="setpiece-variant">套路</label>
            <select id="setpiece-variant" value={safeVariant} onChange={(event) => setVariant(Number(event.target.value))}>
              {rows.map((row, index) => (
                <option key={index} value={index}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
          <div className="setpieces-toolbar-actions">
            <button
              className="button"
              type="button"
              onClick={copyRoutine}
              disabled={rows.length >= MAX_ROUTINE_VARIANTS}
              title={rows.length >= MAX_ROUTINE_VARIANTS ? "每个定位球类型最多 3 套套路" : undefined}
            >
              复制套路
            </button>
            <button
              className="button"
              type="button"
              onClick={deleteRoutine}
              disabled={rows.length <= 1}
              title={rows.length <= 1 ? "至少保留 1 套套路" : undefined}
            >
              删除套路
            </button>
            <button className="button" type="button" onClick={restoreRoutine}>
              恢复此套路
            </button>
          </div>
        </div>

        {pendingTeam !== null && (
          <div
            className="setpieces-confirm"
            role="alertdialog"
            aria-label="切换队伍确认"
            aria-modal="true"
            aria-describedby="setpiece-switch-warning"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                closeSwitchDialog();
              }
            }}
          >
            <p id="setpiece-switch-warning">切换队伍会丢弃未保存的修改。</p>
            <div className="setpieces-row-actions">
              <button
                ref={confirmButtonRef}
                className="button"
                type="button"
                onClick={() => switchTeam(pendingTeam)}
              >
                放弃修改并切换
              </button>
              <button className="button" type="button" onClick={closeSwitchDialog}>
                取消
              </button>
            </div>
          </div>
        )}

        <div className="setpieces-fields">
          <div className="field">
            <label htmlFor="setpiece-name">套路名称</label>
            <input
              id="setpiece-name"
              maxLength={NAME_LIMIT}
              value={routine.name}
              onChange={(event) =>
                updateRoutine((current) => ({ ...current, name: event.target.value.slice(0, NAME_LIMIT) }))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="setpiece-frequency">使用频率</label>
            <select
              id="setpiece-frequency"
              value={routine.frequency}
              onChange={(event) => updateRoutine((current) => ({ ...current, frequency: Number(event.target.value) }))}
            >
              {catalog.frequencies.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
          </div>
          {strategyField.length > 0 && (
            <div className="field">
              <label htmlFor="setpiece-strategy">发球策略</label>
              <select
                id="setpiece-strategy"
                value={routine.strategy}
                onChange={(event) => updateRoutine((current) => ({ ...current, strategy: Number(event.target.value) }))}
              >
                <option value={255}>不使用</option>
                {strategyField.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          {showSwing && (
            <div className="field">
              <label htmlFor="setpiece-swing">旋转方向</label>
              <select
                id="setpiece-swing"
                value={routine.swing}
                onChange={(event) => updateRoutine((current) => ({ ...current, swing: Number(event.target.value) }))}
              >
                {catalog.swing.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <p className="setpieces-hint">
          共 {totalTasks(routine)} 项任务，目标 {totalExpected} 项；已把 {assigned.size} 名球员分配到角色。
        </p>

        <div className="setpieces-groups">
          {routine.priority.map((group, index) => {
            const tasks = routine.groups[group] ?? [];
            const backups = routine.backups[group] ?? [];
            const options = taskOptions(catalog, group);
            const pending = pendingTasks[String(group)] ?? options[0]?.id ?? 0;
            const label = groupLabel(catalog, group);
            return (
              <section className="setpieces-group" key={group} aria-label={label}>
                <header className="setpieces-group-header">
                  <div className="setpieces-group-title">
                    <span className="setpieces-rank">{index + 1}</span>
                    <strong>{label}</strong>
                    <span className="setpieces-count">
                      {tasks.length} 项任务
                    </span>
                  </div>
                  <div className="setpieces-row-actions">
                    <button
                      className="button"
                      type="button"
                      aria-label={"上移" + label}
                      disabled={index === 0}
                      title={index === 0 ? "已在最前" : undefined}
                      onClick={() => movePriority(index, -1)}
                    >
                      上移
                    </button>
                    <button
                      className="button"
                      type="button"
                      aria-label={"下移" + label}
                      disabled={index === routine.priority.length - 1}
                      title={index === routine.priority.length - 1 ? "已在最后" : undefined}
                      onClick={() => movePriority(index, 1)}
                    >
                      下移
                    </button>
                  </div>
                </header>
                {tasks.length > 0 && (
                  <ul className="setpieces-slots">
                    {tasks.map((task, slot) => (
                      <li className="setpieces-slot" key={slot}>
                        <select
                          aria-label={label + " 第 " + (slot + 1) + " 项任务"}
                          value={task}
                          onChange={(event) => setTask(group, slot, Number(event.target.value))}
                        >
                          {options.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.label}
                            </option>
                          ))}
                          {!options.some((option) => option.id === task) && (
                            <option value={task}>{taskLabel(catalog, task)}</option>
                          )}
                        </select>
                        <select
                          aria-label={label + " 第 " + (slot + 1) + " 项备用任务"}
                          value={backups[slot] ?? 0}
                          onChange={(event) => setBackup(group, slot, Number(event.target.value))}
                        >
                          {Array.from({ length: BACKUP_TASK_LIMIT }, (_, value) => (
                            <option key={value} value={value}>
                              备用 {value}
                            </option>
                          ))}
                        </select>
                        <button
                          className="button"
                          type="button"
                          aria-label={"移除" + label + "第" + (slot + 1) + "项任务"}
                          onClick={() => removeTask(group, slot)}
                        >
                          移除
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="setpieces-add">
                  <select
                    aria-label={label + "待添加任务"}
                    value={pending}
                    onChange={(event) =>
                      setPendingTasks((values) => ({ ...values, [String(group)]: Number(event.target.value) }))
                    }
                  >
                    {options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <button
                    className="button"
                    type="button"
                    onClick={() => addTask(group)}
                    disabled={tasks.length >= MAX_GROUP_TASKS}
                    title={tasks.length >= MAX_GROUP_TASKS ? "每组最多 10 项任务" : undefined}
                  >
                    添加任务
                  </button>
                </div>
              </section>
            );
          })}
        </div>

        {problem !== null && (
          <p className="setpieces-problem" role="status">
            {problem}
          </p>
        )}
        {notice !== null && (
          <p className="setpieces-notice" role="status">
            {notice}
          </p>
        )}
        {error !== null && (
          <p className="setpieces-alert" role="alert">
            {error}
          </p>
        )}

        <div className="setpieces-actions">
          <button
            className="button primary"
            type="button"
            disabled={saveDisabled}
            title={problem ?? undefined}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? "保存中…" : "保存定位球"}
          </button>
          <button className="button" type="button" onClick={() => void pickDocument()} disabled={importMutation.isPending}>
            {importMutation.isPending ? "导入中…" : "导入文档"}
          </button>
          <button className="button" type="button" onClick={() => void exportDocument()} disabled={exporting}>
            {exporting ? "导出中…" : "导出文档"}
          </button>
          <button className="button" type="button" onClick={restoreAll}>
            恢复全部默认
          </button>
          <span className="setpieces-hint">最近保存：{formatTime(detail.updated_at)}</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          aria-label="选择定位球文档"
          className="sr-only"
          onChange={(event) => void onDocumentSelected(event)}
        />
      </Panel>

      <div className="span-5 setpieces-side">
        <Panel title="界外球策略">
          <div className="setpieces-throws">
            {THROW_STYLE_LABELS.map((label, index) => (
              <div className="field" key={label}>
                <label htmlFor={"throw-style-" + index}>{label}</label>
                <select
                  id={"throw-style-" + index}
                  value={draft.throw_styles[index] ?? 0}
                  onChange={(event) => setThrowStyle(index, Number(event.target.value))}
                >
                  {(THROW_STYLE_OPTIONS[index] ?? []).map((option, value) => (
                    <option key={option} value={value}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <p className="setpieces-hint">界外球策略决定球员在三种场区的站位选择，对所有界外球套路生效。</p>
          </div>
        </Panel>

        <Panel title="角色分配顺序">
          <div className="setpieces-roles">
            {ROLE_GROUP_IDS.map((group) => {
              const label = groupLabel(catalog, group);
              const players = draft.role_priorities[String(group)] ?? [];
              const pending = pendingRoles[String(group)] ?? availablePlayers[0]?.index ?? 0;
              return (
                <section className="setpieces-role" key={group} aria-label={label + " 角色分配"}>
                  <header className="setpieces-group-header">
                    <strong>{label}</strong>
                    <span className="setpieces-count">{players.length} 人</span>
                  </header>
                  {players.length > 0 && (
                    <ol className="setpieces-role-list">
                      {players.map((player, index) => (
                        <li className="setpieces-role-row" key={player}>
                          <span className="setpieces-role-name">
                            {detail.players.find((entry) => entry.index === player)?.name ?? "球员 " + (player + 1)}
                          </span>
                          <div className="setpieces-row-actions">
                            <button
                              className="button"
                              type="button"
                              aria-label={label + " 球员 " + (index + 1) + " 上移"}
                              disabled={index === 0}
                              title={index === 0 ? "已在最前" : undefined}
                              onClick={() => moveRole(group, index, -1)}
                            >
                              上移
                            </button>
                            <button
                              className="button"
                              type="button"
                              aria-label={label + " 球员 " + (index + 1) + " 下移"}
                              disabled={index === players.length - 1}
                              title={index === players.length - 1 ? "已在最后" : undefined}
                              onClick={() => moveRole(group, index, 1)}
                            >
                              下移
                            </button>
                            <button
                              className="button"
                              type="button"
                              aria-label={label + " 球员 " + (index + 1) + " 移除"}
                              onClick={() => removeRole(group, index)}
                            >
                              移除
                            </button>
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                  <div className="setpieces-add">
                    <select
                      aria-label={label + "待加入球员"}
                      value={pending}
                      onChange={(event) =>
                        setPendingRoles((values) => ({ ...values, [String(group)]: Number(event.target.value) }))
                      }
                      disabled={availablePlayers.length === 0}
                      title={availablePlayers.length === 0 ? "名单内没有可分配球员" : undefined}
                    >
                      {availablePlayers.map((player) => (
                        <option key={player.index} value={player.index}>
                          {player.name}
                        </option>
                      ))}
                    </select>
                    <button
                      className="button"
                      type="button"
                      onClick={() => addRole(group)}
                      disabled={availablePlayers.length === 0 || players.length >= detail.roster_size}
                      title={
                        availablePlayers.length === 0
                          ? "名单内没有可分配球员"
                          : players.length >= detail.roster_size
                            ? "该角色类别已达到名单人数上限"
                            : undefined
                      }
                    >
                      加入
                    </button>
                  </div>
                </section>
              );
            })}
            <p className="setpieces-hint">同一名球员只会出现在一个角色类别中；未列出的球员按原版自动分配。</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
