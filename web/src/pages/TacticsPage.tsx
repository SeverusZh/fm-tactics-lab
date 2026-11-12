import { SquaresFour } from "@phosphor-icons/react";

import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

export function TacticsPage() {
  return (
    <div className="page-grid">
      <Panel title="双阶段战术板" className="span-7">
        <EmptyState
          icon={SquaresFour}
          title="尚未载入战术"
          description="从默认样本开始，或在存档战术库载入一支球队，再编辑有球与无球阶段。"
          action={
            <button className="button primary" type="button" disabled>
              从默认样本开始
            </button>
          }
        />
      </Panel>
      <Panel title="球队指令" className="span-5">
        <EmptyState
          icon={SquaresFour}
          title="选择球队后编辑"
          description="心态、球队指令、角色职责与个人指令会集中在这里。"
        />
      </Panel>
    </div>
  );
}
