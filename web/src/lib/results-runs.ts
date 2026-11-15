import type { Job, JobRun, PoolSummaryEntry } from "./api";

export type TeamStats = {
  side: number;
  xg: number | null;
  possession: number | null;
  shots: number | null;
  shotsOnTarget: number | null;
  passes: number | null;
  completedPasses: number | null;
};

export type RunDraw = {
  index: number;
  name: string | null;
  weight: number | null;
  probability: number | null;
};

export type RunEvents = {
  collected: boolean;
  goals: number;
  cards: number;
  reason: string | null;
};

function recordOf(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function runTeams(stats: JobRun["stats"]): TeamStats[] {
  const record = recordOf(stats);
  const teams = record === null ? null : record.teams;
  if (!Array.isArray(teams)) return [];
  const parsed: TeamStats[] = [];
  for (const entry of teams) {
    const team = recordOf(entry);
    if (team === null) continue;
    const side = numberValue(team.side);
    if (side === null) continue;
    parsed.push({
      side,
      xg: numberValue(team.xg),
      possession: numberValue(team.possession),
      shots: numberValue(team.shots),
      shotsOnTarget: numberValue(team.shots_on_target),
      passes: numberValue(team.passes),
      completedPasses: numberValue(team.completed_passes),
    });
  }
  return parsed;
}

export function runDraw(stats: JobRun["stats"]): RunDraw | null {
  const record = recordOf(stats);
  const raw = record === null ? null : record.tactic_pool_entry;
  if (raw === null || raw === undefined) return null;
  if (typeof raw === "number") {
    if (!Number.isInteger(raw)) return null;
    return { index: raw, name: null, weight: null, probability: null };
  }
  const draw = recordOf(raw);
  if (draw === null) return null;
  const index = numberValue(draw.index);
  if (index === null) return null;
  return {
    index,
    name: stringValue(draw.name),
    weight: numberValue(draw.weight),
    probability: numberValue(draw.probability),
  };
}

export function runEvents(events: JobRun["events"]): RunEvents | null {
  const record = recordOf(events);
  if (record === null) return null;
  return {
    collected: record.collected === true,
    goals: Array.isArray(record.goals) ? record.goals.length : 0,
    cards: Array.isArray(record.cards) ? record.cards.length : 0,
    reason: stringValue(record.reason),
  };
}

export function drawText(draw: RunDraw, entries: PoolSummaryEntry[] | null): string {
  if (draw.name !== null) return draw.name;
  const match = entries === null ? undefined : entries.find((entry) => entry.index === draw.index);
  if (match !== undefined) return match.name;
  return `索引 ${draw.index}`;
}

export function formatPossession(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function jobFailureReason(job: Job): string | null {
  if (job.status !== "error") return null;
  const summary = recordOf(job.summary);
  return summary === null ? null : stringValue(summary.error);
}
