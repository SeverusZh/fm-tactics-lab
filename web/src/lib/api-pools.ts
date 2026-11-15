import { apiFetch, apiJson } from "./api";
import type { Connection } from "./connection";

export type PoolTactic = Record<string, unknown>;

export type PoolEntry = {
  id: string;
  name: string;
  weight: number;
  tactic: PoolTactic;
  roster: PoolTactic | null;
  created_at: string;
};

export type PoolList = {
  items: PoolEntry[];
  total: number;
  next_offset: number | null;
};

export type PoolUpdateInput = {
  name?: string;
  weight?: number;
};

export type PoolImportInput = {
  content_base64: string;
  name?: string;
};

export type PoolImportResult = {
  items: PoolEntry[];
  total: number;
};

function poolPath(entryId: string): string {
  return "/api/pools/" + encodeURIComponent(entryId);
}

export async function listPools(connection: Connection): Promise<PoolList> {
  return apiJson<PoolList>(connection, "/api/pools");
}

export async function updatePool(
  connection: Connection,
  entryId: string,
  input: PoolUpdateInput,
): Promise<PoolEntry> {
  return apiJson<PoolEntry>(connection, poolPath(entryId), {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deletePool(connection: Connection, entryId: string): Promise<void> {
  await apiFetch(connection, poolPath(entryId), { method: "DELETE" });
}

export async function importPoolsFmf(
  connection: Connection,
  input: PoolImportInput,
): Promise<PoolImportResult> {
  return apiJson<PoolImportResult>(connection, "/api/pools/import-fmf", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
