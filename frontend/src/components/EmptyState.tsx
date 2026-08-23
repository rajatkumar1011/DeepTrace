import { FileSearch } from "lucide-react";

export function EmptyState({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><FileSearch size={28} /></span>
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </div>
  );
}
