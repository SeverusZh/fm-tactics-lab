import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise, GearSix, Plus } from "@phosphor-icons/react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  apiJson,
  checkConcurrency,
  deleteSetting,
  diagnoseEngine,
  getEngineStatus,
  getHostResources,
  importEngineResources,
  listSettings,
  putSetting,
  restartSidecar,
  selectEngine,
  type ConcurrencyCheckQuery,
  type EngineDiagnosis,
  type EngineImportResult,
  type EngineSelect,
  type EngineStatus,
  type Health,
  type Setting,
} from "../lib/api";
import type { Connection } from "../lib/connection";
import { chooseLocalDirectory, isDesktopShell } from "../lib/file-dialog";
import "../styles/settings.css";

const KEY_PATTERN = /^[a-z][a-z0-9_.-]{0,63}$/;
const GIB = 1024 ** 3;
const NOTE_MAX_LENGTH = 200;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
const RESTART_TIMEOUT_MS = 60_000;
const RESTART_POLL_INTERVAL_MS = 1_000;
const SHA_PREFIX_LENGTH = 12;

type EngineAvailability = EngineStatus["engine"];
type RestartPhase = "idle" | "confirming" | "pending" | "recovered" | "timeout";

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
  if (trimmed.length > NOTE_MAX_LENGTH) return "设置备注最多 " + String(NOTE_MAX_LENGTH) + " 个字符";
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
  return String(gib) + " GiB";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return String(bytes) + " B";
  if (bytes < 1024 ** 2) return String(Math.round((bytes / 1024) * 10) / 10) + " KiB";
  return String(Math.round((bytes / 1024 ** 2) * 10) / 10) + " MiB";
}

function codeLabel(code: string): string | null {
  if (code === "insufficient_memory") return "内存不足";
  if (code === "insufficient_disk") return "磁盘不足";
  return null;
}

function gibValue(bytes: number): string {
  return String(Math.round((bytes / GIB) * 100) / 100);
}

function displayValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "未知";
  return value;
}

function shortSha(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  return value.slice(0, SHA_PREFIX_LENGTH);
}

function reasonExplanation(reason: string): string {
  if (/fingerprint|sha-?256|镜像|指纹/i.test(reason)) {
    return "引擎与游戏版本不一致，请重新构建或选择匹配的引擎。";
  }
  if (/missing|not found|找不到|不存在|缺少/i.test(reason)) {
    return "引擎目录不完整，请检查必需文件后重试。";
  }
  return "原生引擎自检未通过，请查看原始原因并重新构建引擎。";
}

function renderAvailability(
  label: string,
  root: string | null,
  availability: EngineAvailability | undefined,
): ReactNode {
  if (availability === undefined) return null;
  return (
    <div className="settings-availability">
      <div className="settings-availability-head">
        <span className="badge" data-tone={availability.available ? "ok" : "error"}>
          {label}
          {availability.available ? "可用" : "不可用"}
        </span>
        <span className="field-hint">{root === null ? "尚未配置" : root}</span>
      </div>
      {availability.missing.length === 0 ? null : (
        <div>
          <p className="field-hint">缺少以下文件：</p>
          <ul className="settings-missing">
            {availability.missing.map((file) => (
              <li key={file}>
                <code>{file}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function AdvancedSettingsPanel() {
  const { connection } = useAppContext();
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

  const settings = useQuery({
    queryKey: ["settings", connection?.url],
    queryFn: () => listSettings(connection as Connection),
    enabled: connection !== null,
  });

  const invalidateSettings = () => {
    void queryClient.invalidateQueries({ queryKey: ["settings"] });
  };

  const save = useMutation({
    mutationFn: (input: { key: string; value: unknown; note: string | null }) =>
      putSetting(connection as Connection, input.key, { value: input.value, note: input.note }),
    onSuccess: (setting) => {
      setActionError(null);
      setNotice("设置「" + setting.key + "」已保存");
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
    mutationFn: (key: string) => deleteSetting(connection as Connection, key),
    onSuccess: (_result, key) => {
      setActionError(null);
      setNotice("已删除设置「" + key + "」");
      setConfirmation(null);
      invalidateSettings();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
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

  const refreshSettings = () => {
    setActionError(null);
    setNotice(null);
    setConfirmation(null);
    void settings.refetch();
  };

  const data = settings.data;
  const items = Array.isArray(data?.items) ? data.items : [];
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
  } else if (items.length === 0) {
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
            {items.map((setting) => {
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

  return (
    <>
      <div className="jobs-toolbar settings-advanced-toolbar">
        <button
          className="button"
          type="button"
          onClick={refreshSettings}
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
    </>
  );
}

export function SettingsPage() {
  const { connection, health, refresh } = useAppContext();
  const queryClient = useQueryClient();
  const desktop = isDesktopShell();

  const [engineRoot, setEngineRoot] = useState("");
  const [gameRoot, setGameRoot] = useState("");
  const [configError, setConfigError] = useState<string | null>(null);
  const [configNotice, setConfigNotice] = useState<string | null>(null);
  const [needsRestart, setNeedsRestart] = useState(false);
  const [diagnosis, setDiagnosis] = useState<EngineDiagnosis | null>(null);
  const [diagnosisError, setDiagnosisError] = useState<string | null>(null);
  const [restartPhase, setRestartPhase] = useState<RestartPhase>("idle");
  const [restartError, setRestartError] = useState<string | null>(null);
  const [workers, setWorkers] = useState("4");
  const [cpuCount, setCpuCount] = useState("8");
  const [memoryGib, setMemoryGib] = useState("32");
  const [diskGib, setDiskGib] = useState("100");
  const [allowOversubscription, setAllowOversubscription] = useState(false);
  const [importSource, setImportSource] = useState("");
  const [importResult, setImportResult] = useState<EngineImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const editedEngine = useRef(false);
  const editedGame = useRef(false);
  const editedCpu = useRef(false);
  const editedMemory = useRef(false);
  const editedDisk = useRef(false);
  const restartOrigin = useRef<Connection | null>(null);
  const restartStartedAt = useRef<number | null>(null);
  const restartSawFailure = useRef(false);
  const restartTrigger = useRef<HTMLButtonElement | null>(null);
  const confirmWasOpen = useRef(false);
  const refreshRef = useRef(refresh);
  const preflightKeyRef = useRef("");

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  const engineQuery = useQuery({
    queryKey: ["engine-status", connection?.url],
    queryFn: () => getEngineStatus(connection as Connection),
    enabled: connection !== null,
  });

  const resourcesQuery = useQuery({
    queryKey: ["host-resources", connection?.url],
    queryFn: () => getHostResources(connection as Connection),
    enabled: connection !== null,
  });

  useEffect(() => {
    const status = engineQuery.data;
    if (status === undefined) return;
    if (!editedEngine.current) setEngineRoot(status.engine_root ?? "");
    if (!editedGame.current) setGameRoot(status.game_root ?? "");
  }, [engineQuery.data]);

  useEffect(() => {
    const data = resourcesQuery.data;
    if (data === undefined) return;
    if (typeof data.cpu_count === "number" && !editedCpu.current) {
      setCpuCount(String(data.cpu_count));
    }
    if (typeof data.available_memory_bytes === "number" && !editedMemory.current) {
      setMemoryGib(gibValue(data.available_memory_bytes));
    }
    if (typeof data.free_disk_bytes === "number" && !editedDisk.current) {
      setDiskGib(gibValue(data.free_disk_bytes));
    }
  }, [resourcesQuery.data]);

  const saveEngine = useMutation({
    mutationFn: (input: EngineSelect) => selectEngine(connection as Connection, input),
    onSuccess: (status) => {
      queryClient.setQueryData(["engine-status", connection?.url], status);
      editedEngine.current = false;
      editedGame.current = false;
      setConfigError(null);
      setConfigNotice("已保存，重启 sidecar 后生效");
      setNeedsRestart(true);
      setDiagnosis(null);
      setDiagnosisError(null);
      setRestartPhase("idle");
      void queryClient.invalidateQueries({ queryKey: ["engine-status"] });
    },
    onError: (error) => {
      setConfigNotice(null);
      setConfigError(errorMessage(error));
    },
  });

  const importEngine = useMutation({
    mutationFn: (sourcePath: string) => importEngineResources(connection as Connection, sourcePath),
    onSuccess: (result) => {
      setImportError(null);
      setImportResult(result);
      setEngineRoot(result.target_root);
      editedEngine.current = true;
      setConfigError(null);
      void queryClient.invalidateQueries({ queryKey: ["engine-status"] });
    },
    onError: (error) => {
      setImportResult(null);
      setImportError(errorMessage(error));
    },
  });

  const diagnose = useMutation({
    mutationFn: () => diagnoseEngine(connection as Connection),
    onSuccess: (result) => {
      setDiagnosisError(null);
      setDiagnosis(result);
    },
    onError: (error) => {
      setDiagnosis(null);
      setDiagnosisError(errorMessage(error));
    },
  });

  const restart = useMutation({
    mutationFn: () => restartSidecar(connection as Connection),
    onSuccess: () => {
      restartOrigin.current = connection;
      restartStartedAt.current = Date.now();
      restartSawFailure.current = false;
      setRestartError(null);
      setRestartPhase("pending");
    },
    onError: (error) => {
      setRestartError(errorMessage(error));
      setRestartPhase("idle");
    },
  });

  const preflight = useMutation({
    mutationFn: (query: ConcurrencyCheckQuery) => checkConcurrency(connection as Connection, query),
  });

  useEffect(() => {
    if (restartPhase !== "pending") return;
    if (restartStartedAt.current === null) restartStartedAt.current = Date.now();
    const origin = restartOrigin.current;
    const connectionChanged = origin !== null && connection !== origin;
    if (connectionChanged) restartSawFailure.current = true;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      if (connection === null) {
        restartSawFailure.current = true;
      } else {
        try {
          const probe = await apiJson<Health>(connection, "/api/health");
          if (probe.status === "ok" && restartSawFailure.current) {
            if (cancelled) return;
            restartStartedAt.current = null;
            setRestartPhase("recovered");
            setNeedsRestart(false);
            setConfigNotice("引擎配置已生效");
            void queryClient.invalidateQueries({ queryKey: ["engine-status"] });
            refreshRef.current();
            return;
          }
        } catch {
          restartSawFailure.current = true;
        }
      }
      if (cancelled) return;
      const startedAt = restartStartedAt.current ?? Date.now();
      if (Date.now() - startedAt >= RESTART_TIMEOUT_MS) {
        restartStartedAt.current = null;
        setRestartPhase("timeout");
        return;
      }
      timer = window.setTimeout(() => {
        void poll();
      }, RESTART_POLL_INTERVAL_MS);
    };
    const initialDelay = connectionChanged ? 0 : RESTART_POLL_INTERVAL_MS;
    timer = window.setTimeout(() => {
      void poll();
    }, initialDelay);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [restartPhase, connection, queryClient]);

  useEffect(() => {
    if (restartPhase === "confirming") {
      confirmWasOpen.current = true;
      return;
    }
    if (!confirmWasOpen.current) return;
    confirmWasOpen.current = false;
    if (restartPhase === "idle") restartTrigger.current?.focus();
  }, [restartPhase]);

  const closeRestartConfirm = () => {
    setRestartPhase("idle");
  };

  const handleConfirmKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    closeRestartConfirm();
  };

  const retryRestart = () => {
    if (connection === null || restart.isPending) return;
    setRestartError(null);
    restart.mutate();
  };

  const engineRootValue = engineRoot.trim();
  const gameRootValue = gameRoot.trim();
  const engineStatusData = engineQuery.data;
  const engineAvailability = engineStatusData?.engine;
  const gameAvailability = engineStatusData?.game;

  let saveDisabledReason: string | null = null;
  if (connection === null) {
    saveDisabledReason = "sidecar 未连接，无法保存";
  } else if (engineRootValue === "" && gameRootValue === "") {
    saveDisabledReason = "请至少填写引擎目录或游戏目录";
  }
  const saveDisabled = saveDisabledReason !== null || saveEngine.isPending;

  let diagnoseDisabledReason: string | null = null;
  if (connection === null) {
    diagnoseDisabledReason = "sidecar 未连接，无法诊断";
  } else if (needsRestart) {
    diagnoseDisabledReason = "已保存新配置，请先重启 sidecar 使新配置生效";
  } else if (engineQuery.isError) {
    diagnoseDisabledReason = "无法读取引擎配置，请先刷新状态";
  } else if (engineStatusData === undefined) {
    diagnoseDisabledReason = "正在读取引擎配置…";
  } else if (engineAvailability === undefined || !engineAvailability.available) {
    diagnoseDisabledReason = "引擎目录缺少必需文件，无法诊断";
  } else if (gameAvailability === undefined || !gameAvailability.available) {
    diagnoseDisabledReason = "游戏目录缺少必需文件，无法诊断";
  }
  const diagnoseDisabled = diagnoseDisabledReason !== null || diagnose.isPending;

  const restartDisabledReason = connection === null ? "sidecar 未连接，无法重启" : null;

  const importSourceValue = importSource.trim();
  let importDisabledReason: string | null = null;
  if (connection === null) {
    importDisabledReason = "连接 sidecar 后才能导入";
  } else if (importSourceValue === "") {
    importDisabledReason = "请填写来源目录";
  } else if (importEngine.isPending) {
    importDisabledReason = "导入进行中…";
  }
  const importDisabled = importDisabledReason !== null;

  const workersValid = integerBetween(workers, 1, 256);
  const cpuValid = integerBetween(cpuCount, 1, Number.MAX_SAFE_INTEGER);
  const memoryBytes = gibToBytes(memoryGib);
  const diskBytes = gibToBytes(diskGib);
  const preflightValid = workersValid && cpuValid && memoryBytes !== null && diskBytes !== null;
  const preflightKey = [
    workers,
    cpuCount,
    memoryGib,
    diskGib,
    allowOversubscription ? "1" : "0",
  ].join("|");
  const preflightFresh = preflight.isSuccess && preflightKeyRef.current === preflightKey;
  useEffect(() => {
    if (!preflight.isSuccess) return;
    if (preflightKeyRef.current === preflightKey) return;
    preflight.reset();
  }, [preflight, preflightKey]);
  const resourcesUsable =
    resourcesQuery.data !== undefined && typeof resourcesQuery.data.cpu_count === "number";

  const browseDirectory = (
    title: string,
    current: string,
    apply: (value: string) => void,
    markEdited: () => void,
  ) => {
    void chooseLocalDirectory({
      title,
      defaultPath: current.trim() === "" ? undefined : current.trim(),
    })
      .then((selected) => {
        if (selected === null) return;
        apply(selected);
        markEdited();
        setConfigError(null);
        setConfigNotice(null);
      })
      .catch((error: unknown) => {
        setConfigError(errorMessage(error));
      });
  };

  const submitEngineConfig = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connection === null || saveEngine.isPending || saveDisabled) return;
    const input: EngineSelect = {};
    if (engineRootValue !== "") input.engine_root = engineRootValue;
    if (gameRootValue !== "") input.game_root = gameRootValue;
    saveEngine.mutate(input);
  };

  const browseImportSource = () => {
    void chooseLocalDirectory({
      title: "选择旧版数据或引擎目录",
      defaultPath: importSourceValue === "" ? undefined : importSourceValue,
    })
      .then((selected) => {
        if (selected === null) return;
        setImportSource(selected);
        setImportError(null);
      })
      .catch((error: unknown) => {
        setImportError(errorMessage(error));
      });
  };

  const submitImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (importDisabled) return;
    importEngine.mutate(importSourceValue);
  };

  const runPreflight = () => {
    if (connection === null || preflight.isPending || !preflightValid) return;
    preflightKeyRef.current = preflightKey;
    preflight.mutate({
      workers: Number(workers),
      cpu_count: Number(cpuCount),
      available_memory_bytes: memoryBytes as number,
      free_disk_bytes: diskBytes as number,
      allow_oversubscription: allowOversubscription,
    });
  };

  let engineBody: ReactNode;
  if (connection === null) {
    engineBody = (
      <EmptyState
        icon={GearSix}
        title="sidecar 未连接"
        description="连接 sidecar 后才能读取与保存引擎配置。"
      />
    );
  } else if (engineQuery.isPending) {
    engineBody = (
      <p className="jobs-loading" role="status">
        正在读取引擎配置…
      </p>
    );
  } else if (engineQuery.isError) {
    engineBody = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(engineQuery.error)}</span>
        <button className="button small" type="button" onClick={() => void engineQuery.refetch()}>
          重试
        </button>
      </div>
    );
  } else {
    engineBody = (
      <div className="settings-engine" data-testid="settings-engine">
        <form
          className="settings-engine-form"
          aria-label="引擎与游戏目录配置"
          onSubmit={submitEngineConfig}
        >
          <div className="settings-engine-grid">
            <div className="field">
              <label htmlFor="engine-root">引擎目录</label>
              <div className="settings-path-row">
                <input
                  id="engine-root"
                  value={engineRoot}
                  placeholder="例如 /opt/FM27"
                  aria-describedby="engine-root-hint"
                  onChange={(event) => {
                    setEngineRoot(event.target.value);
                    editedEngine.current = true;
                    setConfigError(null);
                  }}
                />
                {desktop ? (
                  <button
                    id="engine-browse"
                    className="button"
                    type="button"
                    onClick={() =>
                      browseDirectory(
                        "选择引擎目录",
                        engineRoot,
                        setEngineRoot,
                        () => {
                          editedEngine.current = true;
                        },
                      )
                    }
                  >
                    浏览…
                  </button>
                ) : null}
              </div>
              <span id="engine-root-hint" className="field-hint">
                引擎根目录，需包含 fm27_native 与 fm27_research
              </span>
              {renderAvailability(
                "引擎目录",
                engineStatusData?.engine_root ?? null,
                engineAvailability,
              )}
            </div>
            <div className="field">
              <label htmlFor="game-root">游戏目录</label>
              <div className="settings-path-row">
                <input
                  id="game-root"
                  value={gameRoot}
                  placeholder="例如 /opt/FM27/game"
                  aria-describedby="game-root-hint"
                  onChange={(event) => {
                    setGameRoot(event.target.value);
                    editedGame.current = true;
                    setConfigError(null);
                  }}
                />
                {desktop ? (
                  <button
                    id="game-browse"
                    className="button"
                    type="button"
                    onClick={() =>
                      browseDirectory(
                        "选择游戏目录",
                        gameRoot,
                        setGameRoot,
                        () => {
                          editedGame.current = true;
                        },
                      )
                    }
                  >
                    浏览…
                  </button>
                ) : null}
              </div>
              <span id="game-root-hint" className="field-hint">
                游戏根目录，需包含 fm_Data/Plugins/x86_64/game_plugin.dll
              </span>
              {renderAvailability("游戏目录", engineStatusData?.game_root ?? null, gameAvailability)}
            </div>
          </div>
          {configError === null ? null : (
            <div className="inline-alert" role="alert">
              {configError}
            </div>
          )}
          {configNotice === null ? null : (
            <p className="jobs-notice" role="status">
              {configNotice}
            </p>
          )}
          <div className="settings-actions">
            <button
              id="engine-save"
              className="button primary"
              type="submit"
              disabled={saveDisabled}
              aria-describedby={saveDisabledReason === null ? undefined : "engine-save-hint"}
            >
              保存配置
            </button>
            {saveDisabledReason === null ? null : (
              <span id="engine-save-hint" className="settings-disabled-hint">
                {saveDisabledReason}
              </span>
            )}
            <button
              className="button"
              type="button"
              onClick={() => void engineQuery.refetch()}
              disabled={engineQuery.isFetching}
            >
              <ArrowClockwise size={16} aria-hidden="true" />
              刷新状态
            </button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="page-grid">
      <Panel title="引擎与游戏目录" className="span-12">
        {engineBody}
      </Panel>

      <Panel title="导入引擎资源" className="span-12">
        <div className="settings-import" data-testid="settings-engine-import">
          <form className="settings-import-form" aria-label="导入引擎资源" onSubmit={submitImport}>
            <div className="field">
              <label htmlFor="engine-import-source">来源目录</label>
              <div className="settings-path-row">
                <input
                  id="engine-import-source"
                  value={importSource}
                  placeholder="例如 %LOCALAPPDATA%\FM27TacticsDesktop"
                  aria-describedby="engine-import-source-hint"
                  onChange={(event) => {
                    setImportSource(event.target.value);
                    setImportError(null);
                  }}
                />
                {desktop ? (
                  <button
                    id="engine-import-browse"
                    className="button"
                    type="button"
                    aria-label="浏览来源目录"
                    onClick={browseImportSource}
                  >
                    浏览…
                  </button>
                ) : null}
              </div>
              <span id="engine-import-source-hint" className="field-hint">
                可从旧版应用数据目录或包含 fm27_native 的引擎目录导入，会复制宿主、编辑器快照、fixtures、定位球枚举与场景目录到本地数据目录。
              </span>
            </div>
            <div className="settings-actions">
              <button
                id="engine-import-submit"
                className="button primary"
                type="submit"
                disabled={importDisabled}
                aria-describedby={importDisabledReason === null ? undefined : "engine-import-hint"}
              >
                {importEngine.isPending ? "导入中…" : "导入"}
              </button>
              {importDisabledReason === null ? null : (
                <span id="engine-import-hint" className="settings-disabled-hint">
                  {importDisabledReason}
                </span>
              )}
            </div>
            {importError === null ? null : (
              <>
                <div className="inline-alert" role="alert">
                  {importError}
                </div>
                <p className="field-hint">
                  请检查所选目录，确认包含 fm27_native 引擎工作区或旧版应用数据目录。
                </p>
              </>
            )}
            {importResult === null ? null : (
              <div
                className="settings-import-result"
                role="region"
                aria-label="导入结果"
                aria-live="polite"
              >
                <div className="settings-diagnosis-badges">
                  <span className="badge" data-tone={importResult.available ? "ok" : "warn"}>
                    {importResult.available ? "导入成功" : "导入完成但引擎不可用"}
                  </span>
                  {importResult.matched ? null : (
                    <span className="badge" data-tone="warn">
                      版本不匹配
                    </span>
                  )}
                </div>
                <dl className="settings-import-meta">
                  <dt>目标目录</dt>
                  <dd>{importResult.target_root}</dd>
                  <dt>复制文件</dt>
                  <dd>{importResult.copied.length} 个文件</dd>
                  <dt>总大小</dt>
                  <dd>
                    {formatBytes(importResult.total_bytes)}（{importResult.total_bytes} 字节）
                  </dd>
                  <dt>场景目录来源</dt>
                  <dd>{importResult.catalog_path ?? "未发现"}</dd>
                </dl>
                {importResult.missing.length === 0 ? null : (
                  <div>
                    <p className="field-hint">缺少以下文件：</p>
                    <ul className="settings-missing">
                      {importResult.missing.map((file) => (
                        <li key={file}>
                          <code>{file}</code>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {importResult.matched ? null : (
                  <p className="settings-warning">
                    引擎与当前游戏版本可能不匹配，诊断会给出结论。
                  </p>
                )}
                {importResult.available ? (
                  <p className="jobs-notice" role="status">
                    导入完成，目标目录已填入“引擎目录”，请点击“保存配置”，再重启 sidecar 后生效。
                  </p>
                ) : null}
              </div>
            )}
          </form>
        </div>
      </Panel>

      <Panel title="引擎兼容性诊断" className="span-7">
        <div className="settings-diagnose" data-testid="settings-diagnose">
          <div className="settings-actions">
            <button
              id="engine-diagnose"
              className="button primary"
              type="button"
              onClick={() => diagnose.mutate()}
              disabled={diagnoseDisabled}
              aria-describedby={
                diagnoseDisabledReason === null ? undefined : "engine-diagnose-hint"
              }
            >
              {diagnose.isPending ? "正在诊断…" : "诊断引擎兼容性"}
            </button>
            {diagnoseDisabledReason === null ? null : (
              <span id="engine-diagnose-hint" className="settings-disabled-hint">
                {diagnoseDisabledReason}
              </span>
            )}
          </div>
          {diagnosisError === null ? null : (
            <div className="inline-alert" role="alert">
              {diagnosisError}
            </div>
          )}
          {diagnosis === null ? (
            <p className="field-hint">诊断会启动一次原生宿主自检，通常需要数秒。</p>
          ) : (
            <div className="settings-diagnosis" role="status" aria-live="polite">
              <div className="settings-diagnosis-badges">
                <span className="badge" data-tone={diagnosis.compatible ? "ok" : "error"}>
                  {diagnosis.compatible ? "兼容" : "不兼容"}
                </span>
                <span className="badge" data-tone={diagnosis.trial_allowed ? "warn" : "error"}>
                  {diagnosis.trial_allowed ? "允许试用" : "不允许试用"}
                </span>
              </div>
              {diagnosis.reason === null ? null : (
                <>
                  <p className="settings-diagnosis-reason">{reasonExplanation(diagnosis.reason)}</p>
                  <p className="settings-diagnosis-raw">
                    原始原因 <code className="data-path">{diagnosis.reason}</code>
                  </p>
                </>
              )}
              <dl className="settings-diagnosis-meta">
                <dt>适配器版本</dt>
                <dd>{displayValue(diagnosis.adapter_version)}</dd>
                <dt>镜像指纹</dt>
                <dd>{shortSha(diagnosis.image_sha256) ?? "未知"}</dd>
              </dl>
            </div>
          )}
        </div>
      </Panel>

      <Panel title="重启 sidecar" className="span-5">
        <div className="settings-restart" data-testid="settings-restart">
          {restartPhase === "confirming" ? (
            <div
              className="settings-confirm"
              role="dialog"
              aria-modal="true"
              aria-labelledby="restart-confirm-title"
              aria-describedby="restart-mode-hint"
              onKeyDown={handleConfirmKeyDown}
            >
              <p id="restart-confirm-title">重启会中断正在运行的任务，确定重启 sidecar？</p>
              <div className="settings-actions">
                <button
                  className="button danger"
                  type="button"
                  autoFocus
                  onClick={() => restart.mutate()}
                  disabled={restart.isPending}
                >
                  确认重启
                </button>
                <button className="button" type="button" onClick={closeRestartConfirm}>
                  取消
                </button>
              </div>
            </div>
          ) : restartPhase === "pending" ? (
            <p className="jobs-notice" role="status">
              正在重启 sidecar… 等待重新连接
            </p>
          ) : restartPhase === "recovered" ? (
            <>
              <p className="jobs-notice" role="status">
                sidecar 已重新连接，新配置已生效。
              </p>
              <div className="settings-actions">
                <button className="button small" type="button" onClick={closeRestartConfirm}>
                  完成
                </button>
              </div>
            </>
          ) : restartPhase === "timeout" ? (
            <>
              <div className="inline-alert" role="alert">
                已等待 {String(RESTART_TIMEOUT_MS / 1000)} 秒未自动恢复，请手动重启应用
              </div>
              <div className="settings-actions">
                <button
                  className="button small"
                  type="button"
                  onClick={retryRestart}
                  disabled={connection === null || restart.isPending}
                >
                  重试重启
                </button>
                <button className="button small" type="button" onClick={closeRestartConfirm}>
                  取消等待
                </button>
                {connection === null ? (
                  <span className="settings-disabled-hint">sidecar 未连接，无法再次重启</span>
                ) : null}
              </div>
            </>
          ) : (
            <>
              {needsRestart ? (
                <p className="jobs-notice">配置已保存，需要重启 sidecar 才能生效。</p>
              ) : null}
              <div className="settings-actions">
                <button
                  ref={restartTrigger}
                  id="engine-restart"
                  className="button"
                  type="button"
                  aria-describedby={
                    restartDisabledReason === null ? undefined : "engine-restart-hint"
                  }
                  onClick={() => {
                    setRestartError(null);
                    setRestartPhase("confirming");
                  }}
                  disabled={restartDisabledReason !== null}
                >
                  重启 sidecar
                </button>
                {restartDisabledReason === null ? null : (
                  <span id="engine-restart-hint" className="settings-disabled-hint">
                    {restartDisabledReason}
                  </span>
                )}
              </div>
            </>
          )}
          {restartError === null ? null : (
            <div className="inline-alert" role="alert">
              {restartError}
            </div>
          )}
          <p id="restart-mode-hint" className={desktop ? "field-hint" : "settings-warning"}>
            {desktop
              ? "桌面模式：重启后应用会自动拉起 sidecar，连接恢复后本页自动刷新。"
              : "浏览器模式：重启会断开连接且不会自动拉起，需要手动重启后端进程。"}
          </p>
        </div>
      </Panel>

      <Panel title="运行环境与并发" className="span-7">
        {resourcesQuery.isError ? (
          <p className="field-hint">无法读取本机资源，请手动填写。</p>
        ) : resourcesUsable ? (
          <p className="field-hint">已根据本机资源预填 CPU、内存与磁盘，可手动修改。</p>
        ) : null}
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
            {workersValid ? null : <span className="field-error">并行数需为 1–256 的整数</span>}
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
              onChange={(event) => {
                setCpuCount(event.target.value);
                editedCpu.current = true;
              }}
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
              onChange={(event) => {
                setMemoryGib(event.target.value);
                editedMemory.current = true;
              }}
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
              onChange={(event) => {
                setDiskGib(event.target.value);
                editedDisk.current = true;
              }}
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
        {preflightFresh && preflight.data !== undefined ? (
          <div
            className="concurrency-result"
            role="region"
            aria-label="并发预检结果"
            aria-live="polite"
          >
            <div className="concurrency-headline">
              <span className="badge" data-tone={preflight.data.allowed ? "ok" : "error"}>
                {preflight.data.allowed ? "允许提交" : "阻止提交"}
              </span>
              <span className="concurrency-recommendation">
                推荐并行数 <strong>{preflight.data.recommended_workers}</strong>
              </span>
            </div>
            {preflight.data.code === null ? null : (
              <p className="concurrency-code">
                原因代码 <span className="data-path">{preflight.data.code}</span>
                {codeLabel(preflight.data.code) === null
                  ? null
                  : "（" + (codeLabel(preflight.data.code) as string) + "）"}
              </p>
            )}
            {preflight.data.warnings.length === 0 ? null : (
              <ul className="concurrency-warnings">
                {preflight.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
            <p className="concurrency-resources">
              需要内存 {formatGib(preflight.data.memory_required_bytes)} · 需要磁盘{" "}
              {formatGib(preflight.data.disk_required_bytes)}
            </p>
          </div>
        ) : null}
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

      <details className="panel span-12 settings-advanced" data-testid="settings-advanced">
        <summary>高级设置（键值）</summary>
        <div className="panel-body">
          <AdvancedSettingsPanel />
        </div>
      </details>
    </div>
  );
}
