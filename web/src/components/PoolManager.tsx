import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  createPool,
  deletePool,
  importPoolsFmf,
  listPools,
  updatePool,
  type PoolEntry,
} from "../lib/api-pools";
import { downloadBlob } from "../lib/download";
import type { Connection } from "../lib/connection";
import { Panel } from "./Panel";
import "../styles/pools.css";

const NAME_MAX = 80;
const WEIGHT_MIN = 1;
const WEIGHT_MAX = 1000;

type PoolPatch = { name?: string; weight?: number };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function readFileBytes(file: File): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("FMF 文件无法读取"));
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

function PoolRow({
  entry,
  saving,
  onSave,
  onRequestDelete,
}: {
  entry: PoolEntry;
  saving: boolean;
  onSave: (entryId: string, patch: PoolPatch) => void;
  onRequestDelete: (entryId: string, trigger: HTMLButtonElement) => void;
}) {
  const [name, setName] = useState(entry.name);
  const [weightText, setWeightText] = useState(String(entry.weight));
  const trimmedName = name.trim();
  const weight = Number(weightText);
  const weightValid =
    /^\d+$/.test(weightText.trim()) &&
    Number.isInteger(weight) &&
    weight >= WEIGHT_MIN &&
    weight <= WEIGHT_MAX;
  const nameValid = trimmedName.length >= 1 && trimmedName.length <= NAME_MAX;
  const changed =
    trimmedName !== entry.name || (weightValid && weight !== entry.weight);
  const savable = changed && nameValid && weightValid && !saving;

  function handleSave() {
    if (!savable) return;
    const patch: PoolPatch = {};
    if (trimmedName !== entry.name) patch.name = trimmedName;
    if (weight !== entry.weight) patch.weight = weight;
    onSave(entry.id, patch);
  }

  return (
    <div className="pools-row">
      <div className="pools-fields">
        <input
          className="pools-name"
          aria-label="名称"
          value={name}
          maxLength={NAME_MAX}
          disabled={saving}
          onChange={(event) => setName(event.target.value)}
        />
        <input
          className="pools-weight"
          aria-label="权重"
          type="number"
          min={WEIGHT_MIN}
          max={WEIGHT_MAX}
          step={1}
          value={weightText}
          disabled={saving}
          onChange={(event) => setWeightText(event.target.value)}
        />
      </div>
      <div className="pools-row-actions">
        <button
          type="button"
          className="button small"
          disabled={!savable}
          aria-busy={saving || undefined}
          title={
            savable
              ? undefined
              : !nameValid
                ? "名称需为 1–80 个字符"
                : !weightValid
                  ? "权重需为 1–1000 的整数"
                  : !changed
                    ? "没有需要保存的修改"
                    : undefined
          }
          onClick={handleSave}
        >
          保存
        </button>
        <button
          type="button"
          className="button small"
          disabled={saving}
          onClick={(event) => onRequestDelete(entry.id, event.currentTarget)}
        >
          删除
        </button>
      </div>
      {weightValid ? null : <p className="pools-hint">权重需为 1–1000 的整数</p>}
    </div>
  );
}

export function PoolManager({ connection }: { connection: Connection }) {
  const queryClient = useQueryClient();
  const poolQueryKey = ["pools", connection.url];
  const [notice, setNotice] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const bundleInputRef = useRef<HTMLInputElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (confirmId !== null) {
      confirmButtonRef.current?.focus();
    }
  }, [confirmId]);

  function requestDelete(entryId: string, trigger: HTMLButtonElement): void {
    deleteTriggerRef.current = trigger;
    setConfirmId(entryId);
  }

  function closeConfirm(): void {
    setConfirmId(null);
    deleteTriggerRef.current?.focus();
  }

  const poolsQuery = useQuery({
    queryKey: poolQueryKey,
    queryFn: () => listPools(connection),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: poolQueryKey });
  }

  const updateMutation = useMutation({
    mutationFn: ({ entryId, patch }: { entryId: string; patch: PoolPatch }) =>
      updatePool(connection, entryId, patch),
    onSuccess: () => {
      setNotice("已保存");
      refresh();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (entryId: string) => deletePool(connection, entryId),
    onSuccess: () => {
      setConfirmId(null);
      setNotice("已删除");
      refresh();
    },
  });

  const bundleImportMutation = useMutation({
    mutationFn: async (entries: PoolEntry[]) => {
      for (const entry of entries) {
        await createPool(connection, {
          name: entry.name,
          weight: entry.weight,
          tactic: entry.tactic,
          roster: entry.roster,
        });
      }
      return entries.length;
    },
    onSuccess: (count) => {
      setNotice("已导入 " + String(count) + " 套客队战术");
      refresh();
    },
  });

  const importMutation = useMutation({
    mutationFn: (input: { content_base64: string; name?: string }) =>
      importPoolsFmf(connection, input),
    onSuccess: (result) => {
      setNotice("已导入 " + String(result.total) + " 套客队战术");
      refresh();
    },
  });

  async function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) return;
    setNotice(null);
    setFileError(null);
    try {
      const bytes = await readFileBytes(file);
      importMutation.mutate({ content_base64: base64FromBytes(bytes), name: file.name });
    } catch (error) {
      setFileError(errorMessage(error));
    }
  }

  const items = poolsQuery.data?.items ?? [];
  const actionError =
    updateMutation.error ??
    deleteMutation.error ??
    importMutation.error ??
    bundleImportMutation.error;

  function exportBundle() {
    const payload = JSON.stringify(
      {
        profile: "fm27lab-pool-bundle-v1",
        exported_at: new Date().toISOString(),
        entries: items.map((entry) => ({
          name: entry.name,
          weight: entry.weight,
          tactic: entry.tactic,
          roster: entry.roster,
        })),
      },
      null,
      2,
    );
    downloadBlob(new Blob([payload], { type: "application/json" }), "fm27lab-pool.json");
    setNotice("已导出 " + String(items.length) + " 套客队战术");
  }

  async function handleBundleSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) return;
    setNotice(null);
    setFileError(null);
    try {
      const parsed = JSON.parse(await file.text()) as { entries?: unknown };
      if (!Array.isArray(parsed.entries)) {
        throw new Error("客队战术池文件缺少 entries");
      }
      const rows = parsed.entries.filter(
        (entry): entry is PoolEntry =>
          typeof entry === "object" &&
          entry !== null &&
          typeof (entry as { name?: unknown }).name === "string" &&
          typeof (entry as { tactic?: unknown }).tactic === "object",
      );
      if (rows.length === 0) throw new Error("客队战术池文件没有可导入条目");
      bundleImportMutation.mutate(rows);
    } catch (error) {
      setFileError(errorMessage(error));
    }
  }
  const pendingEntryId = updateMutation.isPending
    ? updateMutation.variables?.entryId
    : undefined;

  return (
    <Panel
      title="客队战术池"
      className="pools-panel"
      action={
        <div className="pools-actions">
          <button
            type="button"
            className="button small"
            disabled={bundleImportMutation.isPending || importMutation.isPending}
            aria-busy={bundleImportMutation.isPending || undefined}
            onClick={() => bundleInputRef.current?.click()}
          >
            导入池
          </button>
          <button
            type="button"
            className="button small"
            disabled={items.length === 0}
            onClick={exportBundle}
          >
            导出池
          </button>
          <button
            type="button"
            className="button small"
            disabled={importMutation.isPending}
            aria-busy={importMutation.isPending || undefined}
            onClick={() => fileInputRef.current?.click()}
          >
            导入 FMF
          </button>
        </div>
      }
    >
      <input
        ref={bundleInputRef}
        className="pools-file-input"
        type="file"
        accept="application/json,.json"
        aria-label="客队战术池文件"
        onChange={(event) => void handleBundleSelected(event)}
      />
      <input
        ref={fileInputRef}
        className="pools-file-input"
        type="file"
        accept=".fmf"
        aria-label="FMF 文件"
        onChange={(event) => void handleFileSelected(event)}
      />
      {poolsQuery.isPending ? <p className="pools-status">正在加载客队战术池…</p> : null}
      {poolsQuery.isError ? (
        <div className="pools-error" role="alert">
          <span>{errorMessage(poolsQuery.error)}</span>
          <button
            type="button"
            className="button small"
            onClick={() => void poolsQuery.refetch()}
          >
            重试
          </button>
        </div>
      ) : null}
      {actionError !== null ? (
        <div className="pools-error" role="alert">
          <span>{errorMessage(actionError)}</span>
        </div>
      ) : null}
      {fileError !== null ? (
        <div className="pools-error" role="alert">
          <span>{fileError}</span>
        </div>
      ) : null}
      {notice !== null ? (
        <p className="pools-notice" role="status">
          {notice}
        </p>
      ) : null}
      {!poolsQuery.isPending && !poolsQuery.isError && items.length === 0 ? (
        <p className="pools-empty">还没有客队战术。导入 FMF 文件后，条目会出现在这里。</p>
      ) : null}
      {items.length > 0 ? (
        <ul className="pools-list" aria-label="客队战术池条目">
          {items.map((entry) => (
            <li
              className="pools-item"
              key={entry.id}
            >
              <PoolRow
                entry={entry}
                saving={pendingEntryId === entry.id}
                onSave={(entryId, patch) => updateMutation.mutate({ entryId, patch })}
                onRequestDelete={requestDelete}
              />
              {confirmId === entry.id ? (
                <div
                  className="pools-confirm"
                  role="alertdialog"
                  aria-modal="true"
                  aria-label={"删除 " + entry.name}
                  aria-describedby={"pools-confirm-text-" + entry.id}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      closeConfirm();
                    }
                  }}
                >
                  <p id={"pools-confirm-text-" + entry.id}>删除后不可恢复。</p>
                  <div className="pools-confirm-actions">
                    <button
                      ref={confirmButtonRef}
                      type="button"
                      className="button small"
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate(entry.id)}
                    >
                      确认删除
                    </button>
                    <button
                      type="button"
                      className="button small"
                      onClick={closeConfirm}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
