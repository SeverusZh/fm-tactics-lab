import { apiJson } from "./api";
import type { Connection } from "./connection";

export type FormationCell = { position: string; role: string; x: number; y: number };

export type Formation = {
  id: string;
  name: string;
  phases: FormationCell[][];
};

export type FormationInstructionOption = {
  id: number | string;
  label?: string;
  name?: string;
};

export type FormationInstructionGroup = {
  id: number | string;
  label?: string;
  name?: string;
  phase?: number | null;
  options?: FormationInstructionOption[];
};

export type FormationPosition = { id: string; mask: number };

export type FormationEditing = {
  duties: string[];
  player_instructions: FormationInstructionGroup[];
  positions: FormationPosition[];
  role_eligibility: Record<string, string[][]>;
  role_eligibility_context: Record<string, Record<string, string[][]>> | null;
};

export type FormationList = {
  formations: Formation[];
  editing: FormationEditing | null;
};

export type FormationApplyInput = {
  formation_id: string;
  overwrite?: boolean;
  scenario?: Record<string, unknown>;
};

export type FormationApplyResult = {
  formation_id: string;
  scenario: Record<string, unknown>;
  notes: string[];
};

export async function listFormations(connection: Connection): Promise<FormationList> {
  return apiJson<FormationList>(connection, "/api/formations");
}

export async function applyFormation(
  connection: Connection,
  draftId: string,
  input: FormationApplyInput,
): Promise<FormationApplyResult> {
  return apiJson<FormationApplyResult>(
    connection,
    `/api/drafts/${encodeURIComponent(draftId)}/formation`,
    { method: "POST", body: JSON.stringify(input) },
  );
}
