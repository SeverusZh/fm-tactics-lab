import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowClockwise } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  ApiError,
  applyRoster,
  deleteSave,
  getSaveSquad,
  importFmfFile,
  importSaveFile,
  importSaveTactic,
  listDrafts,
  listSaves,
  listSaveTactics,
  undoRoster,
  type FmfFileImportInput,
  type RosterScope,
  type RosterSide,
  type Save,
  type SaveFileImportResult,
  type SaveStatus,
  type SaveTactic,
} from "../lib/api";
import { chooseLocalFile, isDesktopShell } from "../lib/file-dialog";
import "../styles/library.css";

const PAGE_SIZE = 20;
const MAX_SOURCE_PATH = 4096;

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

const FMF_NAME_MAX_LENGTH = 80;

function deriveFmfName(path: string): string {
  const normalized = path.trim();
  const separator = Math.max(normalized.lastIndexOf("\\"), normalized.lastIndexOf("/"));
  const basename = normalized.slice(separator + 1);
  const withoutExtension = basename.toLowerCase().endsWith(".fmf")
    ? basename.slice(0, -".fmf".length)
    : basename;
  const trimmed = withoutExtension.trim();
  return (trimmed === "" ? "导入战术" : trimmed).slice(0, FMF_NAME_MAX_LENGTH);
}

const MENTALITY_LABELS: Record<number, string> = {
  1: "极度防守",
  2: "防守",
  3: "谨慎",
  4: "均衡",
  5: "积极",
  6: "进攻",
  7: "全力进攻",
};

function mentalityLabel(value: number | null): string {
  if (value === null) return "—";
  return MENTALITY_LABELS[value] ?? String(value);
}

function teamSlotLabel(value: number | null): string {
  if (value === null) return "—";
  return value === 0 ? "一线队" : `槽位 ${value}`;
}

function tacticImportBlocker(tactic: SaveTactic): string | null {
  if (tactic.importable) return null;
  return tactic.team_slot === 0 ? "需要先配置引擎资源" : "非一线队存储战术";
}

export function LibraryPage() {
  const { connection } = useAppContext();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [status, setStatus] = useState<SaveStatus | "">("");
  const [offset, setOffset] = useState(0);
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
  const [fmfFormOpen, setFmfFormOpen] = useState(false);
  const [fmfSourcePath, setFmfSourcePath] = useState("");
  const [fmfName, setFmfName] = useState("");
  const [fmfNameEdited, setFmfNameEdited] = useState(false);
  const [fmfTouched, setFmfTouched] = useState(false);
  const [fmfError, setFmfError] = useState<string | null>(null);
  const [squadSaveId, setSquadSaveId] = useState<string | null>(null);
  const [squadClubUid, setSquadClubUid] = useState<number | null>(null);
  const [tacticsSaveId, setTacticsSaveId] = useState<string | null>(null);
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

  const saveTactics = useQuery({
    queryKey: ["save-tactics", connection?.url, tacticsSaveId],
    queryFn: () => listSaveTactics(connection!, tacticsSaveId!),
    enabled: connection !== null && tacticsSaveId !== null,
  });

  const drafts = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null && squadSaveId !== null,
  });

  const invalidateSaves = () => {
    void queryClient.invalidateQueries({ queryKey: ["saves"] });
  };

  const filePathTrimmed = fileSourcePath.trim();
  const filePathError =
    filePathTrimmed === ""
      ? "存档文件路径不能为空"
      : filePathTrimmed.length > MAX_SOURCE_PATH
        ? `存档文件路径最多 ${MAX_SOURCE_PATH} 个字符`
        : null;

  const fmfPathTrimmed = fmfSourcePath.trim();
  const fmfPathError = fmfPathTrimmed === "" ? "战术文件路径不能为空" : null;
  const fmfNameTrimmed = fmfName.trim();

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

  const fmfImport = useMutation({
    mutationFn: (input: FmfFileImportInput) => importFmfFile(connection!, input),
    retry: false,
    onSuccess: (draft) => {
      setFmfFormOpen(false);
      setFmfTouched(false);
      setFmfError(null);
      setFmfSourcePath("");
      setFmfName("");
      setFmfNameEdited(false);
      setActionError(null);
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: ["drafts", connection?.url] });
      navigate(`/tactics?draft=${draft.id}`);
    },
    onError: (error) => {
      setFmfError(errorMessage(error));
    },
  });

  const importTactic = useMutation({
    mutationFn: (tacticIndex: number) =>
      importSaveTactic(connection!, tacticsSaveId!, tacticIndex),
    retry: false,
    onSuccess: (draft) => {
      void queryClient.invalidateQueries({ queryKey: ["drafts", connection?.url] });
      navigate(`/tactics?draft=${draft.id}`);
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
      if (tacticsSaveId === save.id) {
        setTacticsSaveId(null);
        importTactic.reset();
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
    setTacticsSaveId(null);
    importTactic.reset();
  };

  const pickSaveFile = async () => {
    try {
      const selected = await chooseLocalFile({
        title: "选择存档文件",
        filters: [{ name: "FM 存档", extensions: ["fm"] }],
      });
      if (selected === null) return;
      setFileSourcePath(selected);
      setFileTouched(true);
    } catch (error) {
      setFileError(errorMessage(error));
    }
  };

  const openFileImport = () => {
    setFileFormOpen(true);
    setFileTouched(false);
    setFileError(null);
    setFileConflict(false);
    setFileResult(null);
    setFmfFormOpen(false);
    setActionError(null);
    setNotice(null);
    if (!isDesktopShell()) return;
    void pickSaveFile();
  };

  const closeFileImport = () => {
    setFileFormOpen(false);
    setFileTouched(false);
    setFileError(null);
    setFileConflict(false);
  };

  const applyFmfPath = (path: string) => {
    setFmfSourcePath(path);
    setFmfTouched(true);
    if (!fmfNameEdited || fmfName.trim() === "") {
      setFmfName(deriveFmfName(path));
    }
  };

  const pickFmfFile = async () => {
    try {
      const selected = await chooseLocalFile({
        title: "选择 FMF 战术文件",
        filters: [{ name: "FMF 战术文件", extensions: ["fmf"] }],
      });
      if (selected === null) return;
      applyFmfPath(selected);
    } catch (error) {
      setFmfError(errorMessage(error));
    }
  };

  const openFmfImport = () => {
    setFmfFormOpen(true);
    setFmfTouched(false);
    setFmfError(null);
    setFileFormOpen(false);
    setFileTouched(false);
    setFileError(null);
    setFileConflict(false);
    setFileResult(null);
    setActionError(null);
    setNotice(null);
    if (!isDesktopShell()) return;
    void pickFmfFile();
  };

  const closeFmfImport = () => {
    setFmfFormOpen(false);
    setFmfTouched(false);
    setFmfError(null);
  };

  const openSquad = (saveId: string) => {
    setSquadSaveId(saveId);
    setTacticsSaveId(null);
    importTactic.reset();
    setFmfFormOpen(false);
    setSquadClubUid(null);
    setRosterError(null);
    setRosterNotice(null);
    setFileFormOpen(false);
    setActionError(null);
    setNotice(null);
  };

  const closeSquad = () => {
    setSquadSaveId(null);
    setSquadClubUid(null);
    setRosterError(null);
    setRosterNotice(null);
  };

  const openTactics = (saveId: string) => {
    setTacticsSaveId(saveId);
    setSquadSaveId(null);
    setSquadClubUid(null);
    setRosterError(null);
    setRosterNotice(null);
    setFileFormOpen(false);
    setFmfFormOpen(false);
    setActionError(null);
    setNotice(null);
    importTactic.reset();
  };

  const closeTactics = () => {
    setTacticsSaveId(null);
    importTactic.reset();
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

  const submitFmfImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFmfTouched(true);
    if (connection === null || fmfPathError !== null || fmfImport.isPending) return;
    setFmfError(null);
    const input: FmfFileImportInput = { source_path: fmfPathTrimmed };
    if (fmfNameTrimmed !== "") input.name = fmfNameTrimmed;
    fmfImport.mutate(input);
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
  const pager =
    data === undefined ? null : (
      <div className="jobs-pager">
        <span className="jobs-meta">共 {data.total} 个存档</span>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || saves.isFetching}
          title={
            offset === 0 ? "已是第一页" : saves.isFetching ? "正在刷新存档列表" : undefined
          }
        >
          上一页
        </button>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(data.next_offset ?? offset)}
          disabled={data.next_offset === null || saves.isFetching}
          title={
            data.next_offset === null
              ? "已是最后一页"
              : saves.isFetching
                ? "正在刷新存档列表"
                : undefined
          }
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
              ? "这是唯一的存档导入入口。导入后可以浏览联赛战术、生成真实 AI 计划、导出 FMF 或加入客队战术池。没有存档也可以导入 FMF 战术文件使用战术板与固定对手实验。"
              : "当前筛选条件下没有存档，切换状态后重试。"
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
                          onClick={() => openTactics(save.id)}
                        >
                          战术库
                        </button>
                        <button
                          className="button small"
                          type="button"
                          onClick={() => openSquad(save.id)}
                        >
                          查看名单
                        </button>
                        {confirming ? (
                          <>
                            <button
                              className="button small danger"
                              type="button"
                              disabled={remove.isPending}
                              title={remove.isPending ? "正在删除存档" : undefined}
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
            aria-describedby={
              drafts.isSuccess && draftItems.length === 0 ? "saves-roster-hint" : undefined
            }
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
        {drafts.isSuccess && draftItems.length === 0 ? (
          <p className="field-hint" id="saves-roster-hint">
            先在战术板保存草稿，才能同步阵容
          </p>
        ) : null}
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
            aria-describedby={
              drafts.isSuccess && draftItems.length === 0 ? "saves-roster-hint" : undefined
            }
            title={applyRosterMutation.isPending ? "正在同步阵容" : undefined}
          >
            同步阵容
          </button>
          <button
            className="button"
            type="button"
            disabled={activeDraftId === "" || undoRosterMutation.isPending}
            aria-describedby={
              drafts.isSuccess && draftItems.length === 0 ? "saves-roster-hint" : undefined
            }
            title={undoRosterMutation.isPending ? "正在撤销同步" : undefined}
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

  const tacticsSave = items.find((save) => save.id === tacticsSaveId);
  const tactics = saveTactics.data ?? [];
  const importTacticEngineUnavailable =
    importTactic.error instanceof ApiError &&
    (importTactic.error.status === 503 || importTactic.error.code === "engine_unavailable");

  let tacticsPanel: ReactNode = null;
  if (saveTactics.isPending) {
    tacticsPanel = (
      <p className="jobs-loading" role="status">
        正在加载存档战术…
      </p>
    );
  } else if (saveTactics.isError) {
    tacticsPanel = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(saveTactics.error)}</span>
        <button className="button small" type="button" onClick={() => void saveTactics.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (saveTactics.isSuccess) {
    tacticsPanel =
      tactics.length === 0 ? (
        <p className="field-hint">该存档没有可用的存储战术</p>
      ) : (
        <div className="jobs-table-wrap">
          <table className="jobs-table saves-tactics-table">
            <caption className="sr-only">存档存储战术列表</caption>
            <thead>
              <tr>
                <th scope="col">名称</th>
                <th scope="col">风格</th>
                <th scope="col">心态</th>
                <th scope="col">槽位</th>
                <th scope="col">可导入</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {tactics.map((tactic) => {
                const blocker = tacticImportBlocker(tactic);
                const importing =
                  importTactic.isPending && importTactic.variables === tactic.index;
                return (
                  <tr key={tactic.index}>
                    <td>{tactic.name === "" ? "—" : tactic.name}</td>
                    <td className="jobs-kind">{tactic.style === "" ? "—" : tactic.style}</td>
                    <td>{mentalityLabel(tactic.mentality)}</td>
                    <td>
                      <span
                        className="saves-tactic-slot"
                        data-primary={tactic.team_slot === 0 ? "true" : undefined}
                      >
                        {teamSlotLabel(tactic.team_slot)}
                      </span>
                    </td>
                    <td>
                      <span className="badge" data-tone={tactic.importable ? "ok" : "warn"}>
                        {tactic.importable ? "可导入" : "不可导入"}
                      </span>
                    </td>
                    <td>
                      <div className="jobs-actions">
                        <button
                          className="button small"
                          type="button"
                          disabled={!tactic.importable || importTactic.isPending}
                          title={
                            blocker ??
                            (importTactic.isPending ? "正在导入存档战术" : undefined)
                          }
                          onClick={() => importTactic.mutate(tactic.index)}
                        >
                          {importing ? "导入中…" : "导入到战术板"}
                        </button>
                        {blocker === null ? null : (
                          <span className="field-hint">{blocker}</span>
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

  const tacticsSection =
    tacticsSaveId === null ? null : (
      <section className="saves-tactics" aria-label="存档存储战术">
        <div className="saves-tactics-head">
          <h3>存储战术</h3>
          <button className="button small" type="button" onClick={closeTactics}>
            关闭
          </button>
        </div>
        <p className="saves-tactics-target">
          存档：<span className="data-path">{tacticsSave?.source_path ?? tacticsSaveId}</span>
        </p>
        {importTactic.error === null ? null : (
          <div className="inline-alert" role="alert">
            <span>{errorMessage(importTactic.error)}</span>
            {importTacticEngineUnavailable ? (
              <Link className="saves-settings-link" to="/settings">
                去设置页
              </Link>
            ) : null}
          </div>
        )}
        {tacticsPanel}
      </section>
    );

  return (
    <Panel
      title="存档战术库"
      action={
        <div className="jobs-toolbar">
          <SaveStatusFilter value={status} onChange={changeStatus} />
          {saves.isFetching && !saves.isPending ? (
            <span className="jobs-hint" role="status">
              正在刷新存档列表
            </span>
          ) : null}
          <button
            className="button"
            type="button"
            onClick={refresh}
            disabled={connection === null || saves.isFetching}
            title={saves.isFetching ? "正在刷新存档列表" : undefined}
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
            className="button"
            type="button"
            onClick={openFmfImport}
            disabled={connection === null}
          >
            导入 FMF 战术文件
          </button>
        </div>
      }
    >
      {fileFormOpen ? (
        <form
          className="saves-import saves-file-import"
          aria-label="导入存档文件"
          onSubmit={submitFileImport}
        >
          <div className="field">
            <label htmlFor="file-import-path">存档文件路径</label>
            <div className="field-row">
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
              {isDesktopShell() ? (
                <button
                  className="button small"
                  type="button"
                  disabled={fileImport.isPending}
                  title={fileImport.isPending ? "正在导入存档文件" : undefined}
                  onClick={() => void pickSaveFile()}
                >
                  浏览…
                </button>
              ) : null}
            </div>
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
              title={fileImport.isPending ? "正在导入存档文件" : undefined}
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
                  title={fileImport.isPending ? "正在导入存档文件" : undefined}
                  onClick={overwriteFileImport}
                >
                  覆盖导入
                </button>
              ) : null}
            </div>
          )}
        </form>
      ) : null}
      {fmfFormOpen ? (
        <form
          className="saves-import saves-fmf-import"
          aria-label="导入 FMF 战术文件"
          aria-busy={fmfImport.isPending ? true : undefined}
          onSubmit={submitFmfImport}
        >
          <p className="field-hint">
            FMF 文件自带双队场景，无需存档即可直接用于战术板与固定对手实验。
          </p>
          <div className="field">
            <label htmlFor="fmf-import-path">战术文件路径</label>
            <div className="field-row">
              <input
                id="fmf-import-path"
                value={fmfSourcePath}
                aria-invalid={fmfTouched && fmfPathError !== null}
                aria-describedby={
                  fmfTouched && fmfPathError !== null ? "fmf-import-path-error" : undefined
                }
                onChange={(event) => {
                  setFmfSourcePath(event.target.value);
                  setFmfTouched(true);
                  if (!fmfNameEdited || fmfName.trim() === "") {
                    setFmfName(deriveFmfName(event.target.value));
                  }
                }}
              />
              {isDesktopShell() ? (
                <button
                  className="button small"
                  type="button"
                  disabled={fmfImport.isPending}
                  title={fmfImport.isPending ? "正在导入战术文件" : undefined}
                  onClick={() => void pickFmfFile()}
                >
                  浏览…
                </button>
              ) : null}
            </div>
            {fmfTouched && fmfPathError !== null ? (
              <span id="fmf-import-path-error" className="field-error">
                {fmfPathError}
              </span>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="fmf-import-name">名称</label>
            <input
              id="fmf-import-name"
              value={fmfName}
              onChange={(event) => {
                setFmfName(event.target.value);
                setFmfNameEdited(true);
              }}
            />
          </div>
          <div className="saves-import-actions">
            <button
              className="button primary"
              type="submit"
              disabled={connection === null || fmfImport.isPending}
              title={fmfImport.isPending ? "正在导入战术文件" : undefined}
            >
              {fmfImport.isPending ? "导入中…" : "导入 FMF"}
            </button>
            <button className="button" type="button" onClick={closeFmfImport}>
              取消
            </button>
          </div>
          {fmfError === null ? null : (
            <div className="inline-alert" role="alert">
              <span>{fmfError}</span>
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
      {tacticsSection}
    </Panel>
  );
}
