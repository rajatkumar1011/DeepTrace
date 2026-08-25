"use client";

import { AlertTriangle, GitCompareArrows, Link2, LoaderCircle, Upload } from "lucide-react";
import { useState } from "react";
import { ACCEPTED_MEDIA } from "@/config/constants";
import { getApiError } from "@/lib/api/client";
import { addTraceSource } from "@/lib/api/deeptrace";
import { formatBytes, shortHash } from "@/lib/format";
import { dataOf, num, rows, str } from "@/lib/modules";
import type { InvestigationDetail, TraceSource } from "@/types";

/**
 * Copy tracing. Two truthful inputs only: a public HTTPS URL DeepTrace fetches
 * itself, or a copy the investigator already holds. There is no internet-wide
 * search, no private API access and no authentication bypass — the panel states
 * that scope on screen so the capability is never overstated in a demo.
 */
export function TracePanel({
  investigation,
  onChanged,
}: {
  investigation: InvestigationDetail;
  onChanged: () => void;
}) {
  const [url, setUrl] = useState("");
  const [copy, setCopy] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const sources = investigation.trace_sources || [];
  const similarity = dataOf(investigation, "similarity");
  const localMatches = rows(similarity, "matches");

  const submit = async () => {
    if (!url.trim() && !copy) {
      setError("Add a public HTTPS URL or choose a copy of the file to compare.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await addTraceSource(investigation.id, { sourceUrls: url, localCopy: copy, label });
      const rejected = result.sources.filter((item) => item.retrieval_status === "rejected");
      setNotice(
        rejected.length > 0
          ? `${result.processed} source(s) processed. ${rejected.length} was refused: ${rejected[0].retrieval_error || "target not permitted"}`
          : `${result.processed} source(s) processed and compared.`,
      );
      setUrl("");
      setCopy(null);
      setLabel("");
      onChanged();
    } catch (traceError) {
      setError(getApiError(traceError, "The source could not be traced."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="content-card">
      <div className="content-card-heading">
        <div>
          <span>Where else has this appeared?</span>
          <h2>Copy tracing</h2>
        </div>
        <span className="count-badge"><GitCompareArrows size={13} /> {sources.length} source(s)</span>
      </div>

      <div className="scope-note">
        <Link2 size={17} />
        <p>
          DeepTrace compares copies you point it at. It retrieves only the specific public HTTPS URLs you supply, and it
          does not search the internet, access private or authenticated APIs, or bypass any access control.
        </p>
      </div>

      <div className="trace-form">
        <div className="form-field">
          <label htmlFor="trace-url">Public HTTPS URL of a copy</label>
          <input
            id="trace-url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/path/to/media.jpg"
            inputMode="url"
          />
          <small>One per line. Loopback, private-network and non-HTTPS targets are refused by the server.</small>
        </div>
        <div className="form-field">
          <label htmlFor="trace-copy">Or a copy you already have</label>
          <div className="compact-file-input">
            <input id="trace-copy" type="file" accept={ACCEPTED_MEDIA.suspicious} onChange={(event) => setCopy(event.target.files?.[0] || null)} />
          </div>
          <small>{copy ? `${copy.name} · ${formatBytes(copy.size)}` : "For example a copy someone forwarded to you."}</small>
        </div>
        <div className="form-field">
          <label htmlFor="trace-label">Label (optional)</label>
          <input id="trace-label" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Where it came from" />
        </div>
        <button className="btn btn-primary" onClick={submit} disabled={busy}>
          {busy ? <><LoaderCircle className="spin" size={16} /> Comparing…</> : <><Upload size={16} /> Trace and compare</>}
        </button>
      </div>

      {error && <div className="form-alert"><AlertTriangle size={18} /><span>{error}</span></div>}
      {notice && <div className="form-notice">{notice}</div>}

      {sources.length > 0 && (
        <div className="mini-table">
          <div className="mini-table-head"><span>Source</span><span>Retrieval</span><span>Similarity</span><span>Digest</span></div>
          {sources.map((source) => (
            <div className="mini-table-row" key={source.id}>
              <span title={source.source_url || undefined}>{describeSource(source)}</span>
              <span className={`verdict verdict-${source.retrieval_status === "fetched" ? "ok" : source.retrieval_status === "rejected" ? "warn" : "muted"}`}>
                {source.retrieval_status || "unknown"}
                {source.retrieval_error ? ` — ${source.retrieval_error}` : ""}
              </span>
              <span>{source.similarity_label || (source.similarity !== null ? source.similarity.toFixed(3) : "—")}</span>
              <span><code>{shortHash(source.sha256)}</code></span>
            </div>
          ))}
        </div>
      )}

      <div className="panel-divider" />

      <div className="content-card-heading tight">
        <div>
          <span>Already preserved locally</span>
          <h2>Matches in this DeepTrace instance</h2>
        </div>
        <span className="count-badge">{num(similarity, "match_count") ?? 0} match(es)</span>
      </div>

      {localMatches.length === 0 ? (
        <div className="inline-empty">
          <GitCompareArrows size={19} />
          {str(similarity, "summary") || "No matching or visually similar media was found in the local evidence index."}
        </div>
      ) : (
        <div className="mini-table">
          <div className="mini-table-head"><span>Case</span><span>Relationship</span><span>Similarity</span><span>Basis</span></div>
          {localMatches.slice(0, 12).map((match, index) => (
            <div className="mini-table-row" key={`${match.matched_investigation_id}-${index}`}>
              <span title={str(match, "matched_investigation_filename") || undefined}>
                {num(match, "matched_investigation_id") !== null ? `Case #${num(match, "matched_investigation_id")}` : "Unknown case"}
              </span>
              <span>{str(match, "similarity_label") || str(match, "match_type") || "—"}</span>
              <span>{num(match, "similarity")?.toFixed(3) ?? "—"}</span>
              <span>{str(match, "basis") || "—"}</span>
            </div>
          ))}
        </div>
      )}

      <p className="panel-note">
        {str(similarity, "scope") || "Local evidence index only — the media preserved by this DeepTrace installation."}
      </p>
    </section>
  );
}

function describeSource(source: TraceSource) {
  if (source.origin === "local_copy") return source.title || "Investigator-supplied copy";
  return source.source_url || source.title || "Unnamed source";
}
