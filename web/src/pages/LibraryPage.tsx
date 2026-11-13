import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowClockwise, Plus } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  ApiError,
  applyRoster,
  createSave,
  deleteSave,
  getSaveSquad,
  importSave,
  importSaveFile,
  listDrafts,
  listSaves,
  undoRoster,
  type RosterScope,
  type RosterSide,
  type Save,
  type SaveCreate,
  type SaveFileImportResult,
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

function statusLabel(status: string): string {
  return STATUS_LABELS[status as SaveStatus] ?? status;
}

function statusTone(status: string): "ok" | "warn" | "error" | undefined {
  return STATUS_TONES[status as SaveStatus];
}

function managedClubUids(save: Save | undefined): number[] {
  const value = save?.metadata?.managed_club_uids;
  if (!Array.isArray(value)) return [];
  return value.filter((uid): uid is number => typeof uid === "number");
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
  const [fileFormOpen, setFileFormOpen] = useState(false);
  const [fileSourcePath, setFileSourcePath] = useState("");
  const [fileReplace, setFileReplace] = useState(false);
  const [fileTouched, setFileTouched] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [fileConflict, setFileConflict] = useState(false);
  const [fileResult, setFileResult] = useState<SaveFileImportResult | null>(null);
  const [squadSaveId, setSquadSaveId] = useState<string | null>(null);
  const [squadClubUid, setSquadClubUid] = useState<number | null>(null);
  const [rosterDraftId, setRosterDraftId] = useState("");
  const [rosterSide, setRosterSide] = useState<RosterSide>("home");
  const [rosterScope, setRosterScope] = useState<RosterScope>("starters");
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [rosterNotice, setRosterNotice] = useState<string | null>(null);

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

  const squad = useQuery({
    queryKey: ["save-squad", connection?.url, squadSaveId, squadClubUid],
    queryFn: () => getSaveSquad(connection!, squadSaveId!, squadClubUid!),
    enabled: connection !== null && squadSaveId !== null && squadClubUid !== null,
  });

  const drafts = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null && squadSaveId !== null,
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

  const filePathTrimmed = fileSourcePath.trim();
  const filePathError =
    filePathTrimmed === ""
      ? "存档文件路径不能为空"
      : filePathTrimmed.length > MAX_SOURCE_PATH
        ? `存档文件路径最多 ${MAX_SOURCE_PATH} 个字符`
        : null;

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

  const fileImport = useMutation({
    mutationFn: (input: { source_path: string; replace: boolean }) =>
      importSaveFile(connection!, input),
    onSuccess: (result) => {
      setFileResult(result);
      setFileFormOpen(false);
      setFileTouched(false);
      setFileError(null);
      setFileConflict(false);
      setActionError(null);
      setNotice(null);
      invalidateSaves();
    },
    onError: (error) => {
      setFileResult(null);
      setFileError(errorMessage(error));
      setFileConflict(error instanceof ApiError && error.status === 409);
    },
  });

  const remove = useMutation({
    mutationFn: (save: Save) => deleteSave(connection!, save.id),
    onSuccess: (_result, save) => {
      setConfirmation(null);
      setActionError(null);
      setNotice("已删除存档");
      if (squadSaveId === save.id) {
        setSquadSaveId(null);
        setSquadClubUid(null);
        setRosterError(null);
        setRosterNotice(null);
      }
      invalidateSaves();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const draftItems = Array.isArray(drafts.data?.items) ? drafts.data.items : [];
  const activeDraftId = draftItems.some((item) => item.id === rosterDraftId)
    ? rosterDraftId
    : (draftItems[0]?.id ?? "");

  const applyRosterMutation = useMutation({
    mutationFn: (input: { side: RosterSide; scope: RosterScope }) =>
      applyRoster(connection!, activeDraftId, {
        save_id: squadSaveId!,
        club_uid: squadClubUid!,
        side: input.side,
        scope: input.scope,
      }),
    onSuccess: (result) => {
      setRosterError(null);
      setRosterNotice(
        `已同步：首发 ${result.applied.starters} 人、替补 ${result.applied.substitutes} 人`,
      );
      void queryClient.invalidateQueries({ queryKey: ["draft"] });
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
    onError: (error) => {
      setRosterNotice(null);
      setRosterError(errorMessage(error));
    },
  });

  const undoRosterMutation = useMutation({
    mutationFn: () => undoRoster(connection!, activeDraftId),
    onSuccess: () => {
      setRosterError(null);
      setRosterNotice("已撤销阵容同步");
      void queryClient.invalidateQueries({ queryKey: ["draft"] });
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
    onError: (error) => {
      setRosterNotice(null);
      setRosterError(errorMessage(error));
    },
  });

  const changeStatus = (next: SaveStatus | "") => {
    setStatus(next);
    setOffset(0);
    setConfirmation(null);
    setActionError(null);
    setNotice(null);
    setSquadSaveId(null);
    setSquadClubUid(null);
  };

  const openCreate = () => {
    setCreateOpen((open) => !open);
    setImportTargetId(null);
    setImportError(null);
    setFileFormOpen(false);
    setActionError(null);
    setNotice(null);
  };

  const openImport = (saveId: string) => {
    setImportTargetId(saveId);
    setImportText("");
    setImportError(null);
    setCreateOpen(false);
    setFileFormOpen(false);
    setConfirmation(null);
    setActionError(null);
    setNotice(null);
  };

  const openFileImport = () => {
    setFileFormOpen((open) => !open);
    setFileTouched(false);
    setFileError(null);
    setFileConflict(false);
    setFileResult(null);
    setCreateOpen(false);
    setImportTargetId(null);
    setActionError(null);
    setNotice(null);
  };

  const closeFileImport = () => {
    setFileFormOpen(false);
    setFileTouched(false);
    setFileError(null);
    setFileConflict(false);
  };

  const openSquad = (saveId: string) => {
    setSquadSaveId(saveId);
    setSquadClubUid(null);
    setRosterError(null);
    setRosterNotice(null);
    setFileFormOpen(false);
    setCreateOpen(false);
    setImportTargetId(null);
    setActionError(null);
    setNotice(null);
  };

  const closeSquad = () => {
    setSquadSaveId(null);
    setSquadClubUid(null);
    setRosterError(null);
    setRosterNotice(null);
  };

  const selectClub = (clubUid: number) => {
    setSquadClubUid(clubUid);
    setRosterError(null);
    setRosterNotice(null);
  };

  const changeRosterDraft = (draftId: string) => {
    setRosterDraftId(draftId);
    setRosterError(null);
    setRosterNotice(null);
  };

  const changeRosterSide = (side: RosterSide) => {
    setRosterSide(side);
    setRosterError(null);
    setRosterNotice(null);
  };

  const changeRosterScope = (scope: RosterScope) => {
    setRosterScope(scope);
    setRosterError(null);
    setRosterNotice(null);
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

  const submitFileImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFileTouched(true);
    if (connection === null || filePathError !== null || fileImport.isPending) return;
    setFileError(null);
    setFileConflict(false);
    fileImport.mutate({ source_path: filePathTrimmed, replace: fileReplace });
  };

  const overwriteFileImport = () => {
    if (connection === null || filePathTrimmed === "" || fileImport.isPending) return;
    setFileError(null);
    setFileConflict(false);
    fileImport.mutate({ source_path: filePathTrimmed, replace: true });
  };

  const submitRoster = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      connection === null ||
      activeDraftId === "" ||
      squadSaveId === null ||
      squadClubUid === null ||
      applyRosterMutation.isPending
    ) {
      return;
    }
    setRosterError(null);
    setRosterNotice(null);
    applyRosterMutation.mutate({ side: rosterSide, scope: rosterScope });
  };

  const undoRosterSync = () => {
    if (connection === null || activeDraftId === "" || undoRosterMutation.isPending) return;
    setRosterError(null);
    setRosterNotice(null);
    undoRosterMutation.mutate();
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
                          onClick={() => openSquad(save.id)}
                        >
                          查看名单
                        </button>
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

  const squadSave = items.find((save) => save.id === squadSaveId);
  const clubUids = managedClubUids(squadSave);
  const squadData = squad.data;
  const selection = squadData?.selection ?? null;
  const squadCounts =
    selection === null
      ? null
      : {
          starters: Array.isArray(selection.lineup) ? selection.lineup.length : 0,
          substitutes: Array.isArray(selection.substitutes)
            ? selection.substitutes.length
            : 0,
        };

  const rosterPanel = (
    <section className="saves-roster" aria-label="阵容同步">
      <h3>阵容同步</h3>
      <form className="saves-roster-form" aria-label="阵容同步表单" onSubmit={submitRoster}>
        <label className="field">
          草稿
          <select
            aria-label="选择同步草稿"
            value={activeDraftId}
            onChange={(event) => changeRosterDraft(event.target.value)}
            disabled={draftItems.length === 0}
          >
            {draftItems.length === 0 ? (
              <option value="">{drafts.isPending ? "正在加载草稿…" : "没有可用草稿"}</option>
            ) : (
              draftItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))
            )}
          </select>
        </label>
        <div className="segmented" role="group" aria-label="阵容同步球队">
          <button
            type="button"
            aria-pressed={rosterSide === "home"}
            onClick={() => changeRosterSide("home")}
          >
            主队
          </button>
          <button
            type="button"
            aria-pressed={rosterSide === "away"}
            onClick={() => changeRosterSide("away")}
          >
            客队
          </button>
        </div>
        <label className="field">
          同步范围
          <select
            aria-label="同步范围"
            value={rosterScope}
            onChange={(event) => changeRosterScope(event.target.value as RosterScope)}
          >
            <option value="starters">首发</option>
            <option value="bench">替补</option>
            <option value="both">全部</option>
          </select>
        </label>
        <div className="saves-roster-actions">
          <button
            className="button primary"
            type="submit"
            disabled={activeDraftId === "" || applyRosterMutation.isPending}
          >
            同步阵容
          </button>
          <button
            className="button"
            type="button"
            disabled={activeDraftId === "" || undoRosterMutation.isPending}
            onClick={undoRosterSync}
          >
            撤销同步
          </button>
        </div>
      </form>
      {drafts.isError ? (
        <p className="field-hint" role="alert">
          草稿列表加载失败：{errorMessage(drafts.error)}
        </p>
      ) : null}
      {rosterError === null ? null : (
        <div className="inline-alert" role="alert">
          {rosterError}
        </div>
      )}
      {rosterNotice === null ? null : (
        <p className="jobs-notice" role="status">
          {rosterNotice}
        </p>
      )}
    </section>
  );

  let squadPanel: ReactNode = null;
  if (squadClubUid !== null) {
    if (squad.isPending) {
      squadPanel = (
        <p className="jobs-loading" role="status">
          正在加载名单…
        </p>
      );
    } else if (squad.isError) {
      squadPanel = (
        <div className="inline-alert" role="alert">
          <span>{errorMessage(squad.error)}</span>
          <button className="button small" type="button" onClick={() => void squad.refetch()}>
            重试
          </button>
        </div>
      );
    } else if (squadData !== undefined) {
      squadPanel = (
        <>
          <p className="saves-squad-title">
            {squadData.club_name ?? `俱乐部 ${squadClubUid}`}
          </p>
          {squadData.players.length === 0 ? (
            <p className="field-hint">该俱乐部没有可读取的球员</p>
          ) : (
            <>
              <p className="saves-selection">
                {squadCounts === null
                  ? "暂无上一场阵容记录"
                  : `首发 ${squadCounts.starters} 人 · 替补 ${squadCounts.substitutes} 人`}
              </p>
              <div className="jobs-table-wrap">
                <table className="jobs-table saves-squad-table">
                  <caption className="sr-only">存档球队球员名单</caption>
                  <thead>
                    <tr>
                      <th scope="col">姓名</th>
                      <th scope="col">位置</th>
                      <th scope="col">能力</th>
                    </tr>
                  </thead>
                  <tbody>
                    {squadData.players.map((player) => (
                      <tr key={String(player.source_uid)}>
                        <td>{player.name === "" ? "—" : player.name}</td>
                        <td className="jobs-kind">{player.position === "" ? "—" : player.position}</td>
                        <td className="jobs-number">{player.ability ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rosterPanel}
            </>
          )}
        </>
      );
    }
  }

  const squadSection =
    squadSaveId === null ? null : (
      <section className="saves-squad" aria-label="存档球队名单">
        <div className="saves-squad-head">
          <h3>存档球队名单</h3>
          <button className="button small" type="button" onClick={closeSquad}>
            关闭
          </button>
        </div>
        <p className="saves-squad-target">
          存档：<span className="data-path">{squadSave?.source_path ?? squadSaveId}</span>
        </p>
        {clubUids.length === 0 ? (
          <p className="field-hint">该存档没有可读取的经理俱乐部</p>
        ) : (
          <div className="saves-clubs" role="group" aria-label="经理俱乐部">
            {clubUids.map((uid) => (
              <button
                key={uid}
                className="button small"
                type="button"
                aria-pressed={squadClubUid === uid}
                onClick={() => selectClub(uid)}
              >
                俱乐部 {uid}
              </button>
            ))}
          </div>
        )}
        {squadPanel}
      </section>
    );

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
            className="button"
            type="button"
            onClick={openFileImport}
            disabled={connection === null}
          >
            导入存档文件
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
      {fileFormOpen ? (
        <form
          className="saves-import saves-file-import"
          aria-label="导入存档文件"
          onSubmit={submitFileImport}
        >
          <div className="field">
            <label htmlFor="file-import-path">存档文件路径</label>
            <input
              id="file-import-path"
              value={fileSourcePath}
              aria-invalid={fileTouched && filePathError !== null}
              aria-describedby={
                fileTouched && filePathError !== null ? "file-import-path-error" : undefined
              }
              onChange={(event) => {
                setFileSourcePath(event.target.value);
                setFileTouched(true);
              }}
            />
            {fileTouched && filePathError !== null ? (
              <span id="file-import-path-error" className="field-error">
                {filePathError}
              </span>
            ) : null}
          </div>
          <label className="field-inline">
            <input
              type="checkbox"
              checked={fileReplace}
              onChange={(event) => setFileReplace(event.target.checked)}
            />
            覆盖已存在的存档
          </label>
          <div className="saves-import-actions">
            <button
              className="button primary"
              type="submit"
              disabled={connection === null || fileImport.isPending}
            >
              导入文件
            </button>
            <button className="button" type="button" onClick={closeFileImport}>
              取消
            </button>
          </div>
          {fileError === null ? null : (
            <div className="inline-alert" role="alert">
              <span>{fileError}</span>
              {fileConflict ? (
                <button
                  className="button small"
                  type="button"
                  disabled={fileImport.isPending}
                  onClick={overwriteFileImport}
                >
                  覆盖导入
                </button>
              ) : null}
            </div>
          )}
        </form>
      ) : null}
      {fileResult === null ? null : (
        <section className="saves-import-result" aria-label="存档文件导入结果">
          <p className="jobs-notice" role="status">
            存档文件已导入
          </p>
          <dl className="saves-import-result-facts">
            <div>
              <dt>存档 ID</dt>
              <dd className="data-path">{fileResult.save_id}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>
                <span className="badge" data-tone={statusTone(fileResult.status)}>
                  {statusLabel(fileResult.status)}
                </span>
              </dd>
            </div>
            <div>
              <dt>经理俱乐部</dt>
              <dd>{fileResult.clubs} 个</dd>
            </div>
          </dl>
          {fileResult.managed_clubs.length === 0 ? (
            <p className="field-hint">该存档没有可读取的经理俱乐部</p>
          ) : (
            <ul className="saves-import-clubs">
              {fileResult.managed_clubs.map((club) => (
                <li key={club.club_uid}>
                  {club.club_name ?? `俱乐部 ${club.club_uid}`}（{club.players} 人）
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
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
      {squadSection}
    </Panel>
  );
}
