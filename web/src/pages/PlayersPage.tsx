import { UsersThree } from "@phosphor-icons/react";

import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

export function PlayersPage() {
  return (
    <Panel title="球员属性">
      <EmptyState
        icon={UsersThree}
        title="尚未载入球队"
        description="载入默认样本、存档球队或完整方案后，在这里查看技术、精神、身体、门将与隐藏属性。"
      />
    </Panel>
  );
}
