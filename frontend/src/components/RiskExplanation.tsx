import { FaFlask as FlaskConical, FaBalanceScale as Scale } from "react-icons/fa";
import { dataOf, nested, num, rows, str } from "@/lib/modules";
import type { InvestigationDetail } from "@/types";

/**
 * Why the case scored what it scored. Every contributing signal is shown with
 * the weight actually applied, and every excluded signal is shown with the
 * reason it was excluded — so the number is auditable rather than opaque.
 */
export function RiskExplanation({ investigation }: { investigation: InvestigationDetail }) {
  const fusion = investigation.analysis_results?.risk_fusion;
  if (!fusion) return null;

  const data = dataOf(investigation, "risk_fusion");
  const signals = rows(data, "signals");
  const excluded = rows(data, "excluded");
  const bands = nested(nested(data, "thresholds"), "risk_bands");

  return (
    <section className="content-card">
      <div className="content-card-heading">
        <div>
          <span>How the score was reached</span>
          <h2>Risk explanation</h2>
        </div>
        <span className="count-badge"><Scale size={13} /> {signals.length} of {signals.length + excluded.length} signals used</span>
      </div>

      <p className="panel-lead">{str(data, "explanation") || "No explanation was recorded for this assessment."}</p>

      {signals.length > 0 && (
        <div className="weight-list">
          {signals.map((signal, index) => {
            const weight = num(signal, "effective_weight") ?? 0;
            const contribution = num(signal, "contribution");
            return (
              <div className="weight-row" key={`${signal.key}-${index}`}>
                <div className="weight-head">
                  <strong>{str(signal, "label") || str(signal, "key") || "Signal"}</strong>
                  <span>{formatWeight(weight)} weight</span>
                </div>
                <span className="weight-bar"><span style={{ width: `${Math.round(weight * 100)}%` }} /></span>
                <small>
                  {str(signal, "detail") || ""}
                  {contribution !== null ? ` Contributed ${contribution.toFixed(3)} to the final score.` : ""}
                </small>
              </div>
            );
          })}
        </div>
      )}

      {excluded.length > 0 && (
        <div className="excluded-list">
          <strong>Signals not included</strong>
          {excluded.map((signal, index) => (
            <div key={`${signal.key}-${index}`}>
              <span>{str(signal, "label") || str(signal, "key")}</span>
              <small>{str(signal, "reason") || "No reason recorded."}</small>
            </div>
          ))}
        </div>
      )}

      <details className="technical-details">
        <summary>Show the formula and thresholds used</summary>
        <div className="kv-grid">
          <div className="kv-row"><span>Formula</span><strong>{str(data, "formula") || "—"}</strong></div>
          <div className="kv-row"><span>Declared weight available</span><strong>{num(data, "total_declared_weight_available")?.toFixed(2) ?? "—"}</strong></div>
          {Object.entries(bands).map(([band, value]) => (
            <div className="kv-row" key={band}><span>{band} band from</span><strong>{String(value)}</strong></div>
          ))}
        </div>
      </details>

      <div className="custody-callout" role="note">
        <FlaskConical size={20} />
        <p>
          <strong>This number is analysis, not preserved fact.</strong> It is a statistical estimate
          with an error rate, recomputed from the preserved original every time the pipeline runs —
          and it can change if the models or weights change. The SHA-256 digests in the evidence
          register are the opposite: arithmetic over bytes, fixed at the moment the file was
          received, and never recalculated by analysis. A score prioritises what to examine; a
          digest establishes which file was examined.
        </p>
      </div>

      <p className="panel-note">
        {str(data, "disclaimer") ||
          "This score is an investigative prioritisation aid derived from forensic indicators. It is not proof of manipulation or of impersonation."}
      </p>
    </section>
  );
}

/**
 * Effective weights are renormalised fractions, so rounding each one to a whole
 * percent can make the displayed set sum to 101%. Keeping a decimal where the
 * value is not whole avoids publishing a total that does not add up.
 */
function formatWeight(weight: number) {
  const percent = weight * 100;
  return `${Math.abs(percent - Math.round(percent)) < 0.05 ? Math.round(percent) : percent.toFixed(1)}%`;
}
