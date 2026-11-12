import { ChartBar } from "@phosphor-icons/react";

import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

export function ResultsPage() {
  return (
    <Panel title="实验结果">
      <EmptyState
        icon={ChartBar}
        title="尚无实验结果"
        description="提交实验后，这里会显示批次摘要、A/B 指标、配对差值与逐场记录。"
      />
    </Panel>
  );
}
