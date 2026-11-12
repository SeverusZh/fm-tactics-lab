import { GearSix } from "@phosphor-icons/react";

import { useAppContext } from "../app-context";
import { Panel } from "../components/Panel";

export function SettingsPage() {
  const { connection, health } = useAppContext();
  return (
    <div className="page-grid">
      <Panel title="sidecar" className="span-7">
        <dl className="settings-list">
          <dt>API</dt>
          <dd>{connection?.api ?? "未连接"}</dd>
          <dt>地址</dt>
          <dd>{connection?.url ?? "未连接"}</dd>
          <dt>版本</dt>
          <dd>{health?.version ?? "未知"}</dd>
          <dt>数据库</dt>
          <dd>{health?.database ?? "未知"}</dd>
        </dl>
      </Panel>
      <Panel title="比赛环境" className="span-5">
        <div className="empty-state" style={{ minHeight: 180 }}>
          <GearSix size={28} weight="thin" aria-hidden="true" />
          <p>引擎路径、并发推荐值与语言设置将在后续阶段接入。</p>
        </div>
      </Panel>
    </div>
  );
}
