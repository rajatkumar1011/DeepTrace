"use client";

import {
  FaExclamationTriangle as AlertTriangle,
  FaFileAlt as FileCheck2,
  FaSpinner as LoaderCircle,
  FaShieldAlt as ShieldCheck,
} from "react-icons/fa";
import { useState } from "react";
import { INTEGRITY_COPY } from "@/config/constants";
import { getApiError } from "@/lib/api/client";
import { verifyEvidence } from "@/lib/api/deeptrace";
import { formatDate, shortHash } from "@/lib/format";
import { clock } from "@/lib/modules";
import type { EvidenceItem, IntegrityReport } from "@/types";

/**
 * The preserved-artifact register plus on-demand integrity re-verification.
 *
 * Verification is deliberately a user-triggered action rather than a cached
 * value: it re-reads every file from disk and re-hashes it, so the result is
 * only meaningful at the moment it is run.
 */
export function IntegrityPanel({ investigationId, evidence }: { investigationId: number; evidence: EvidenceItem[] }) {
  const [report, setReport] = useState<IntegrityReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const runVerification = async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await verifyEvidence(investigationId));
    } catch (verifyError) {
      setError(getApiError(verifyError, "Integrity verification could not be completed."));
    } finally {
      setBusy(false);
    }
  };

  const grouped = evidence.reduce<Record<string, EvidenceItem[]>>((accumulator, item) => {
    (accumulator[item.type] ||= []).push(item);
    return accumulator;
  }, {});

  return (
    <section className="content-card">
      <div className="content-card-heading">
        <div>
          <span>Preserved artifacts</span>
          <h2>Evidence register and integrity</h2>
        </div>
        <span className="count-badge">{evidence.length} items</span>
      </div>

      {evidence.length === 0 ? (
        <div className="inline-empty"><FileCheck2 size={19} /> No evidence artifacts have been preserved yet.</div>
      ) : (
        <>
          <div className="chip-row">
            {Object.entries(grouped).map(([type, items]) => (
              <span className="chip" key={type}>{items.length} {type}{items.length === 1 ? "" : "s"}</span>
            ))}
          </div>

          <div className="evidence-list">
            {evidence.slice(0, 30).map((item) => (
              <div className="evidence-row" key={item.id}>
                <span className="evidence-icon"><FileCheck2 size={19} /></span>
                <div>
                  <strong>{describeEvidence(item.type)}</strong>
                  <small>
                    {item.filename}
                    {item.timestamp_offset !== null ? ` · at ${clock(item.timestamp_offset)}` : ""}
                  </small>
                </div>
                <code title={item.sha256 || undefined}>{shortHash(item.sha256)}</code>
              </div>
            ))}
          </div>
          {evidence.length > 30 && (
            <p className="panel-note">
              Showing the first 30 of {evidence.length} artifacts. The generated PDF report lists every one with its full digest.
            </p>
          )}
        </>
      )}

      <div className="panel-divider" />

      <div className="verify-bar">
        <div>
          <strong>Re-verify the preserved evidence</strong>
          <p>Each file is re-read from disk, re-hashed with SHA-256 and compared against the digest recorded when it was preserved.</p>
        </div>
        <button className="btn btn-secondary" onClick={runVerification} disabled={busy || evidence.length === 0}>
          {busy ? <><LoaderCircle className="spin" size={16} /> Verifying…</> : <><ShieldCheck size={16} /> Run verification</>}
        </button>
      </div>

      <p className="panel-note">
        This check answers one question: do the preserved files still match the digests recorded for
        them? It says nothing about whether the content is genuine or manipulated — that is a
        separate question, answered by the analysis modules with a probability rather than a
        match. The Chain of custody panel above sets out the boundary in full.
      </p>

      {error && <div className="form-alert"><AlertTriangle size={18} /><span>{error}</span></div>}

      {report && (
        <>
          <div className={`verify-result ${report.chain_intact ? "ok" : "bad"}`} role="status">
            {report.chain_intact ? <ShieldCheck size={22} /> : <AlertTriangle size={22} />}
            <div>
              <strong>{report.summary}</strong>
              <p>
                {report.counts.verified} verified · {report.counts.mismatch} mismatch · {report.counts.missing} missing ·{" "}
                {report.counts.no_recorded_hash} without a recorded hash · checked {formatDate(report.verified_at)}
              </p>
            </div>
          </div>

          <details className="technical-details" open={!report.chain_intact}>
            <summary>Show each artifact&rsquo;s verification result</summary>
            <div className="mini-table">
              <div className="mini-table-head"><span>Artifact</span><span>Result</span><span>Recorded digest</span><span>Detail</span></div>
              {report.artifacts.map((artifact) => {
                const copy = INTEGRITY_COPY[artifact.status] || { label: artifact.status, tone: "muted" as const };
                return (
                  <div className="mini-table-row" key={artifact.evidence_id}>
                    <span>{artifact.label}</span>
                    <span className={`verdict verdict-${copy.tone}`} title={VERDICT_TOOLTIPS[artifact.status] || artifact.detail}>
                      {copy.label}
                    </span>
                    <span><code>{shortHash(artifact.recorded_sha256)}</code></span>
                    <span>{artifact.detail}</span>
                  </div>
                );
              })}
            </div>
          </details>

          <p className="panel-note">{report.limitations}</p>
        </>
      )}
    </section>
  );
}

/**
 * What each verdict actually licenses you to say. Kept as tooltips rather than
 * body text because they are precise enough to be long, and a reader only needs
 * them for the row they are looking at.
 */
const VERDICT_TOOLTIPS: Record<string, string> = {
  verified:
    "The file's current bytes hash to the digest recorded for it. This detects corruption, truncation, re-encoding and edits made to the file alone — it cannot detect a change made to both the file and its stored digest.",
  mismatch:
    "The file's current bytes do not hash to the recorded digest, so the file has changed since it was preserved. The mismatch is reported, never repaired.",
  missing:
    "The recorded file could not be read from disk, so nothing could be compared. This is reported as unverifiable, not as verified.",
  no_recorded_hash:
    "No digest was recorded when this artifact was preserved, so there is nothing to compare against. It stays in the register marked unverifiable.",
};

function describeEvidence(type: string) {
  const labels: Record<string, string> = {
    original: "Original submitted media",
    frame: "Sampled video frame",
    localization: "Manipulation overlay",
    audio: "Extracted audio track",
    traced_copy: "Traced external copy",
  };
  return labels[type] || type;
}
