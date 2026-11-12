import { Archive, UploadSimple } from "@phosphor-icons/react";

import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

export function LibraryPage() {
  return (
    <Panel
      title="存档战术库"
      action={
        <button className="button primary" type="button" disabled>
          <UploadSimple size={16} aria-hidden="true" /> 导入存档
        </button>
      }
    >
      <EmptyState
        icon={Archive}
        title="尚未导入存档"
        description="这是唯一的存档导入入口。导入后可以浏览联赛战术、生成真实 AI 计划、导出 FMF 或加入客队战术池。"
      />
    </Panel>
  );
}
