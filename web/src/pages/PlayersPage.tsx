import { useQuery } from "@tanstack/react-query";
import { UsersThree } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import { getDraft, listDrafts } from "../lib/api";

const POSITION_CODES = [
  "GK",
  "SW",
  "DL",
  "DC",
  "DR",
  "DM",
  "ML",
  "MC",
  "MR",
  "AML",
  "AMC",
  "AMR",
  "ST",
  "WBL",
  "WBR",
];

const ATTRIBUTE_LABELS = [
  "门将",
  "旧清道夫位置",
  "左后卫",
  "中后卫",
  "右后卫",
  "后腰",
  "左前卫",
  "中前卫",
  "右前卫",
  "左边锋",
  "前腰",
  "右边锋",
  "中锋",
  "左翼卫",
  "右翼卫",
  "传中",
  "盘带",
  "射门",
  "头球",
  "远射",
  "盯人",
  "无球跑动",
  "传球",
  "点球",
  "抢断",
  "视野",
  "手控球",
  "制空范围",
  "禁区控制",
  "交流",
  "大脚开球",
  "手抛球",
  "预判",
  "决断",
  "一对一",
  "防守站位",
  "反应",
  "停球",
  "技术",
  "左脚",
  "右脚",
  "想象力",
  "角球",
  "团队合作",
  "工作投入",
  "界外球",
  "神经指数",
  "出击",
  "击球倾向",
  "爆发力",
  "任意球",
  "强壮",
  "耐力",
  "速度",
  "弹跳",
  "领导力",
  "肮脏",
  "平衡",
  "勇敢",
  "稳定性",
  "侵略性",
  "灵活",
  "大赛",
  "伤病倾向",
  "多面性",
  "体质",
  "意志力",
  "镇定",
  "集中",
] as const;

type GroupId = "technical" | "mental" | "physical" | "goalkeeping" | "hidden" | "position";

type AttributeGroup = {
  id: GroupId;
  title: string;
  indices: readonly number[];
};

const ATTRIBUTE_GROUPS: readonly AttributeGroup[] = [
  {
    id: "technical",
    title: "技术",
    indices: [15, 16, 17, 18, 19, 20, 22, 23, 24, 37, 38, 42, 45, 50],
  },
  {
    id: "mental",
    title: "精神",
    indices: [21, 25, 32, 33, 35, 41, 43, 44, 55, 58, 60, 66, 67, 68],
  },
  {
    id: "physical",
    title: "身体",
    indices: [49, 51, 52, 53, 54, 57, 61, 65],
  },
  {
    id: "goalkeeping",
    title: "门将",
    indices: [26, 27, 28, 29, 30, 31, 34, 36, 46, 47, 48],
  },
  {
    id: "hidden",
    title: "隐藏",
    indices: [39, 40, 56, 59, 62, 63, 64],
  },
  {
    id: "position",
    title: "位置熟练度",
    indices: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
  },
];

type ScenarioPlayer = {
  uid: string;
  name: string;
  position: number;
  ability: number | null;
  attributes: number[];
};

type ScenarioTeam = {
  name: string | null;
  players: ScenarioPlayer[];
};

type Scenario = {
  teams: [ScenarioTeam, ScenarioTeam];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readAttributes(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 69) return null;
  if (!value.every((item) => typeof item === "number" && Number.isInteger(item))) return null;
  return value;
}

function readAbility(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (isRecord(value) && typeof value.current === "number" && Number.isFinite(value.current)) {
    return value.current;
  }
  return null;
}

function strongestPosition(attributes: number[]): number {
  let best = 0;
  for (let index = 1; index < POSITION_CODES.length; index += 1) {
    if (attributes[index] > attributes[best]) best = index;
  }
  return best;
}

function parsePlayer(value: unknown, index: number): ScenarioPlayer | null {
  if (!isRecord(value)) return null;
  const attributes = readAttributes(value.attributes);
  if (attributes === null) return null;
  const uid = value.source_uid;
  const name =
    typeof value.name === "string" && value.name.trim() !== "" ? value.name.trim() : `球员 ${index + 1}`;
  return {
    uid: typeof uid === "number" || typeof uid === "string" ? String(uid) : `player-${index}`,
    name,
    position: strongestPosition(attributes),
    ability: readAbility(value.ability),
    attributes,
  };
}

function parseTeam(value: unknown): ScenarioTeam | null {
  if (!isRecord(value) || !Array.isArray(value.players) || value.players.length !== 23) {
    return null;
  }
  const players: ScenarioPlayer[] = [];
  for (const [index, entry] of value.players.entries()) {
    const player = parsePlayer(entry, index);
    if (player === null) return null;
    players.push(player);
  }
  const name = typeof value.name === "string" && value.name.trim() !== "" ? value.name.trim() : null;
  return { name, players };
}

function parseScenario(scenario: Record<string, unknown>): Scenario | null {
  const teams = scenario.teams;
  if (!Array.isArray(teams) || teams.length !== 2) return null;
  const home = parseTeam(teams[0]);
  const away = parseTeam(teams[1]);
  if (home === null || away === null) return null;
  return { teams: [home, away] };
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatAbility(value: number | null): string {
  return value === null ? "—" : formatNumber(value);
}

function displayValue(group: GroupId, value: number): string {
  return group === "position" ? String(value) : formatNumber(value / 5);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function PlayersPage() {
  const { connection } = useAppContext();
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [side, setSide] = useState<0 | 1>(0);
  const [selectedPlayer, setSelectedPlayer] = useState(0);
  const [showHidden, setShowHidden] = useState(false);

  const drafts = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null,
  });

  const draftItems = Array.isArray(drafts.data?.items) ? drafts.data.items : [];
  const activeDraftId = draftItems.some((item) => item.id === selectedDraftId)
    ? selectedDraftId
    : (draftItems[0]?.id ?? null);

  const detail = useQuery({
    queryKey: ["draft", connection?.url, activeDraftId],
    queryFn: () => getDraft(connection!, activeDraftId!),
    enabled: connection !== null && activeDraftId !== null,
  });

  const changeDraft = (draftId: string) => {
    setSelectedDraftId(draftId);
    setSelectedPlayer(0);
  };

  const changeSide = (next: 0 | 1) => {
    setSide(next);
    setSelectedPlayer(0);
  };

  const scenario = detail.data === undefined ? null : parseScenario(detail.data.scenario);
  const team = scenario === null ? null : scenario.teams[side];
  const players = team?.players ?? [];
  const playerIndex = selectedPlayer < players.length ? selectedPlayer : 0;
  const player = players[playerIndex];
  const visibleGroups = ATTRIBUTE_GROUPS.filter(
    (group) => group.id !== "hidden" || showHidden,
  );

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={UsersThree}
        title="sidecar 未连接"
        description="连接 sidecar 后可以查看草稿球队的球员名单与属性分组。"
      />
    );
  } else if (drafts.isPending) {
    body = (
      <p className="jobs-loading" role="status">
        正在加载草稿…
      </p>
    );
  } else if (drafts.isError) {
    body = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(drafts.error)}</span>
        <button className="button small" type="button" onClick={() => void drafts.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (draftItems.length === 0) {
    body = (
      <EmptyState
        icon={UsersThree}
        title="暂无草稿"
        description="创建场景草案后，这里会显示主客队各 23 名球员与六组属性。"
      />
    );
  } else {
    let content: ReactNode;
    if (detail.isPending) {
      content = (
        <p className="jobs-loading" role="status">
          正在加载球员属性…
        </p>
      );
    } else if (detail.isError) {
      content = (
        <div className="inline-alert" role="alert">
          <span>{errorMessage(detail.error)}</span>
          <button className="button small" type="button" onClick={() => void detail.refetch()}>
            重试
          </button>
        </div>
      );
    } else if (scenario === null || team === null || player === undefined) {
      content = (
        <div className="inline-alert" role="alert">
          场景数据无效：需要两支球队各 23 名球员与 69 项属性。
        </div>
      );
    } else {
      const selected = player;
      content = (
        <div className="players-layout">
          <aside
            className="players-roster"
            aria-label={`${side === 0 ? "主队" : "客队"}球员名单`}
          >
            <div className="players-list-head" aria-hidden="true">
              <span>球员</span>
              <span>位置</span>
              <span>能力</span>
            </div>
            <ol className="players-list">
              {team.players.map((item, index) => (
                <li key={`${item.uid}-${index}`}>
                  <button
                    className="players-row"
                    type="button"
                    aria-pressed={index === playerIndex}
                    onClick={() => setSelectedPlayer(index)}
                  >
                    <span className="players-row-name">{item.name}</span>
                    <span
                      className="players-row-position"
                      title={ATTRIBUTE_LABELS[item.position]}
                    >
                      {POSITION_CODES[item.position]}
                    </span>
                    <span className="players-row-ability">{formatAbility(item.ability)}</span>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
          <section className="players-detail" aria-label="选中球员属性">
            <div className="players-selected">
              <strong>{selected.name}</strong>
              <span className="badge" title={ATTRIBUTE_LABELS[selected.position]}>
                {POSITION_CODES[selected.position]}
              </span>
              <span className="players-selected-ability">
                <span className="players-ability-label">能力</span>
                {formatAbility(selected.ability)}
              </span>
              {team.name === null ? null : <span className="players-team">{team.name}</span>}
            </div>
            <div className="players-groups">
              {visibleGroups.map((group) => (
                <section
                  className="players-group"
                  key={group.id}
                  aria-labelledby={`players-group-${group.id}`}
                >
                  <h3 id={`players-group-${group.id}`}>{group.title}</h3>
                  <dl className="players-attributes">
                    {group.indices.map((index) => (
                      <div className="players-attribute" key={index}>
                        <dt>{ATTRIBUTE_LABELS[index]}</dt>
                        <dd>{displayValue(group.id, selected.attributes[index])}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}
            </div>
          </section>
        </div>
      );
    }
    body = (
      <>
        <div className="players-toolbar">
          <label className="field players-draft">
            草稿
            <select
              aria-label="选择草稿"
              value={activeDraftId ?? ""}
              onChange={(event) => changeDraft(event.target.value)}
            >
              {draftItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="segmented" role="group" aria-label="球队">
            <button type="button" aria-pressed={side === 0} onClick={() => changeSide(0)}>
              主队
            </button>
            <button type="button" aria-pressed={side === 1} onClick={() => changeSide(1)}>
              客队
            </button>
          </div>
          <label className="field-inline players-hidden-toggle">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => setShowHidden(event.target.checked)}
            />
            显示隐藏属性
          </label>
        </div>
        {content}
      </>
    );
  }

  return <Panel title="球员属性">{body}</Panel>;
}
