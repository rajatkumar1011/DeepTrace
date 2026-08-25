import { BadgeCheck, FileCode2, ShieldQuestion } from "lucide-react";
import { dataOf, nested, num, str } from "@/lib/modules";
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
    </section>
  );
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
