import { apiFetch, apiJson } from "./api";
import type { Connection } from "./connection";

export type SetpieceOption = { id: number; label: string };

export type SetpieceType = {
  id: number;
  label: string;
  strategy_kind: string | null;
  swing: boolean;
};

export type SetpieceFrequency = { id: number; label: string };

export type SetpieceCatalog = {
  allowed: Record<string, number[]>;
  attack: SetpieceOption[];
  defend: SetpieceOption[];
  categories: SetpieceOption[];
  swing: SetpieceOption[];
  corner_target?: SetpieceOption[];
  free_kick_risk?: SetpieceOption[];
  defensive_line?: SetpieceOption[];
  types: SetpieceType[];
  frequencies: SetpieceFrequency[];
};

export type SetpieceRoutine = {
  name: string;
  opaque_flags: number;
  frequency: number;
  strategy: number;
  swing: number;
  priority: number[];
  groups: number[][];
  backups: number[][];
};

export type SetpieceValue = {
  routines: Record<string, SetpieceRoutine[]>;
  throw_styles: number[];
  role_priorities: Record<string, number[]>;
};

export type SetpiecePlayer = { index: number; name: string };

export type SetpieceSummary = {
  setpiece_id: string;
  team: string;
  side: number;
  configured: boolean;
  updated_at: string | null;
};

export type SetpieceList = {
  catalog: SetpieceCatalog;
  setpieces: SetpieceSummary[];
};

export type SetpieceDetail = SetpieceSummary & {
  roster_size: number;
  players: SetpiecePlayer[];
  value: SetpieceValue;
  default: SetpieceValue;
};

export type SetpieceImportInput = {
  content_base64?: string;
  source_path?: string;
};

export async function listSetpieces(connection: Connection): Promise<SetpieceList> {
  return apiJson<SetpieceList>(connection, "/api/setpieces");
}

export async function getSetpiece(connection: Connection, setpieceId: string): Promise<SetpieceDetail> {
  return apiJson<SetpieceDetail>(connection, "/api/setpieces/" + encodeURIComponent(setpieceId));
}

export async function saveSetpiece(
  connection: Connection,
  setpieceId: string,
  value: SetpieceValue,
): Promise<SetpieceDetail> {
  return apiJson<SetpieceDetail>(connection, "/api/setpieces/" + encodeURIComponent(setpieceId), {
    method: "PATCH",
    body: JSON.stringify({ value }),
  });
}

export async function importSetpieceFile(
  connection: Connection,
  setpieceId: string,
  input: SetpieceImportInput,
): Promise<SetpieceDetail> {
  return apiJson<SetpieceDetail>(
    connection,
    "/api/setpieces/" + encodeURIComponent(setpieceId) + "/import-file",
    { method: "POST", body: JSON.stringify(input) },
  );
}

function documentFilename(response: Response, setpieceId: string): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return match === null ? "setpieces-" + setpieceId + ".json" : match[1];
}

export async function exportSetpieceFile(
  connection: Connection,
  setpieceId: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await apiFetch(
    connection,
    "/api/setpieces/" + encodeURIComponent(setpieceId) + "/export-file",
  );
  return { blob: await response.blob(), filename: documentFilename(response, setpieceId) };
}
