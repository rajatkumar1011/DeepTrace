import {
  FaCertificate as BadgeCheck,
  FaFileCode as FileCode2,
  FaGlobe as Globe,
  FaInfoCircle as Info,
  FaQuestionCircle as ShieldQuestion,
} from "react-icons/fa";
import { dataOf, nested, num, rows, str, strings } from "@/lib/modules";
import { formatBytes } from "@/lib/format";
import type { InvestigationDetail } from "@/types";

/**
 * Technical attributes and provenance. Absence of Content Credentials is the
 * normal case for social-media media and is reported as such — it is not
 * presented as a suspicious finding.
 */
export function MetadataPanel({ investigation }: { investigation: InvestigationDetail }) {
  const metadataModule = investigation.analysis_results?.metadata;
  const provenanceModule = investigation.analysis_results?.provenance;
  const metadata = dataOf(investigation, "metadata");
  const provenance = dataOf(investigation, "provenance");
  const container = nested(metadata, "container");
  const file = nested(metadata, "file");
  const exif = nested(metadata, "exif");
  const tags = nested(container, "container_tags");
  const credentialsFound = provenance.credentials_found === true;

  return (
    <section className="content-card">
      <div className="content-card-heading">
        <div>
          <span>Technical attributes</span>
          <h2>Metadata and provenance</h2>
        </div>
        <span className="count-badge">
          <FileCode2 size={13} /> {metadata.ffprobe_available === false ? "ffprobe unavailable" : "extracted"}
        </span>
      </div>

      {!metadataModule ? (
        <div className="inline-empty"><FileCode2 size={19} /> Metadata extraction has not run for this case.</div>
      ) : (
        <div className="kv-grid">
          <Row label="Container" value={str(container, "container_long") || str(container, "container")} />
          <Row label="Video codec" value={str(container, "video_codec") ? `${str(container, "video_codec")} ${str(container, "video_profile") || ""}`.trim() : null} />
          <Row label="Pixel format" value={str(container, "pixel_format")} />
          <Row label="Resolution" value={str(container, "resolution") || investigation.resolution} />
          <Row label="Frame rate" value={num(container, "frame_rate") !== null ? `${num(container, "frame_rate")} fps` : null} />
          <Row label="Bitrate" value={num(container, "bitrate_bps") !== null ? `${Math.round((num(container, "bitrate_bps") as number) / 1000)} kbps` : null} />
          <Row label="Audio codec" value={str(container, "audio_codec") ? `${str(container, "audio_codec")} · ${num(container, "audio_sample_rate") ?? "?"} Hz · ${num(container, "audio_channels") ?? "?"} ch` : null} />
          <Row label="Declared encoder" value={str(container, "encoder") || str(tags, "encoder")} />
          <Row label="Container title tag" value={str(tags, "title")} />
          <Row label="File size" value={formatBytes(num(file, "file_size_bytes") ?? investigation.file_size_bytes)} />
          <Row label="MIME type by extension" value={str(file, "mime_type_by_extension")} />
          <Row label="Camera make / model" value={[str(exif, "Make"), str(exif, "Model")].filter(Boolean).join(" ") || null} />
          <Row label="EXIF capture time" value={str(exif, "DateTimeOriginal")} />
        </div>
      )}

      {str(tags, "title") && (
        <p className="panel-note">
          A container tag such as “{str(tags, "title")}” records the tool that last wrote this file. It indicates
          re-encoding, which is also what ordinary sharing and re-uploading produce.
        </p>
      )}

      <div className="panel-divider" />

      <div className="content-card-heading tight">
        <div>
          <span>Content Credentials (C2PA)</span>
          <h2>Provenance</h2>
        </div>
        <span className={`count-badge ${credentialsFound ? "badge-ok" : ""}`}>
          {credentialsFound ? <BadgeCheck size={13} /> : <ShieldQuestion size={13} />}
          {credentialsFound ? " manifest present" : " none present"}
        </span>
      </div>

      <div className="kv-grid">
        <Row label="Status" value={str(provenance, "status") || provenanceModule?.status || "Not run"} />
        <Row label="Method" value={str(provenance, "method")} />
        <Row label="Reader" value={str(provenance, "model_name")} />
        <Row label="Active manifest" value={str(provenance, "active_manifest_label")} />
        <Row label="Signed by" value={str(provenance, "signature_issuer")} />
        <Row label="Claim generator" value={str(provenance, "claim_generator")} />
      </div>

      <p className="panel-note">
        {str(provenance, "note") ||
          "Most media shared on social platforms carries no Content Credentials. Their absence is expected and is not, by itself, an indication of manipulation."}
      </p>

      <div className="panel-divider" />

      <ExternalSources search={nested(provenance, "external_search")} />
    </section>
  );
}

/** What the badge may claim, given only the search's own status. */
function searchBadge(status: string | null, verified: number, discovered: number) {
  if (status === "completed") return `${discovered} found · ${verified} matched`;
  if (status === "no_sources") return "no similar pages returned";
  if (status === "discovered_only") return `${discovered} found · not verified`;
  if (status === "not_configured") return "search key not configured";
  if (status === "failed") return "search failed";
  return "not run";
}

/**
 * Published copies located by reverse-image search, then verified locally.
 *
 * Discovery and verification are shown as separate numbers on purpose. A page
 * returned by the search index is a lead; only a page whose served media matched
 * this file on DeepTrace's own hash and face comparison is reported as a match.
 * Collapsing the two would let an index's guess read as a forensic finding.
 */
function ExternalSources({ search }: { search: Record<string, unknown> }) {
  const status = str(search, "status");
  const sources = rows(search, "sources");
  const discovered = num(search, "sources_discovered") ?? 0;
  const verified = num(search, "sources_verified") ?? 0;

  return (
    <>
      <div className="content-card-heading tight">
        <div>
          <span>Where else has this media been published?</span>
          <h2>Located sources</h2>
        </div>
        <span className={`count-badge ${verified > 0 ? "badge-ok" : ""}`}>
          <Globe size={13} /> {searchBadge(status, verified, discovered)}
        </span>
      </div>

      <div className="scope-note">
        <Info size={17} />
        <p>
          {str(search, "scope") ||
            "Reverse-image lookup through one third-party index, followed by local verification of the media each candidate page actually serves. This is not an internet-wide search, and no private or authenticated endpoint is accessed."}
        </p>
      </div>

      {sources.length === 0 ? (
        <div className="inline-empty">
          <Globe size={19} />
          {str(search, "reason") || "No external source search has run for this case."}
        </div>
      ) : (
        <div className="mini-table">
          <div className="mini-table-head"><span>Source</span><span>Result</span><span>Similarity</span><span>First archived</span></div>
          {sources.map((source, index) => {
            const url = str(source, "url");
            const sourceStatus = str(source, "status") || "unknown";
            const matched = sourceStatus === "provenance_candidate";
            const media = num(source, "media_score");
            const face = num(source, "face_similarity");
            const estimate = nested(source, "provenance_estimate");
            return (
              <div key={`${url}-${index}`}>
                <div className="mini-table-row">
                  <span title={url || undefined}>
                    {url ? (
                      // rel=noreferrer: opening an investigator's case in a new tab
                      // must not hand the target a referrer describing this tool.
                      <a href={url} target="_blank" rel="noopener noreferrer nofollow">
                        {str(source, "title") || hostOf(url)}
                      </a>
                    ) : "Unnamed source"}
                  </span>
                  <span className={`verdict verdict-${matched ? "ok" : sourceStatus === "no_match" ? "muted" : "warn"}`}>
                    {SOURCE_RESULTS[sourceStatus] || sourceStatus}
                  </span>
                  <span>{media !== null ? media.toFixed(3) : "—"}</span>
                  <span>{formatArchiveStamp(str(source, "first_observed"))}</span>
                </div>
                <div className="mini-table-note">
                  <span className="note-muted">
                    {str(source, "platform") || "Web"}
                    {url ? ` · ${url}` : ""}
                  </span>
                  {/* A thumbnail match means the page advertises this frame, not
                      that it serves this video. The distinction is the finding. */}
                  {matched && (
                    <span>
                      Matched on {str(source, "verified_on") || "retrieved media"}
                      {face !== null ? ` · face similarity ${face.toFixed(3)}` : ""}
                      {str(source, "classification") ? ` · ${str(source, "classification")?.toLowerCase().replace(/_/g, " ")}` : ""}
                    </span>
                  )}
                  {!matched && str(source, "reason") && <span>{str(source, "reason")}</span>}
                  {num(source, "frame_occurrence_count") !== null && (
                    <span className="note-muted">
                      Returned for {num(source, "frame_occurrence_count")} of the sampled query frame(s)
                      {num(estimate, "confidence_score") !== null
                        ? ` · lead confidence ${num(estimate, "confidence_score")} (ranking score, not a probability)`
                        : ""}
                    </span>
                  )}
                  {str(source, "published_at") && (
                    <span className="note-muted">
                      Page reports publication {str(source, "published_at")}
                      {str(source, "uploader") ? ` by ${str(source, "uploader")}` : ""}
                      {str(source, "metadata_source") ? ` (${str(source, "metadata_source")})` : ""}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {str(search, "interpretation") && <p className="panel-note">{str(search, "interpretation")}</p>}

      <div className="kv-grid">
        <Row label="Search engine" value={str(search, "engine")} />
        <Row label="Query frames" value={num(search, "frames_searched")} />
        <Row label="Raw index matches" value={num(search, "raw_match_count")} />
        <Row label="Pages verified locally" value={num(search, "sources_checked")} />
        <Row label="Could not be retrieved" value={num(search, "sources_unreachable")} />
        <Row label="Candidate video download" value={str(search, "candidate_video_download")} />
      </div>

      {str(search, "verification_method") && <p className="panel-note">{str(search, "verification_method")}</p>}

      {strings(search, "limitations").length > 0 && (
        <ul className="observation-list">
          {strings(search, "limitations").map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </>
  );
}

/** Backend status → what the row is allowed to say happened. */
const SOURCE_RESULTS: Record<string, string> = {
  provenance_candidate: "media matched",
  no_match: "below threshold",
  unverified: "media not retrievable",
  unreachable: "page unreachable",
  refused: "refused by URL policy",
  not_checked: "not verified this run",
  not_verified: "discovered only",
  error: "verification error",
};

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Wayback CDX stamps are YYYYMMDDhhmmss, which is unreadable as-is. */
function formatArchiveStamp(stamp: string | null) {
  if (!stamp) return "—";
  const match = /^(\d{4})(\d{2})(\d{2})/.exec(stamp);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : stamp;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  const shown = value === null || value === undefined || value === "" ? "Not recorded" : String(value);
  return (
    <div className="kv-row">
      <span>{label}</span>
      <strong className={shown === "Not recorded" ? "kv-absent" : undefined}>{shown}</strong>
    </div>
  );
}
