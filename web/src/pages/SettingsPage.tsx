import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise, GearSix, Plus } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  checkConcurrency,
  deleteSetting,
  listSettings,
  putSetting,
  type ConcurrencyCheckQuery,
  type Setting,
} from "../lib/api";

const KEY_PATTERN = /^[a-z][a-z0-9_.-]{0,63}$/;
const GIB = 1024 ** 3;
const NOTE_MAX_LENGTH = 200;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

const timeFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : timeFormat.format(date);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function serializedValue(value: unknown): string {
  return JSON.stringify(value) ?? "";
}

function keyProblem(key: string): string | null {
  if (key === "") return "设置键不能为空";
  if (!KEY_PATTERN.test(key)) {
    return "设置键需以小写字母开头，仅含小写字母、数字、点、横线或下划线，最多 64 个字符";
  }
  return null;
}

function parseValue(text: string): { value: unknown; problem: string | null } {
  if (text.trim() === "") return { value: undefined, problem: "设置值不能为空，需填写合法 JSON" };
  try {
    return { value: JSON.parse(text), problem: null };
  } catch {
    return { value: undefined, problem: "设置值必须是合法 JSON" };
  }
}

function noteProblem(note: string): string | null {
  const trimmed = note.trim();
  if (trimmed === "") return null;
  if (trimmed.length > NOTE_MAX_LENGTH) return `设置备注最多 ${NOTE_MAX_LENGTH} 个字符`;
  if (CONTROL_CHARACTERS.test(trimmed)) return "设置备注不能包含换行等控制字符";
  return null;
}

function integerBetween(value: string, minimum: number, maximum: number): boolean {
  if (value.trim() === "") return false;
  const number = Number(value);
  return Number.isInteger(number) && number >= minimum && number <= maximum;
}

function gibToBytes(text: string): number | null {
  if (text.trim() === "") return null;
  const gib = Number(text);
  if (!Number.isFinite(gib) || gib < 0) return null;
  const bytes = Math.round(gib * GIB);
  return Number.isSafeInteger(bytes) ? bytes : null;
}

function formatGib(bytes: number): string {
  const gib = Math.round((bytes / GIB) * 100) / 100;
  return `${gib} GiB`;
}

function codeLabel(code: string): string | null {
  if (code === "insufficient_memory") return "内存不足";
  if (code === "insufficient_disk") return "磁盘不足";
  return null;
}

export function SettingsPage() {
  const { connection, health } = useAppContext();
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [formKey, setFormKey] = useState("");
  const [valueText, setValueText] = useState("");
  const [noteText, setNoteText] = useState("");
  const [touched, setTouched] = useState({ key: false, value: false, note: false });
  const [formAttempted, setFormAttempted] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workers, setWorkers] = useState("4");
  const [cpuCount, setCpuCount] = useState("8");
  const [memoryGib, setMemoryGib] = useState("32");
  const [diskGib, setDiskGib] = useState("100");
  const [allowOversubscription, setAllowOversubscription] = useState(false);

  const settings = useQuery({
    queryKey: ["settings", connection?.url],
    queryFn: () => listSettings(connection!),
    enabled: connection !== null,
  });

  const invalidateSettings = () => {
    void queryClient.invalidateQueries({ queryKey: ["settings"] });
  };

  const save = useMutation({
    mutationFn: (input: { key: string; value: unknown; note: string | null }) =>
      putSetting(connection!, input.key, { value: input.value, note: input.note }),
    onSuccess: (setting) => {
      setActionError(null);
      setNotice(`设置「${setting.key}」已保存`);
      resetForm();
      setConfirmation(null);
      invalidateSettings();
    },
    onError: (error) => {
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const remove = useMutation({
    mutationFn: (key: string) => deleteSetting(connection!, key),
    onSuccess: (_result, key) => {
      setActionError(null);
      setNotice(`已删除设置「${key}」`);
      setConfirmation(null);
      invalidateSettings();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const preflight = useMutation({
    mutationFn: (query: ConcurrencyCheckQuery) => checkConcurrency(connection!, query),
  });

  function resetForm() {
    setFormOpen(false);
    setEditingKey(null);
    setFormKey("");
    setValueText("");
    setNoteText("");
    setTouched({ key: false, value: false, note: false });
    setFormAttempted(false);
  }

  const keyIssue = keyProblem(formKey);
  const parsed = parseValue(valueText);
  const noteIssue = noteProblem(noteText);
  const formValid = keyIssue === null && parsed.problem === null && noteIssue === null;
  const showKeyIssue = (touched.key || formAttempted) && keyIssue !== null;
  const showValueIssue = (touched.value || formAttempted) && parsed.problem !== null;
  const showNoteIssue = (touched.note || formAttempted) && noteIssue !== null;

  const workersValid = integerBetween(workers, 1, 256);
  const cpuValid = integerBetween(cpuCount, 1, Number.MAX_SAFE_INTEGER);
  const memoryBytes = gibToBytes(memoryGib);
  const diskBytes = gibToBytes(diskGib);
  const preflightValid = workersValid && cpuValid && memoryBytes !== null && diskBytes !== null;

  const openCreate = () => {
    resetForm();
    setFormOpen(true);
    setActionError(null);
    setNotice(null);
    setConfirmation(null);
  };

  const openEdit = (setting: Setting) => {
    resetForm();
    setFormOpen(true);
    setEditingKey(setting.key);
    setFormKey(setting.key);
    setValueText(JSON.stringify(setting.value, null, 2) ?? "");
    setNoteText(setting.note ?? "");
    setActionError(null);
    setNotice(null);
    setConfirmation(null);
  };

  const submitForm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connection === null || save.isPending) return;
    if (!formValid) {
      setFormAttempted(true);
      return;
    }
    save.mutate({
      key: formKey,
      value: parsed.value,
      note: noteText.trim() === "" ? null : noteText.trim(),
    });
  };

  const runPreflight = () => {
    if (connection === null || preflight.isPending || !preflightValid) return;
    preflight.mutate({
      workers: Number(workers),
      cpu_count: Number(cpuCount),
      available_memory_bytes: memoryBytes!,
      free_disk_bytes: diskBytes!,
      allow_oversubscription: allowOversubscription,
    });
  };

  const refresh = () => {
    setActionError(null);
    setNotice(null);
    setConfirmation(null);
    void settings.refetch();
  };

  const data = settings.data;
  let settingsBody: ReactNode;
  if (connection === null) {
    settingsBody = (
      <EmptyState
        icon={GearSix}
        title="sidecar 未连接"
        description="连接 sidecar 后可以读取与维护设置。"
      />
    );
  } else if (settings.isPending) {
    settingsBody = (
      <p className="jobs-loading" role="status">
        正在加载设置…
      </p>
    );
  } else if (settings.isError) {
    settingsBody = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(settings.error)}</span>
        <button className="button small" type="button" onClick={() => void settings.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (data === undefined || data.items.length === 0) {
    settingsBody = (
      <EmptyState
        icon={GearSix}
        title="尚无设置"
        description="新建设置后，这里会显示键、JSON 值与更新时间。"
      />
    );
  } else {
    settingsBody = (
      <div className="jobs-table-wrap">
        <table className="jobs-table settings-table">
          <caption className="sr-only">设置列表</caption>
          <thead>
            <tr>
              <th scope="col">设置键</th>
              <th scope="col">值</th>
              <th scope="col">备注</th>
              <th scope="col">更新时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((setting) => {
              const confirming = confirmation === setting.key;
              return (
                <tr key={setting.key}>
                  <td>
                    <span className="data-path">{setting.key}</span>
                  </td>
                  <td>
                    <code className="settings-value" title={serializedValue(setting.value)}>
                      {serializedValue(setting.value)}
                    </code>
                  </td>
                  <td className="settings-note">{setting.note ?? "—"}</td>
                  <td className="jobs-time">{formatTime(setting.updated_at)}</td>
                  <td>
                    <div className="jobs-actions">
                      <button
                        className="button small"
                        type="button"
                        onClick={() => openEdit(setting)}
                      >
                        编辑
                      </button>
                      {confirming ? (
                        <>
                          <button
                            className="button small danger"
                            type="button"
                            disabled={remove.isPending}
                            onClick={() => remove.mutate(setting.key)}
                          >
                            确认删除
                          </button>
                          <button
                            className="button small"
                            type="button"
                            onClick={() => setConfirmation(null)}
                          >
                            放弃
                          </button>
                        </>
                      ) : (
                        <button
                          className="button small danger"
                          type="button"
                          onClick={() => setConfirmation(setting.key)}
                        >
                          删除
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  const result = preflight.isSuccess ? preflight.data : undefined;
  const resultCode = result?.code ?? null;
  const resultCodeLabel = resultCode === null ? null : codeLabel(resultCode);

  return (
    <div className="page-grid">
      <Panel
        title="设置"
        className="span-12"
        action={
          <div className="jobs-toolbar">
            <button
              className="button"
              type="button"
              onClick={refresh}
              disabled={connection === null || settings.isFetching}
            >
              <ArrowClockwise size={16} aria-hidden="true" />
              刷新
            </button>
            <button
              className="button primary"
              type="button"
              onClick={openCreate}
              disabled={connection === null}
            >
              <Plus size={16} aria-hidden="true" />
              新建设置
            </button>
          </div>
        }
      >
        {formOpen ? (
          <form className="settings-form" aria-label="设置编辑器" onSubmit={submitForm}>
            <div className="field">
              <label htmlFor="setting-key">设置键</label>
              <input
                id="setting-key"
                value={formKey}
                disabled={editingKey !== null}
                aria-invalid={showKeyIssue}
                aria-describedby={
                  showKeyIssue ? "setting-key-hint setting-key-error" : "setting-key-hint"
                }
                onChange={(event) => {
                  setFormKey(event.target.value);
                  setTouched((state) => ({ ...state, key: true }));
                }}
              />
              <span id="setting-key-hint" className="field-hint">
                小写字母开头，可含数字、点、横线、下划线，最多 64 个字符
              </span>
              {showKeyIssue ? (
                <span id="setting-key-error" className="field-error">
                  {keyIssue}
                </span>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="setting-note">备注</label>
              <input
                id="setting-note"
                value={noteText}
                aria-invalid={showNoteIssue}
                aria-describedby={showNoteIssue ? "setting-note-error" : undefined}
                onChange={(event) => {
                  setNoteText(event.target.value);
                  setTouched((state) => ({ ...state, note: true }));
                }}
              />
              {showNoteIssue ? (
                <span id="setting-note-error" className="field-error">
                  {noteIssue}
                </span>
              ) : null}
            </div>
            <div className="field settings-form-value">
              <label htmlFor="setting-value">值 JSON</label>
              <textarea
                id="setting-value"
                value={valueText}
                aria-invalid={showValueIssue}
                aria-describedby={showValueIssue ? "setting-value-error" : undefined}
                onChange={(event) => {
                  setValueText(event.target.value);
                  setTouched((state) => ({ ...state, value: true }));
                }}
              />
              {showValueIssue ? (
                <span id="setting-value-error" className="field-error">
                  {parsed.problem}
                </span>
              ) : null}
            </div>
            <div className="settings-form-actions">
              <button
                className="button primary"
                type="submit"
                disabled={connection === null || save.isPending}
              >
                保存
              </button>
              <button className="button" type="button" onClick={resetForm}>
                取消
              </button>
            </div>
          </form>
        ) : null}
        {actionError === null ? null : (
          <div className="inline-alert" role="alert">
            {actionError}
          </div>
        )}
        {notice === null ? null : (
          <p className="jobs-notice" role="status">
            {notice}
          </p>
        )}
        {settingsBody}
      </Panel>

      <Panel title="并发预检" className="span-7">
        <div className="settings-preflight">
          <div className="field">
            <label htmlFor="preflight-workers">并行数</label>
            <input
              id="preflight-workers"
              type="number"
              inputMode="numeric"
              min={1}
              max={256}
              value={workers}
              aria-invalid={!workersValid}
              onChange={(event) => setWorkers(event.target.value)}
            />
            {workersValid ? null : (
              <span className="field-error">并行数需为 1–256 的整数</span>
            )}
          </div>
          <div className="field">
            <label htmlFor="preflight-cpu">CPU 数量</label>
            <input
              id="preflight-cpu"
              type="number"
              inputMode="numeric"
              min={1}
              value={cpuCount}
              aria-invalid={!cpuValid}
              onChange={(event) => setCpuCount(event.target.value)}
            />
            {cpuValid ? null : <span className="field-error">CPU 数量需为正整数</span>}
          </div>
          <div className="field">
            <label htmlFor="preflight-memory">可用内存 GiB</label>
            <input
              id="preflight-memory"
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={memoryGib}
              aria-invalid={memoryBytes === null}
              onChange={(event) => setMemoryGib(event.target.value)}
            />
            {memoryBytes === null ? (
              <span className="field-error">可用内存需为非负 GiB 数值</span>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="preflight-disk">空闲磁盘 GiB</label>
            <input
              id="preflight-disk"
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={diskGib}
              aria-invalid={diskBytes === null}
              onChange={(event) => setDiskGib(event.target.value)}
            />
            {diskBytes === null ? (
              <span className="field-error">空闲磁盘需为非负 GiB 数值</span>
            ) : null}
          </div>
          <label className="field-inline" htmlFor="preflight-oversubscription">
            <input
              id="preflight-oversubscription"
              type="checkbox"
              checked={allowOversubscription}
              onChange={(event) => setAllowOversubscription(event.target.checked)}
            />
            允许资源覆盖
          </label>
          <button
            className="button primary"
            type="button"
            onClick={runPreflight}
            disabled={connection === null || preflight.isPending || !preflightValid}
          >
            运行预检
          </button>
        </div>
        {preflight.isPending ? (
          <p className="jobs-loading" role="status">
            正在预检…
          </p>
        ) : null}
        {preflight.isError ? (
          <div className="inline-alert" role="alert">
            {errorMessage(preflight.error)}
          </div>
        ) : null}
        {result === undefined ? null : (
          <div
            className="concurrency-result"
            role="region"
            aria-label="并发预检结果"
            aria-live="polite"
          >
            <div className="concurrency-headline">
              <span className="badge" data-tone={result.allowed ? "ok" : "error"}>
                {result.allowed ? "允许提交" : "阻止提交"}
              </span>
              <span className="concurrency-recommendation">
                推荐并行数 <strong>{result.recommended_workers}</strong>
              </span>
            </div>
            {resultCode === null ? null : (
              <p className="concurrency-code">
                原因代码 <span className="data-path">{resultCode}</span>
                {resultCodeLabel === null ? null : `（${resultCodeLabel}）`}
              </p>
            )}
            {result.warnings.length === 0 ? null : (
              <ul className="concurrency-warnings">
                {result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
            <p className="concurrency-resources">
              需要内存 {formatGib(result.memory_required_bytes)} · 需要磁盘{" "}
              {formatGib(result.disk_required_bytes)}
            </p>
          </div>
        )}
      </Panel>

      <Panel title="sidecar" className="span-5">
        <dl className="settings-list">
          <dt>API</dt>
          <dd>{connection?.api ?? "未连接"}</dd>
          <dt>地址</dt>
          <dd>{connection?.url ?? "未连接"}</dd>
          <dt>版本</dt>
          <dd>{health?.version ?? "未知"}</dd>
          <dt>数据库</dt>
          <dd>{health?.database ?? "未知"}</dd>
        </dl>
      </Panel>
    </div>
  );
}
