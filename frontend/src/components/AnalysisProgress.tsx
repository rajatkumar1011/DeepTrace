import { AlertCircle, LoaderCircle } from "lucide-react";
import type { InvestigationDetail } from "@/types";

/**
 * Live pipeline progress, read from the values the backend actually writes
 * between stages (`progress_stage` / `progress_percent`) rather than an
 * animation that only looks like progress.
 */
export function AnalysisProgress({ investigation }: { investigation: InvestigationDetail }) {
  if (investigation.status === "failed") {
    return (
      <div className="analysis-progress failed" role="alert">
        <AlertCircle size={22} />
        <div>
          <strong>Analysis stopped before it finished.</strong>
          <p>{investigation.error_message || "The backend reported an error. The preserved evidence and its hash are unaffected."}</p>
          {investigation.progress_stage && <p>Last stage reached: {investigation.progress_stage}</p>}
        </div>
      </div>
    );
  }

  if (investigation.status !== "analyzing") return null;

  const percent = Math.max(0, Math.min(100, investigation.progress_percent ?? 0));
  return (
    <div className="analysis-progress" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={22} />
      <div>
        <strong>{investigation.progress_stage || "Preparing analysis"}</strong>
        <p>Findings refresh automatically. You can stay on this page.</p>
        <div className="progress-track" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
      <span className="progress-figure">{percent}%</span>
    </div>
  );
}
