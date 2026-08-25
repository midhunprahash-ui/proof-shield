import type { ReactNode } from "react";

export type StatusTone = "blue" | "danger" | "good" | "muted" | "warning";

export function StatusBadge({
  children,
  dot = true,
  tone = "muted",
}: {
  children: ReactNode;
  dot?: boolean;
  tone?: StatusTone;
}) {
  return (
    <span className={`status-badge status-${tone}`}>
      {dot ? <span aria-hidden="true" className="status-dot" /> : null}
      {children}
    </span>
  );
}
