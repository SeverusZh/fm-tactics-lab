import { apiFetch, apiJson } from "./api";
import type { PoolEntry } from "./api-pools";
import type { Connection } from "./connection";

const FORBIDDEN_NAME_CHARS = /[\\/:*?"<>|]/g;
const CONTROL_NAME_CHARS = /[\u0000-\u001f\u007f]/g;
const EDGE_DOTS = /^[ .]+|[ .]+$/g;
const MAX_FMF_NAME = 100;
const FALLBACK_FMF_NAME = "tactic";

export function fmfDownloadName(name: string): string {
  const cleaned = name
    .replace(FORBIDDEN_NAME_CHARS, "")
    .replace(CONTROL_NAME_CHARS, "")
    .replace(EDGE_DOTS, "");
  const sized = Array.from(cleaned).slice(0, MAX_FMF_NAME).join("");
  return `${sized === "" ? FALLBACK_FMF_NAME : sized}.fmf`;
}

export async function exportSaveTacticFmf(
  connection: Connection,
  saveId: string,
  tacticIndex: number,
): Promise<Blob> {
  const response = await apiFetch(
    connection,
    `/api/saves/${encodeURIComponent(saveId)}/tactics/${tacticIndex}/export.fmf`,
  );
  return response.blob();
}

export function addSaveTacticToPool(
  connection: Connection,
  saveId: string,
  tacticIndex: number,
): Promise<PoolEntry> {
  return apiJson<PoolEntry>(
    connection,
    `/api/saves/${encodeURIComponent(saveId)}/tactics/${tacticIndex}/pool`,
    { method: "POST" },
  );
}
