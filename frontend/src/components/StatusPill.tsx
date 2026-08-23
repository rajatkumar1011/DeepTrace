export function StatusPill({ status }: { status: string }) {
  const normalized = status?.toLowerCase() || "pending";
  const label: Record<string, string> = {
    pending: "Evidence received",
    analyzing: "Analysis in progress",
    completed: "Ready to review",
    failed: "Needs attention",
  };
  return <span className={`status-pill status-${normalized}`}>{label[normalized] || status}</span>;
}
