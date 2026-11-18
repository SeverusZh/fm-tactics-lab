import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { updateDraft, type Draft } from "../lib/api";
import { listPools, type PoolEntry } from "../lib/api-pools";
import type { Connection } from "../lib/connection";
import "../styles/pool-config.css";

const ROUNDS_MIN = 1;
const ROUNDS_MAX = 1000;
const ATTRIBUTE_MIN = 1;
const ATTRIBUTE_MAX = 20;

type Mode = "random" | "rotation";
type Players = "uniform" | "real";

type Props = {
  connection: Connection;
  draftId: string;
  scenario: { [key: string]: unknown };
  onApplied: (draft: Draft) => void;
};

type PoolFormState = {
  entries: string[];
  mode: Mode;
  rounds: string;
  players: Players;
  attribute: string;
};

type PoolTactic = { [key: string]: unknown };

function readPool(scenario: { [key: string]: unknown }) {
  const value = scenario["away_tactic_pool"];
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const pool = value as { [key: string]: unknown };
  const entries = Array.isArray(pool["entries"]) ? pool["entries"] : [];
  const rotation = typeof pool["rotation"] === "object" && pool["rotation"] !== null
    ? (pool["rotation"] as { [key: string]: unknown })
    : {};
  const real = typeof pool["real"] === "object" && pool["real"] !== null
    ? (pool["real"] as { [key: string]: unknown })
    : {};
  const uniform = typeof pool["uniform"] === "object" && pool["uniform"] !== null
    ? (pool["uniform"] as { [key: string]: unknown })
    : {};
  return {
    enabled: pool["enabled"] === true,
    count: entries.length,
    mode: rotation["enabled"] === true ? ("rotation" as const) : ("random" as const),
    rounds: typeof rotation["rounds"] === "number" ? rotation["rounds"] : 1,
    players: real["enabled"] === true ? ("real" as const) : ("uniform" as const),
    attribute: typeof uniform["attribute_value"] === "number" ? uniform["attribute_value"] : 15,
    entries,
  };
}

function entryNames(scenario: { [key: string]: unknown }): string[] {
  const pool = readPool(scenario);
  if (pool === null) return [];
  return pool.entries
    .map((entry) =>
      typeof entry === "object" && entry !== null && typeof (entry as { name?: unknown }).name === "string"
        ? (entry as { name: string }).name
        : "",
    )
    .filter((name) => name !== "");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function PoolConfig({ connection, draftId, scenario, onApplied }: Props) {
  const poolsQuery = useQuery({
    queryKey: ["pools", connection.url],
    queryFn: () => listPools(connection),
  });
  const existing = readPool(scenario);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<PoolFormState>(() => ({
    entries: entryNames(scenario),
    mode: existing?.mode ?? "random",
    rounds: String(existing?.rounds ?? 1),
    players: existing?.players ?? "uniform",
    attribute: String(existing?.attribute ?? 15),
  }));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const roundsNumber = Number(form.rounds);
  const roundsValid =
    /^\d+$/.test(form.rounds.trim()) &&
    Number.isInteger(roundsNumber) &&
    roundsNumber >= ROUNDS_MIN &&
    roundsNumber <= ROUNDS_MAX;
  const attributeNumber = Number(form.attribute);
  const attributeValid =
    /^\d+$/.test(form.attribute.trim()) &&
    Number.isInteger(attributeNumber) &&
    attributeNumber >= ATTRIBUTE_MIN &&
    attributeNumber <= ATTRIBUTE_MAX;
  const library = poolsQuery.data?.items ?? [];
  const libraryNames = new Set(library.map((entry) => entry.name));
  const orphanEntries: PoolEntry[] = (existing?.entries ?? [])
    .filter(
      (entry): entry is { name: string; weight?: number; tactic: PoolTactic; roster?: PoolTactic | null } =>
        typeof entry === "object" && entry !== null && typeof (entry as { name?: unknown }).name === "string",
    )
    .filter((entry) => !libraryNames.has(entry.name))
    .map((entry, index) => ({
      id: "scenario:" + String(index),
      name: entry.name,
      weight: typeof entry.weight === "number" ? entry.weight : 1,
      tactic: entry.tactic,
      roster: entry.roster ?? null,
      created_at: "",
    }));
  const entries = [...library, ...orphanEntries];
  const chosen = entries.filter((entry) => form.entries.includes(entry.name));
  const missingRoster = chosen.some((entry) => entry.roster == null);
  const rotationMatches = chosen.length * (roundsValid ? roundsNumber : 1);

  function openEditor() {
    setForm({
      entries: entryNames(scenario),
      mode: existing?.mode ?? "random",
      rounds: String(existing?.rounds ?? 1),
      players: existing?.players ?? "uniform",
      attribute: String(existing?.attribute ?? 15),
    });
    setError(null);
    setNotice(null);
    setOpen(true);
  }

  const apply = useMutation({
    mutationFn: () => {
      const payload = {
        profile: "away-tactic-pool-v1",
        enabled: chosen.length > 0,
        entries: chosen.map((entry) => ({
          name: entry.name,
          weight: entry.weight,
          tactic: entry.tactic,
          ...(entry.roster == null ? {} : { roster: entry.roster }),
        })),
        uniform: { enabled: true, attribute_value: attributeNumber },
        rotation: { enabled: form.mode === "rotation", rounds: roundsNumber },
        real: { enabled: form.players === "real" },
      };
      return updateDraft(connection, draftId, {
        scenario: { ...scenario, away_tactic_pool: payload },
      });
    },
    onSuccess: (draft) => {
      setNotice("已应用到草案");
      setError(null);
      setOpen(false);
      onApplied(draft);
    },
    onError: (failure) => {
      setNotice(null);
      setError(errorMessage(failure));
    },
  });

  function toggle(entry: PoolEntry, checked: boolean) {
    setForm((current) => ({
      ...current,
      entries: checked
        ? [...current.entries, entry.name]
        : current.entries.filter((name) => name !== entry.name),
    }));
  }

  const canApply =
    !apply.isPending &&
    roundsValid &&
    attributeValid &&
    (form.players !== "real" || !missingRoster);

  return (
    <section className="pool-config" aria-label="客队战术池配置">
      <div className="pool-config-head">
        <span className="pool-config-label">客队战术池配置</span>
        <button className="button small" type="button" onClick={openEditor}>
          配置
        </button>
      </div>
      {notice === null ? null : <p className="pool-config-notice" role="status">{notice}</p>}
      {open ? (
        <div className="pool-config-body">
          {poolsQuery.isPending ? <p className="pool-config-hint">正在加载客队战术…</p> : null}
          {poolsQuery.isError ? (
            <p className="pool-config-error" role="alert">{errorMessage(poolsQuery.error)}</p>
          ) : null}
          {entries.length === 0 && !poolsQuery.isPending ? (
            <p className="pool-config-hint">还没有客队战术，请先在下方导入 FMF 或加入存档战术。</p>
          ) : null}
          <fieldset className="pool-config-entries">
            <legend>战术条目</legend>
            {entries.map((entry) => (
              <label key={entry.id} className="pool-config-entry">
                <input
                  type="checkbox"
                  checked={form.entries.includes(entry.name)}
                  onChange={(event) => toggle(entry, event.target.checked)}
                />
                <span>{entry.name}</span>
                <span className="pool-config-weight">权重 {entry.weight}</span>
                {entry.roster == null ? <span className="pool-config-tag">无名单</span> : null}
              </label>
            ))}
          </fieldset>
          <div className="pool-config-row">
            <fieldset>
              <legend>抽取模式</legend>
              <label>
                <input
                  type="radio"
                  name="pool-mode"
                  checked={form.mode === "random"}
                  onChange={() => setForm((current) => ({ ...current, mode: "random" }))}
                />
                随机抽取
              </label>
              <label>
                <input
                  type="radio"
                  name="pool-mode"
                  checked={form.mode === "rotation"}
                  onChange={() => setForm((current) => ({ ...current, mode: "rotation" }))}
                />
                轮战
              </label>
            </fieldset>
            <div className="field">
              <label htmlFor="pool-rounds">轮战每套轮数</label>
              <input
                id="pool-rounds"
                type="number"
                min={ROUNDS_MIN}
                max={ROUNDS_MAX}
                step={1}
                value={form.rounds}
                disabled={form.mode !== "rotation"}
                onChange={(event) => setForm((current) => ({ ...current, rounds: event.target.value }))}
              />
              {roundsValid ? null : <p className="pool-config-error">轮数需为 1–1000 的整数</p>}
            </div>
            <div className="field">
              <label htmlFor="pool-attribute">统一属性值</label>
              <input
                id="pool-attribute"
                type="number"
                min={ATTRIBUTE_MIN}
                max={ATTRIBUTE_MAX}
                step={1}
                value={form.attribute}
                disabled={form.players === "real"}
                onChange={(event) => setForm((current) => ({ ...current, attribute: event.target.value }))}
              />
              {attributeValid ? null : <p className="pool-config-error">属性值需为 1–20 的整数</p>}
            </div>
          </div>
          <fieldset className="pool-config-players">
            <legend>名单来源</legend>
            <label>
              <input
                type="radio"
                name="pool-players"
                checked={form.players === "uniform"}
                onChange={() => setForm((current) => ({ ...current, players: "uniform" }))}
              />
              统一属性
            </label>
            <label>
              <input
                type="radio"
                name="pool-players"
                checked={form.players === "real"}
                onChange={() => setForm((current) => ({ ...current, players: "real" }))}
              />
              真实名单
            </label>
            {missingRoster ? (
              <p className="pool-config-hint">所选条目中有缺少存档名单的战术，真实名单模式不可用。</p>
            ) : null}
          </fieldset>
          {form.mode === "rotation" && chosen.length > 0 ? (
            <p className="pool-config-hint">
              轮战需要 {chosen.length} 套 × {roundsValid ? roundsNumber : "?"} 轮 ={" "}
              {rotationMatches} 个种子（每方案）。
            </p>
          ) : null}
          {error === null ? null : <p className="pool-config-error" role="alert">{error}</p>}
          <div className="pool-config-actions">
            <button
              className="button"
              type="button"
              disabled={!canApply}
              aria-busy={apply.isPending || undefined}
              onClick={() => apply.mutate()}
            >
              {apply.isPending ? "应用中…" : "应用到草案"}
            </button>
            <button className="button small" type="button" onClick={() => setOpen(false)}>
              取消
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
