import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { RISK_COPY } from "@/config/constants";
import { formatPercent } from "@/lib/format";

export function RiskPanel({ level, score }: { level: string | null; score: number | null }) {
  if (!level) {
    return (
      <div className="risk-panel neutral">
        <Info size={22} />
        <div>
          <strong>Assessment not ready yet</strong>
          <p>DeepTrace is still preparing the findings for this case.</p>
        </div>
      </div>
    );
  }

  const copy = RISK_COPY[level] || {
    label: level,
    tone: "neutral" as const,
    description: "Review the preserved evidence and findings carefully.",
  };
  const Icon = copy.tone === "danger" || copy.tone === "warning" ? AlertTriangle : CheckCircle2;
  return (
    <div className={`risk-panel ${copy.tone}`}>
      <Icon size={24} />
      <div>
        <div className="risk-heading">
          <strong>{copy.label}</strong>
          <span>{formatPercent(score)}</span>
        </div>
        <p>{copy.description}</p>
      </div>
    </div>
  );
}
