import { FaWaveSquare as AudioLines, FaInfoCircle as Info, FaWaveSquare as Waves } from "react-icons/fa";
import { API_BASE_URL } from "@/config/constants";
import { bool, clock, dataOf, nested, num, rows, str, strings } from "@/lib/modules";
import type { InvestigationDetail } from "@/types";

/** What the badge may claim, given only the module's own status. */
function audioBadge(status: string | undefined) {
  if (status === "completed") return "measured";
  if (status === "not_applicable") return "no audio track";
  if (status === "unavailable") return "not measured";
  if (status === "failed") return "measurement failed";
  return "not run";
}

/**
 * Audio forensics and audio-visual consistency, side by side. Both are
 * deterministic signal measurements rather than model predictions, so the panel
 * states the method plainly and shows the numbers behind each observation.
 */
export function AudioPanel({ investigation }: { investigation: InvestigationDetail }) {
  const audioModule = investigation.analysis_results?.audio;
  const avModule = investigation.analysis_results?.consistency;
  if (!audioModule && !avModule) return null;

  const audio = dataOf(investigation, "audio");
  const av = dataOf(investigation, "consistency");
  const levels = nested(audio, "levels");
  const container = nested(audio, "container");
  const spectral = nested(audio, "spectral");
  const discontinuities = rows(audio, "discontinuities");
  const mismatches = rows(av, "mismatches");
  const duration = nested(av, "duration_agreement");
  const audioTrack = investigation.evidence.find((item) => item.type === "audio");

  return (
    <section className="content-card audio-panel">
      <div className="content-card-heading">
        <div>
          <span>Sound and synchronisation</span>
          <h2>Audio forensics</h2>
        </div>
        <span className="count-badge"><Waves size={13} /> {audioBadge(audioModule?.status)}</span>
      </div>

      {audioModule?.status !== "completed" ? (
        <div className="inline-empty">
          <AudioLines size={19} />
          {str(audio, "reason") || "This media has no analysable audio stream."}
        </div>
      ) : (
        <>
          {audioTrack?.url && (
            <audio controls preload="none" className="audio-player" src={`${API_BASE_URL}${audioTrack.url}`}>
              Your browser cannot play the extracted audio track.
            </audio>
          )}

          <div className="stat-grid">
            <Stat label="Editing indicator" value={num(audio, "editing_indicator")?.toFixed(3) ?? "—"} hint="0 = no discontinuities found" />
            <Stat label="Level discontinuities" value={String(num(audio, "discontinuity_count") ?? 0)} hint={`${num(audio, "discontinuities_per_minute")?.toFixed(2) ?? "—"} per minute`} />
            <Stat label="Peak level" value={num(levels, "peak_dbfs") !== null ? `${num(levels, "peak_dbfs")} dBFS` : "—"} hint={`RMS ${num(levels, "rms_dbfs") ?? "—"} dBFS`} />
            <Stat label="Silence" value={num(levels, "silence_ratio") !== null ? `${Math.round((num(levels, "silence_ratio") as number) * 100)}%` : "—"} hint={`${num(levels, "clipped_samples") ?? 0} clipped samples`} />
            <Stat label="Codec" value={str(container, "codec") || "—"} hint={`${num(container, "sample_rate") ?? "—"} Hz, ${num(container, "channels") ?? "—"} ch`} />
            <Stat label="Spectral centroid" value={num(spectral, "mean_centroid_hz") !== null ? `${num(spectral, "mean_centroid_hz")} Hz` : "—"} hint={`${num(spectral, "windows_analyzed") ?? 0} windows`} />
          </div>

          {discontinuities.length > 0 && (
            <div className="chip-group">
              <strong className="chip-group-label">Abrupt level changes at</strong>
              <div className="chip-row">
                {discontinuities.slice(0, 12).map((item, index) => (
                  <span className="chip" key={`${item.timestamp_seconds}-${index}`}>{clock(num(item, "timestamp_seconds"))}</span>
                ))}
              </div>
            </div>
          )}

          <ObservationList items={strings(audio, "observations")} />
          <p className="panel-note">{str(audio, "interpretation") || ""}</p>
        </>
      )}

      <div className="panel-divider" />

      <div className="content-card-heading tight">
        <div>
          <span>Do picture and sound agree?</span>
          <h2>Audio-video consistency</h2>
        </div>
        {avModule?.status === "completed" && num(av, "consistency_score") !== null && (
          <span className="count-badge">{Math.round((num(av, "consistency_score") as number) * 100)}% aligned</span>
        )}
      </div>

      {avModule?.status !== "completed" ? (
        <div className="inline-empty">
          <AudioLines size={19} />
          {str(av, "reason") || str(av, "details") || "Consistency checking needs both a video track and an audio track."}
        </div>
      ) : (
        <>
          {/* The module decides whether face-vs-audio agreement means anything for
              this media. When it does not, the number is still shown — but not as
              a finding, because low alignment is normal in a voice-over or B-roll. */}
          {bool(av, "alignment_applicable") === false && (
            <div className="scope-note">
              <Info size={17} />
              <p>{str(av, "exclusion_reason") || "This alignment figure was excluded from the risk score."}</p>
            </div>
          )}

          <div className="stat-grid">
            <Stat label="Alignment" value={num(av, "energy_alignment_score")?.toFixed(4) ?? "—"} hint={`${num(av, "samples_agreed") ?? 0} of ${num(av, "samples_compared") ?? 0} timestamps agreed`} />
            <Stat label="Face present" value={num(av, "face_present_ratio") !== null ? `${Math.round((num(av, "face_present_ratio") as number) * 100)}%` : "—"} hint={`${num(av, "faces_detected_total") ?? 0} faces detected`} />
            <Stat label="Mismatched samples" value={String(num(av, "mismatch_count") ?? 0)} hint="face visible but audio silent, or vice versa" />
            <Stat
              label="Stream durations"
              value={num(duration, "delta_seconds") !== null ? `${num(duration, "delta_seconds")}s apart` : "—"}
              hint={duration.mismatch ? "Flagged as disagreeing" : "Within tolerance"}
            />
          </div>

          {mismatches.length > 0 && (
            <div className="mini-table">
              <div className="mini-table-head"><span>Timestamp</span><span>Face</span><span>Audio</span><span>Observation</span></div>
              {mismatches.slice(0, 8).map((item, index) => (
                <div className="mini-table-row" key={`${item.timestamp_seconds}-${index}`}>
                  <span>{clock(num(item, "timestamp_seconds"))}</span>
                  <span>{item.face_present ? "visible" : "absent"}</span>
                  <span>{item.audio_active ? "active" : "near-silent"}</span>
                  <span>{str(item, "observation") || "—"}</span>
                </div>
              ))}
            </div>
          )}

          <ObservationList items={strings(av, "observations")} />
          <p className="panel-note">
            {str(av, "model_status") || ""} {str(av, "warning") || ""}
          </p>
        </>
      )}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat-cell">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function ObservationList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="observation-list">
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}
