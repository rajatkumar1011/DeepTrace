"use client";

import {
  FaExclamationTriangle as AlertTriangle,
  FaCertificate as BadgeCheck,
  FaFingerprint as Fingerprint,
  FaLink as Link2,
  FaSpinner as LoaderCircle,
  FaScroll as ScrollText,
  FaQuestionCircle as ShieldQuestion,
  FaMagic as Sparkles,
  FaUserCheck as UserCheck,
  FaTimesCircle as XCircle,
} from "react-icons/fa";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getApiError } from "@/lib/api/client";
import { getCustodyRecord } from "@/lib/api/deeptrace";
import { formatBytes, formatDate, shortHash } from "@/lib/format";
import type { CustodyClaim, CustodyRecord } from "@/types";

/**
 * The chain-of-custody record, and the boundary the evaluators asked us to draw.
 *
 * Two things are deliberately load-bearing here. First, the panel opens by
 * defining what a complete chain of custody actually requires and stating which
 * half DeepTrace can evidence — because it records no custodian, calling this a
 * finished chain would be the overclaim. Second, hashing and analysis are shown
 * side by side with their own "does not prove" column, because conflating the
 * arithmetic certainty of a digest with the statistical estimate of a model is
 * the usual route to an overstated forensic conclusion.
 *
 * Every string is served by the backend rather than written here, so the screen
 * and the exported PDF cannot drift apart.
 */
export function CustodyPanel({ investigationId }: { investigationId: number }) {
  const [record, setRecord] = useState<CustodyRecord | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRecord(await getCustodyRecord(investigationId));
    } catch (loadError) {
      setError(getApiError(loadError, "The custody record could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) {
    return (
      <section className="content-card">
        <div className="inline-empty">
          <LoaderCircle className="spin" size={19} /> Assembling the custody record…
        </div>
      </section>
    );
  }

  if (error || !record) {
    return (
      <section className="content-card">
        <div className="form-alert">
          <AlertTriangle size={18} />
          <span>{error || "No custody record is available for this case."}</span>
        </div>
        <button className="btn btn-secondary" onClick={() => void load()}>Try again</button>
      </section>
    );
  }

  const { custody_scope: scope, acquisition, counts, integrity_check: check } = record;

  return (
    <section className="content-card">
      <div className="content-card-heading">
        <div>
          <span>For the investigating officer</span>
          <h2>Chain of custody</h2>
        </div>
        <span className="count-badge"><Link2 size={13} /> {counts.artifacts} artifacts</span>
      </div>

      <p className="panel-lead">{scope.definition}</p>

      <div className="custody-scope">
        <div className="custody-scope-half">
          <strong><BadgeCheck size={15} /> What DeepTrace records</strong>
          <ul>{scope.deeptrace_supplies.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
        <div className="custody-scope-half muted">
          <strong><UserCheck size={15} /> What the investigating officer supplies</strong>
          <ul>{scope.investigator_supplies.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      </div>

      <div className="custody-callout" role="note">
        <ShieldQuestion size={20} />
        <p>{scope.statement}</p>
      </div>

      <div className="panel-divider" />

      <h3 className="custody-subhead"><Fingerprint size={15} /> Acquisition</h3>
      <div className="kv-grid">
        <Row label="Case reference" value={acquisition.case_reference} />
        <Row label="Item acquired" value={acquisition.submitted_filename || "Not recorded"} />
        <Row label="Acquired at" value={formatDate(acquisition.received_at)} />
        <Row
          label={`${acquisition.algorithm} digest`}
          value={<code title={acquisition.sha256 || undefined}>{shortHash(acquisition.sha256)}</code>}
        />
        <Row label="Size at acquisition"
             value={acquisition.file_size_bytes !== null
               ? `${formatBytes(acquisition.file_size_bytes)} (${acquisition.file_size_bytes} bytes)`
               : "Not recorded"} />
      </div>
      <details className="technical-details">
        <summary>How that digest is bound to this file, and what the record does not fix</summary>
        <div className="kv-grid">
          <Row label="Digest binding" value={acquisition.hash_binding} />
          <Row label="Derived files" value={acquisition.derived_hash_binding} />
          <Row label="Media type" value={acquisition.type_determination} />
          <Row label="Stored filename" value={acquisition.filename_note} />
          <Row label="Time source" value={acquisition.clock_source} />
        </div>
      </details>

      <div className="panel-divider" />

      <h3 className="custody-subhead"><Link2 size={15} /> Artifact lineage</h3>
      <p className="panel-lead">
        {counts.acquired} acquired · {counts.derived} derived from the original ·{" "}
        {counts.without_digest} without a recorded digest
      </p>
      <div className="mini-table custody-ledger">
        <div className="mini-table-head">
          <span>ID</span><span>Role in the chain</span><span>Preserved</span><span>Digest</span>
        </div>
        {record.artifact_ledger.slice(0, 40).map((entry) => (
          <div className="mini-table-row" key={entry.evidence_id}>
            <span>{entry.evidence_id}</span>
            <span title={entry.role_detail}>{entry.role}</span>
            <span>{formatDate(entry.preserved_at)}</span>
            <span>
              {entry.digest_recorded
                ? <code title={entry.sha256 || undefined}>{shortHash(entry.sha256)}</code>
                : <span className="verdict verdict-muted">Not recorded</span>}
            </span>
          </div>
        ))}
      </div>
      {record.artifact_ledger.length > 40 && (
        <p className="panel-note">
          Showing the first 40 of {record.artifact_ledger.length}. The exported PDF lists every one.
        </p>
      )}
      <p className="panel-note">{record.derivation_note}</p>

      <div className="panel-divider" />

      <h3 className="custody-subhead"><ScrollText size={15} /> Recorded sequence</h3>
      {check.verified_at && (
        <div className="kv-grid">
          <Row label="Events recorded in order" value={`${record.chronology.length}`} />
          <Row label="Digests last re-checked" value={formatDate(check.verified_at)} />
          <Row label="Re-check result" value={check.summary || "Not recorded"} />
        </div>
      )}
      <p className="panel-note">{record.chronology_note}</p>

      <div className="panel-divider" />

      <h3 className="custody-subhead"><Sparkles size={15} /> What proves what</h3>
      <p className="panel-lead">{record.boundary_summary}</p>

      <div className="proof-split">
        <ClaimColumn
          tone="ok"
          heading={`${acquisition.algorithm} hashing proves`}
          claims={record.hashing_proves}
        />
        <ClaimColumn
          tone="bad"
          heading={`${acquisition.algorithm} hashing does not prove`}
          claims={record.hashing_does_not_prove}
        />
        <ClaimColumn
          tone="ok"
          heading="The AI analysis establishes"
          claims={record.ai_establishes}
        />
        <ClaimColumn
          tone="bad"
          heading="The AI analysis does not establish"
          claims={record.ai_does_not_establish}
        />
      </div>

      <div className="panel-divider" />

      <h3 className="custody-subhead"><AlertTriangle size={15} /> Where this record stops</h3>
      <div className="excluded-list">
        {record.custody_gaps.map((gap) => (
          <div key={gap.gap}>
            <span>{gap.gap}</span>
            <small>{gap.detail}</small>
          </div>
        ))}
      </div>
      {check.limitations && <p className="panel-note">{check.limitations}</p>}
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return <div className="kv-row"><span>{label}</span><strong>{value}</strong></div>;
}

function ClaimColumn({
  heading,
  claims,
  tone,
}: {
  heading: string;
  claims: CustodyClaim[];
  tone: "ok" | "bad";
}) {
  const Icon = tone === "ok" ? BadgeCheck : XCircle;
  return (
    <div className={`proof-column proof-${tone}`}>
      <strong><Icon size={15} /> {heading}</strong>
      <ul>
        {claims.map((claim) => (
          <li key={claim.claim}>
            <span>{claim.claim}</span>
            <small>{claim.detail}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}
