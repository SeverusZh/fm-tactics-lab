// @vitest-environment node
import { describe, expect, it } from "vitest";
import apiSchemaSource from "./api-schema.ts?raw";
import apiSource from "./api.ts?raw";

type AliasCase = {
  name: string;
  generated: string;
  importAs?: string;
};

const ALIASES: AliasCase[] = [
  { name: "Job", generated: "JobOutput" },
  { name: "JobRun", generated: "JobRunOutput" },
  { name: "JobList", generated: "JobListOutput" },
  { name: "JobRunList", generated: "JobRunListOutput" },
  { name: "JobCreate", generated: "JobCreateInput" },
  { name: "JobUpdate", generated: "JobUpdateInput" },
  { name: "JobMetrics", generated: "JobMetricsOutput" },
  { name: "JobPaired", generated: "PairedOutput" },
  { name: "JobSummary", generated: "ResultsSummaryOutput" },
  { name: "JobBatchDeleteFailure", generated: "JobBatchDeleteFailureOutput" },
  { name: "JobBatchDeleteResult", generated: "JobBatchDeleteOutput" },
  { name: "PoolSummaryEntry", generated: "PoolSummaryEntryOutput" },
  { name: "CompareInput", generated: "CompareInput", importAs: "GeneratedCompareInput" },
  { name: "ComparePairing", generated: "ComparePairingOutput" },
  { name: "CompareJob", generated: "CompareJobOutput" },
  { name: "Save", generated: "SaveOutput" },
  { name: "SaveList", generated: "SaveListOutput" },
  { name: "SaveCreate", generated: "SaveCreateInput" },
  { name: "SaveUpdate", generated: "SaveUpdateInput" },
  { name: "SaveImport", generated: "SaveImportInput" },
  { name: "Draft", generated: "DraftOutput" },
  { name: "DraftSummary", generated: "DraftSummary", importAs: "GeneratedDraftSummary" },
  { name: "DraftList", generated: "DraftListOutput" },
  { name: "DraftCreate", generated: "DraftCreateInput" },
  { name: "DraftUpdate", generated: "DraftUpdateInput" },
  { name: "DraftAttributePayload", generated: "DraftAttributeInput" },
  { name: "DraftAttributeResult", generated: "DraftAttributeOutput" },
  { name: "Setting", generated: "SettingOutput" },
  { name: "SettingList", generated: "SettingListOutput" },
  { name: "SettingInput", generated: "SettingPutInput" },
  { name: "ConcurrencyCheck", generated: "ConcurrencyCheckOutput" },
  { name: "HostResources", generated: "SystemResourcesOutput" },
  {
    name: "ExperimentSubmitInput",
    generated: "ExperimentSubmitInput",
    importAs: "GeneratedExperimentSubmitInput",
  },
  {
    name: "SaveFileImportInput",
    generated: "SaveFileImportInput",
    importAs: "GeneratedSaveFileImportInput",
  },
  { name: "SaveFileImportResult", generated: "SaveFileImportOutput" },
  { name: "FmfFileImportInput", generated: "FmfFileImportInput", importAs: "GeneratedFmfFileImportInput" },
  { name: "ImportedClub", generated: "ImportedClubOutput" },
  { name: "RosterApplyInput", generated: "RosterApplyInput", importAs: "GeneratedRosterApplyInput" },
  { name: "RosterApplyResult", generated: "RosterApplyOutput" },
  { name: "RosterUndoResult", generated: "RosterUndoOutput" },
  { name: "RosterApplied", generated: "RosterAppliedOutput" },
];

const RETAINED: { name: string; declaration: string }[] = [
  { name: "Health", declaration: "export type Health = {" },
  { name: "JobQuery", declaration: "export type JobQuery = {" },
  { name: "JobRunQuery", declaration: "export type JobRunQuery = {" },
  { name: "PoolSummary", declaration: "export type PoolSummary = {" },
  { name: "ComparePaired", declaration: "export type ComparePaired = {" },
  { name: "CompareCandidate", declaration: "export type CompareCandidate = CompareJob & {" },
  { name: "CompareResult", declaration: "export type CompareResult = {" },
  { name: "SaveQuery", declaration: "export type SaveQuery = {" },
  { name: "DraftQuery", declaration: "export type DraftQuery = {" },
  { name: "CatalogOption", declaration: "export type CatalogOption = {" },
  { name: "CatalogPosition", declaration: "export type CatalogPosition = {" },
  { name: "CatalogRole", declaration: "export type CatalogRole = {" },
  { name: "CatalogTeamInstruction", declaration: "export type CatalogTeamInstruction = {" },
  { name: "CatalogMentality", declaration: "export type CatalogMentality = {" },
  { name: "Catalog", declaration: "export type Catalog = {" },
  { name: "CatalogResponse", declaration: "export type CatalogResponse = {" },
  { name: "ConcurrencyCheckQuery", declaration: "export type ConcurrencyCheckQuery = {" },
  { name: "SquadPlayer", declaration: "export type SquadPlayer = {" },
  { name: "SquadSelection", declaration: "export type SquadSelection = {" },
  { name: "SaveSquad", declaration: "export type SaveSquad = {" },
  { name: "DraftAttributeSide", declaration: 'export type DraftAttributeSide = "home" | "away";' },
  {
    name: "DraftAttributeScope",
    declaration:
      'export type DraftAttributeScope = "all" | "starters" | "player" | "squad";',
  },
  {
    name: "DraftAttributeOperation",
    declaration:
      'export type DraftAttributeOperation = "bulk" | "position" | "copy" | "pair_feet" | "undo";',
  },
  { name: "RosterSide", declaration: 'export type RosterSide = "home" | "away";' },
  { name: "RosterScope", declaration: 'export type RosterScope = "starters" | "bench" | "both";' },
];

const RETAINED_CLASS = {
  name: "ApiError",
  declaration: "export class ApiError extends Error {",
};

const DERIVED: { name: string; expression: string }[] = [
  { name: "JobStatus", expression: 'Job["status"]' },
  { name: "SaveStatus", expression: 'Save["status"]' },
];

const SCHEMA_IMPORT = /import\s+type\s+\{([^{}]*)\}\s+from\s+"\.\/api-schema";/g;
const SCHEMA_IMPORT_CLAUSE = /from "\.\/api-schema"/g;

function codeWithoutComments(source: string): string {
  return source
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("//"))
    .join("\n");
}

function schemaImportSpecifierGroups(source: string): string[][] {
  return Array.from(source.matchAll(SCHEMA_IMPORT), (match) => {
    const body = match[1] ?? "";
    return body
      .split(",")
      .map((specifier) => specifier.trim())
      .filter((specifier) => specifier !== "");
  });
}

function apiSchemaImportSpecifiers(source: string): string[] {
  const groups = schemaImportSpecifierGroups(source);
  if (groups.length !== 1) {
    throw new Error(`api.ts 中 from "./api-schema" 的 import 语句数量为 ${groups.length}，期望恰好 1 条`);
  }
  return groups[0] ?? [];
}

function mappedNames(): string[] {
  return [
    ...ALIASES.map(({ name }) => name),
    ...RETAINED.map(({ name }) => name),
    ...DERIVED.map(({ name }) => name),
  ];
}

describe("api.ts 类型映射", () => {
  it("顶部摘要与映射表计数一致", () => {
    const summary = `// API 类型映射：生成别名 ${ALIASES.length} 项；保留手写类型 ${RETAINED.length} 项；字段派生 ${DERIVED.length} 项；ApiError 类保留；明细见 api-types.test.ts。`;
    expect(apiSource.split("\n")[0]).toBe(summary);
    expect(mappedNames()).toHaveLength(68);
    expect(new Set(mappedNames()).size).toBe(68);
    expect(ALIASES).toHaveLength(41);
    expect(RETAINED).toHaveLength(25);
    expect(DERIVED).toHaveLength(2);
  });

  it("每个映射名都是指向生成接口的类型别名", () => {
    const code = codeWithoutComments(apiSource);
    for (const { name, generated, importAs } of ALIASES) {
      const target = importAs ?? generated;
      expect(code, `${name} 应声明为 ${target} 的类型别名`).toContain(
        `export type ${name} = ${target};`,
      );
      expect(code).not.toContain(`export type ${name} = {`);
      expect(code).not.toContain(`export type ${name} = Omit<`);
      expect(apiSchemaSource).toContain(`export interface ${generated} {`);
    }
  });

  it("导入清单恰好覆盖全部生成接口", () => {
    const code = codeWithoutComments(apiSource);
    const clauses = Array.from(code.matchAll(SCHEMA_IMPORT_CLAUSE));
    expect(clauses).toHaveLength(1);
    const groups = schemaImportSpecifierGroups(code);
    expect(groups).toHaveLength(1);
    const actual = apiSchemaImportSpecifiers(code).sort();
    const expected = ALIASES.map(({ generated, importAs }) =>
      importAs === undefined ? generated : `${generated} as ${importAs}`,
    ).sort();
    expect(actual).toEqual(expected);
  });

  it("保留手写类型仍为内联声明", () => {
    const specifiers = apiSchemaImportSpecifiers(codeWithoutComments(apiSource));
    for (const { name, declaration } of RETAINED) {
      expect(apiSource).toContain(declaration);
      expect(apiSource).not.toMatch(new RegExp(`export type ${name} = [A-Za-z_$][\\w$]*;`));
      expect(specifiers.some((specifier) => specifier === name || specifier.endsWith(` as ${name}`))).toBe(
        false,
      );
    }
    expect(apiSource).toContain(RETAINED_CLASS.declaration);
  });

  it("状态类型从响应类型派生", () => {
    for (const { name, expression } of DERIVED) {
      expect(apiSource).toContain(`export type ${name} = ${expression};`);
    }
  });

  it("导出类型清单与映射表完全一致", () => {
    const exported = Array.from(apiSource.matchAll(/^export type (\w+)/gm), (match) => match[1]).sort();
    expect(exported).toEqual(mappedNames().sort());
    expect(apiSource.match(/^export class /gm)).toHaveLength(1);
  });
});
