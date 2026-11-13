import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowClockwise, Plus } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  createSave,
  deleteSave,
  importSave,
  listSaves,
  type Save,
  type SaveCreate,
  type SaveImport,
  type SaveStatus,
} from "../lib/api";

const PAGE_SIZE = 20;
const SHA256_PATTERN = /^[0-9a-fA-F]{64}$/;
const MAX_SOURCE_PATH = 4096;
const MAX_STAGE = 200;

const STATUS_LABELS: Record<SaveStatus, string> = {
  pending: "待读取",
  reading: "读取中",
  ready: "已就绪",
  error: "失败",
  cancelled: "已取消",
};

const STATUS_TONES: Record<SaveStatus, "ok" | "warn" | "error" | undefined> = {
  pending: "warn",
  reading: undefined,
  ready: "ok",
  error: "error",
  cancelled: undefined,
};

const dateFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

type MetadataParse = {
  value?: Record<string, unknown>;
  error: string | null;
};

function parseMetadata(text: string): MetadataParse {
  const trimmed = text.trim();
  if (trimmed === "") return { error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { error: "元数据必须为合法 JSON 对象" };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: "元数据必须为合法 JSON 对象" };
  }
  return { value: parsed as Record<string, unknown>, error: null };
}

type ImportParse = {
  payload?: SaveImport;
  error: string | null;
};

function isRecord(value: unknown): value is Record<string, Record<string, unknown>> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseImport(text: string): ImportParse {
  const trimmed = text.trim();
  if (trimmed === "") return { error: "导入内容不能为空" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { error: "导入内容必须是合法 JSON" };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: "导入内容必须是 JSON 对象" };
  }
  const record = parsed as Record<string, unknown>;
  if (!isRecord(record.leagues) || !isRecord(record.clubs)) {
    return { error: "导入内容需要 leagues 与 clubs 对象" };
  }
  return { payload: { leagues: record.leagues, clubs: record.clubs }, error: null };
}

function SaveStatusFilter({
  value,
  onChange,
}: {
  value: SaveStatus | "";
  onChange: (value: SaveStatus | "") => void;
}) {
  return (
    <label className="field jobs-filter">
      状态筛选
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as SaveStatus | "")}
      >
        <option value="">全部</option>
        {(Object.keys(STATUS_LABELS) as SaveStatus[]).map((status) => (
          <option key={status} value={status}>
            {STATUS_LABELS[status]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function LibraryPage() {
  const { connection } = useAppContext();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SaveStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [importTargetId, setImportTargetId] = useState<string | null>(null);
  const [sourcePath, setSourcePath] = useState("");
  const [sourceSha, setSourceSha] = useState("");
  const [stage, setStage] = useState("");
  const [metadataText, setMetadataText] = useState("");
  const [touched, setTouched] = useState({
    path: false,
    sha: false,
    stage: false,
    metadata: false,
  });
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const saves = useQuery({
    queryKey: ["saves", connection?.url, status, offset],
    queryFn: () =>
      listSaves(connection!, {
        status: status === "" ? undefined : status,
        limit: PAGE_SIZE,
        offset,
      }),
    enabled: connection !== null,
  });

  const invalidateSaves = () => {
    void queryClient.invalidateQueries({ queryKey: ["saves"] });
  };

  const pathTrimmed = sourcePath.trim();
  const shaTrimmed = sourceSha.trim();
  const stageTrimmed = stage.trim();
  const metadata = parseMetadata(metadataText);
  const pathError =
    pathTrimmed === ""
      ? "存档路径不能为空"
      : pathTrimmed.length > MAX_SOURCE_PATH
        ? `存档路径最多 ${MAX_SOURCE_PATH} 个字符`
        : null;
  const shaError = SHA256_PATTERN.test(shaTrimmed) ? null : "SHA-256 需为 64 位十六进制字符串";
  const stageError =
    stageTrimmed.length > MAX_STAGE ? `阶段最多 ${MAX_STAGE} 个字符` : null;
  const formValid = pathError === null && shaError === null && stageError === null && metadata.error === null;

  const resetForm = () => {
    setSourcePath("");
    setSourceSha("");
    setStage("");
    setMetadataText("");
    setTouched({ path: false, sha: false, stage: false, metadata: false });
  };

  const create = useMutation({
    mutationFn: (input: SaveCreate) => createSave(connection!, input),
    onSuccess: () => {
      setCreateOpen(false);
      setActionError(null);
      setNotice("存档已创建");
      resetForm();
      invalidateSaves();
    },
    onError: (error) => {
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const importMutation = useMutation({
    mutationFn: (input: { saveId: string; payload: SaveImport }) =>
      importSave(connection!, input.saveId, input.payload),
    onSuccess: () => {
      setImportTargetId(null);
      setImportText("");
      setImportError(null);
      setActionError(null);
      setNotice("存档已导入");
      invalidateSaves();
    },
    onError: (error) => {
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const remove = useMutation({
    mutationFn: (save: Save) => deleteSave(connection!, save.id),
    onSuccess: () => {
      setConfirmation(null);
      setActionError(null);
      setNotice("已删除存档");
      invalidateSaves();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const changeStatus = (next: SaveStatus | "") => {
    setStatus(next);
    setOffset(0);
    setConfirmation(null);
    setActionError(null);
    setNotice(null);
  };

  const openCreate = () => {
    setCreateOpen((open) => !open);
    setImportTargetId(null);
    setImportError(null);
    setActionError(null);
    setNotice(null);
  };

  const openImport = (saveId: string) => {
    setImportTargetId(saveId);
    setImportText("");
    setImportError(null);
    setCreateOpen(false);
    setConfirmation(null);
    setActionError(null);
    setNotice(null);
  };

  const refresh = () => {
    setActionError(null);
    setNotice(null);
    void saves.refetch();
  };

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connection === null || !formValid || create.isPending) return;
    setActionError(null);
    setNotice(null);
    create.mutate({
      source_path: pathTrimmed,
      source_sha256: shaTrimmed.toLowerCase(),
      ...(stageTrimmed === "" ? {} : { stage: stageTrimmed }),
      ...(metadata.value === undefined ? {} : { metadata: metadata.value }),
    });
  };

  const submitImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connection === null || importTargetId === null || importMutation.isPending) return;
    const parsed = parseImport(importText);
    if (parsed.payload === undefined) {
      setImportError(parsed.error);
      return;
    }
    setImportError(null);
    setActionError(null);
    setNotice(null);
    importMutation.mutate({ saveId: importTargetId, payload: parsed.payload });
  };

  const data = saves.data;
  const items = data?.items ?? [];
  const importTarget = items.find((save) => save.id === importTargetId);
  const pager =
    data === undefined ? null : (
      <div className="jobs-pager">
        <span className="jobs-meta">共 {data.total} 个存档</span>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || saves.isFetching}
        >
          上一页
        </button>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(data.next_offset ?? offset)}
          disabled={data.next_offset === null || saves.isFetching}
        >
          下一页
        </button>
      </div>
    );

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={Archive}
        title="sidecar 未连接"
        description="连接 sidecar 后可以浏览、导入与管理存档。"
      />
    );
  } else if (saves.isPending) {
    body = (
      <p className="jobs-loading" role="status">
        正在加载存档…
      </p>
    );
  } else if (saves.isError) {
    body = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(saves.error)}</span>
        <button className="button small" type="button" onClick={() => void saves.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (data === undefined || items.length === 0) {
    body = (
      <>
        <EmptyState
          icon={Archive}
          title={status === "" ? "尚未导入存档" : "没有符合条件的存档"}
          description={
            status === ""
              ? "这是唯一的存档导入入口。导入后可以浏览联赛战术、生成真实 AI 计划、导出 FMF 或加入客队战术池。"
              : "当前筛选条件下没有存档，切换状态或新建存档。"
          }
        />
        {data !== undefined && data.total > 0 ? pager : null}
      </>
    );
  } else {
    body = (
      <>
        <div className="jobs-table-wrap">
          <table className="jobs-table">
            <caption className="sr-only">存档列表</caption>
            <thead>
              <tr>
                <th scope="col">存档路径</th>
                <th scope="col">状态</th>
                <th scope="col">阶段</th>
                <th scope="col">创建时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((save) => {
                const confirming = confirmation === save.id;
                return (
                  <tr key={save.id}>
                    <td>
                      <span className="data-path">{save.source_path}</span>
                    </td>
                    <td>
                      <span className="badge" data-tone={STATUS_TONES[save.status]}>
                        {STATUS_LABELS[save.status]}
                      </span>
                    </td>
                    <td className="jobs-kind">{save.stage ?? "—"}</td>
                    <td className="jobs-time">{formatTime(save.created_at)}</td>
                    <td>
                      <div className="jobs-actions">
                        <button
                          className="button small"
                          type="button"
                          onClick={() => openImport(save.id)}
                        >
                          导入
                        </button>
                        {confirming ? (
                          <>
                            <button
                              className="button small danger"
                              type="button"
                              disabled={remove.isPending}
                              onClick={() => remove.mutate(save)}
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
                            onClick={() => setConfirmation(save.id)}
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
        {pager}
      </>
    );
  }

  return (
    <Panel
      title="存档战术库"
      action={
        <div className="jobs-toolbar">
          <SaveStatusFilter value={status} onChange={changeStatus} />
          <button
            className="button"
            type="button"
            onClick={refresh}
            disabled={connection === null || saves.isFetching}
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
            新建存档
          </button>
        </div>
      }
    >
      {createOpen ? (
        <form className="jobs-create saves-create" aria-label="新建存档" onSubmit={submitCreate}>
          <div className="field">
            <label htmlFor="save-path">存档路径</label>
            <input
              id="save-path"
              value={sourcePath}
              aria-invalid={touched.path && pathError !== null}
              aria-describedby={touched.path && pathError !== null ? "save-path-error" : undefined}
              onChange={(event) => {
                setSourcePath(event.target.value);
                setTouched((state) => ({ ...state, path: true }));
              }}
            />
            {touched.path && pathError !== null ? (
              <span id="save-path-error" className="field-error">
                {pathError}
              </span>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="save-sha">SHA-256</label>
            <input
              id="save-sha"
              value={sourceSha}
              aria-invalid={touched.sha && shaError !== null}
              aria-describedby={touched.sha && shaError !== null ? "save-sha-error" : undefined}
              onChange={(event) => {
                setSourceSha(event.target.value);
                setTouched((state) => ({ ...state, sha: true }));
              }}
            />
            {touched.sha && shaError !== null ? (
              <span id="save-sha-error" className="field-error">
                {shaError}
              </span>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="save-stage">阶段</label>
            <input
              id="save-stage"
              value={stage}
              aria-invalid={touched.stage && stageError !== null}
              aria-describedby={touched.stage && stageError !== null ? "save-stage-error" : undefined}
              onChange={(event) => {
                setStage(event.target.value);
                setTouched((state) => ({ ...state, stage: true }));
              }}
            />
            {touched.stage && stageError !== null ? (
              <span id="save-stage-error" className="field-error">
                {stageError}
              </span>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="save-metadata">元数据 JSON</label>
            <textarea
              id="save-metadata"
              value={metadataText}
              aria-invalid={touched.metadata && metadata.error !== null}
              aria-describedby={
                touched.metadata && metadata.error !== null ? "save-metadata-error" : undefined
              }
              onChange={(event) => {
                setMetadataText(event.target.value);
                setTouched((state) => ({ ...state, metadata: true }));
              }}
            />
            {touched.metadata && metadata.error !== null ? (
              <span id="save-metadata-error" className="field-error">
                {metadata.error}
              </span>
            ) : null}
          </div>
          <button
            className="button primary"
            type="submit"
            disabled={connection === null || !formValid || create.isPending}
          >
            创建
          </button>
        </form>
      ) : null}
      {importTarget === undefined ? null : (
        <form className="saves-import" aria-label="导入存档数据" onSubmit={submitImport}>
          <p className="saves-import-target">
            导入到 <span className="data-path">{importTarget.source_path}</span>
          </p>
          <div className="field">
            <label htmlFor="import-json">导入 JSON</label>
            <textarea
              id="import-json"
              value={importText}
              placeholder={'{"leagues": {}, "clubs": {}}'}
              onChange={(event) => {
                setImportText(event.target.value);
                setImportError(null);
              }}
            />
          </div>
          {importError === null ? null : (
            <span className="field-error" role="alert">
              {importError}
            </span>
          )}
          <div className="saves-import-actions">
            <button className="button primary" type="submit" disabled={importMutation.isPending}>
              导入存档
            </button>
            <button
              className="button"
              type="button"
              onClick={() => {
                setImportTargetId(null);
                setImportText("");
                setImportError(null);
              }}
            >
              取消
            </button>
          </div>
        </form>
      )}
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
      {body}
    </Panel>
  );
}
