import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: IconComponent,
  title,
  description,
  action,
}: {
  icon: Icon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <IconComponent size={30} weight="thin" aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}
