"use client";

import {
  FaExclamationTriangle as AlertTriangle,
  FaChartBar as BarChart3,
  FaQuestionCircle as CircleHelp,
  FaFlask as FlaskConical,
  FaTachometerAlt as Gauge,
  FaSpinner as LoaderCircle,
  FaShieldAlt as ShieldAlert,
  FaBullseye as Target,
  FaUserCheck as UserCheck,
} from "react-icons/fa";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getApiError } from "@/lib/api/client";
import { getBenchmark } from "@/lib/api/deeptrace";
import { formatDate } from "@/lib/format";
import type {
  BenchmarkPayload,
  ConfusionPoint,
  DatasetProvenance,
  FamilyBreakdown,
  HarnessCommands,
  IdentityMetrics,
  IdentityPairProvenance,
  RobustnessChannel,
  RobustnessPayload,
} from "@/types";

/**
 * How DeepTrace's own reliability is reported to a reviewer.
 *
 * The panel is built around a distinction the evaluators asked us to make
 * explicit, and everything here follows from it: labelled metrics say how often
 * the detector is *right*, robustness says how far its score *moves* when the
 * same file is degraded. They need different inputs, fail independently, and are
 * therefore rendered as separate blocks that each state their own absence.
 *
 * The labelled half is split again, into identity matching and manipulation
 * detection, because on this project's corpora those two produce opposite
 * results. Showing one number for "accuracy" would average a strong layer
 * together with a failing one and describe neither.
 *
 * Nothing on this screen is a constant. Every number is read from a JSON file
 * written by scripts/benchmark.py or scripts/robustness.py on the machine that
 * ran them, and when those files do not exist the panel says so rather than
 * filling in a plausible figure. That is the whole point: a hard-coded accuracy
 * number would be indistinguishable from a fabricated one.
 */
export function ValidationPanel() {
  const [payload, setPayload] = useState<BenchmarkPayload | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPayload(await getBenchmark());
    } catch (loadError) {
      setError(getApiError(loadError, "The validation results could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) {
    return (
      <section className="content-card">
        <div className="inline-empty">
          <LoaderCircle className="spin" size={19} /> Reading the stored validation runs…
        </div>
      </section>
    );
  }

  if (error || !payload) {
    return (
      <section className="content-card">
        <div className="form-alert">
          <AlertTriangle size={18} />
          <span>{error || "No validation payload was returned."}</span>
        </div>
        <button className="btn btn-secondary" onClick={() => void load()}>Try again</button>
      </section>
    );
  }

  return (
    <section className="content-card validation-panel">
      <div className="content-card-heading">
        <div>
          <span>For the reviewer</span>
          <h2>How DeepTrace measures itself</h2>
        </div>
        <span className="count-badge"><FlaskConical size={13} /> two harnesses</span>
      </div>

      <p className="panel-lead">{payload.boundary}</p>

      <div className="custody-callout" role="note">
        <CircleHelp size={20} />
        <p>
          Every figure below is read from a file written by a script in <code>scripts/</code> on the
          machine that ran it. DeepTrace ships no pre-computed accuracy numbers, so a missing run is
          reported as missing — and where a layer measures badly, the bad figure is the one shown.
        </p>
      </div>

      <div className="panel-divider" />

      <IdentityBlock payload={payload} />

      <div className="panel-divider" />

      <MetricsBlock payload={payload} />

      <div className="panel-divider" />

      <RobustnessBlock robustness={payload.robustness} harness={payload.harness} />
    </section>
  );
}

/* ── identity matching ─────────────────────────────────────────────────────── */

/**
 * The identity layer, reported first because it is the layer the product rests
 * on: DeepTrace's question is "is this the complainant's face", not "is this
 * file fake". A positive is a claimed match, so the false-positive rate here is
 * the rate at which a stranger's face would be attributed to a victim.
 */
function IdentityBlock({ payload }: { payload: BenchmarkPayload }) {
  const heading = <h3 className="custody-subhead"><UserCheck size={15} /> Identity matching on labelled pairs</h3>;
  const identity = payload.identity_matching;

  if (!payload.metrics_available) {
    return (
      <>
        {heading}
        <NotMeasured
          reason={payload.reason || "No labelled evaluation has been run in this environment."}
          command={payload.harness?.metrics_command ?? "scripts/benchmark.py"}
          note={payload.harness?.interpreter_note}
        />
      </>
    );
  }

  if (!identity || !identity.evaluated) {
    return (
      <>
        {heading}
        <NotMeasured
          reason={identity?.note
            || "The stored evaluation contains no scored verification pairs, so no precision, "
               + "recall or false-match rate is reported for identity matching. Fetch a pair set "
               + "first — the manipulation figures below do not cover this layer."}
          command={payload.harness?.fetch_command ?? "scripts/fetch_eval_data.py"}
          note={payload.harness?.interpreter_note}
        />
      </>
    );
  }

  const point = identity.operating_point;
  const counts = identity.pair_counts;

  return (
    <>
      {heading}
      <p className="panel-lead">
        {identity.evaluated} pair(s) compared by <strong>{identity.model || "the loaded model"}</strong>
        {counts && ` — ${counts.same_person} of the same person, ${counts.different_person} of different people`}
        {payload.generated_at_utc && `, run ${formatDate(payload.generated_at_utc)}`}.
      </p>

      {point ? (
        <>
          <div className="metric-tiles">
            <MetricTile label="Precision" value={point.precision} interval={point.precision_95_ci}
                        hint="Of the pairs called the same person, the share that were." />
            <MetricTile label="Recall" value={point.recall_sensitivity} interval={point.recall_95_ci}
                        hint="Of the genuine same-person pairs, the share found." />
            <MetricTile label="F1" value={point.f1}
                        hint="The harmonic mean of precision and recall." />
            <MetricTile label="False-match rate" value={point.false_positive_rate}
                        interval={point.false_positive_rate_95_ci} tone="warn"
                        hint={point.false_positive_rate_definition
                          || "The share of different-person pairs wrongly declared a match."} />
            <MetricTile label="Missed-match rate" value={point.false_negative_rate}
                        interval={point.false_negative_rate_95_ci} tone="warn"
                        hint={point.false_negative_rate_definition
                          || "The share of genuine same-person pairs the threshold misses."} />
            <MetricTile label="ROC AUC" value={identity.roc_auc}
                        hint="Threshold-free separation of the two pair types. 0.5 is chance." />
          </div>
          <ConfusionLine point={point} positive="same person" negative="different people" />
          <p className="panel-note">
            Measured at the same {point.threshold} similarity threshold the application uses when it
            decides whether a face is consistent with the enrolled reference. Intervals are 95%
            Wilson. A false match is the error with the most direct consequence for a complainant, so
            it is reported by name rather than left to be derived from precision.
          </p>
        </>
      ) : (
        <div className="form-alert">
          <AlertTriangle size={18} />
          <span>
            Only one kind of pair was present, so precision, recall and the false-match rate are
            undefined and are reported as such rather than as zero.
          </span>
        </div>
      )}

      {identity.similarity_distribution && (
        <DistributionTable distribution={identity.similarity_distribution} />
      )}

      {identity.dataset_provenance && <PairProvenance provenance={identity.dataset_provenance} />}

      <Caveats items={identity.caveats} heading="What these figures do not say" />
    </>
  );
}

/**
 * The two similarity distributions side by side.
 *
 * An AUC is one number for how separable two groups are; this is the same claim
 * in a form a reviewer can check by eye. If the ranges overlap heavily, no
 * threshold will work, and that is visible here in a way it is not in an AUC.
 */
function DistributionTable({ distribution }: { distribution: NonNullable<IdentityMetrics["similarity_distribution"]> }) {
  const rows = Object.entries(distribution).filter(([, value]) => value && value.count > 0);
  if (rows.length === 0) return null;

  return (
    <details className="technical-details" open>
      <summary>Show the similarity distributions — how far apart the two groups sit</summary>
      <div className="mini-table distribution-table">
        <div className="mini-table-head">
          <span>Pair type</span><span>Pairs</span><span>Mean</span><span>Median</span><span>Lowest</span><span>Highest</span>
        </div>
        {rows.map(([group, value]) => (
          <div className="mini-table-row" key={group}>
            <span>{group.replace(/_/g, " ")}</span>
            <span>{value!.count}</span>
            <span>{ratio(value!.mean)}</span>
            <span>{ratio(value!.median)}</span>
            <span>{ratio(value!.min)}</span>
            <span>{ratio(value!.max)}</span>
          </div>
        ))}
      </div>
      <p className="panel-note">
        Cosine similarity of the face embeddings, not a probability. The gap between the two means is
        what the threshold is placed in; the overlap between the two ranges is where the errors above
        come from.
      </p>
    </details>
  );
}

function PairProvenance({ provenance }: { provenance: IdentityPairProvenance }) {
  const corpus = provenance.corpus;
  const sourceLabel = provenance.label_source === "public_corpus_manifest"
    ? "The published corpus's own pair labels"
    : provenance.label_source === "operator_csv"
      ? "An operator-supplied CSV — nothing in this repository verified it"
      : provenance.label_source;

  return (
    <details className="technical-details">
      <summary>Where the pairs came from</summary>
      <div className="kv-grid">
        <Row label="Label source" value={sourceLabel} />
        {corpus?.dataset && (
          <Row label="Corpus" value={corpus.dataset_url
            ? <a href={corpus.dataset_url} target="_blank" rel="noreferrer">{corpus.dataset}</a>
            : corpus.dataset} />
        )}
        {corpus?.split && <Row label="Split" value={`${corpus.config ? `${corpus.config}/` : ""}${corpus.split}`} />}
        {corpus?.revision && <Row label="Revision" value={<code>{corpus.revision.slice(0, 12)}</code>} />}
        {typeof corpus?.rows_read === "number" && (
          <Row label="Rows read" value={corpus.rows_available
            ? `${corpus.rows_read} of ${corpus.rows_available}`
            : String(corpus.rows_read)} />
        )}
      </div>
      {provenance.construction && <p className="panel-note">{provenance.construction}</p>}
      {provenance.note && <p className="panel-note">{provenance.note}</p>}
    </details>
  );
}

/* ── labelled accuracy ─────────────────────────────────────────────────────── */

function MetricsBlock({ payload }: { payload: BenchmarkPayload }) {
  const metrics = payload.manipulation_detection;

  if (!payload.metrics_available || !metrics) {
    return (
      <>
        <h3 className="custody-subhead"><Target size={15} /> Manipulation detection on labelled data</h3>
        <NotMeasured
          reason={payload.reason
            || "No labelled evaluation has been run in this environment."}
          command={payload.harness?.metrics_command ?? "scripts/benchmark.py"}
          note={payload.harness?.interpreter_note}
        />
      </>
    );
  }

  const point = metrics.operating_point;

  return (
    <>
      <h3 className="custody-subhead"><Target size={15} /> Manipulation detection on labelled data</h3>
      <p className="panel-lead">
        {metrics.evaluated} file(s) scored by <strong>{metrics.model || "the loaded model"}</strong>
        {metrics.class_counts && ` — ${metrics.class_counts.real} authentic, ${metrics.class_counts.fake} manipulated`}
        {payload.generated_at_utc && `, run ${formatDate(payload.generated_at_utc)}`}.
      </p>

      {point ? (
        <>
          <div className="metric-tiles">
            <MetricTile label="Precision" value={point.precision} interval={point.precision_95_ci}
                        hint="Of the files flagged as manipulated, the share that really were." />
            <MetricTile label="Recall" value={point.recall_sensitivity} interval={point.recall_95_ci}
                        hint="Of the manipulated files, the share that were flagged." />
            <MetricTile label="F1" value={point.f1}
                        hint="The harmonic mean of precision and recall." />
            <MetricTile label="False-positive rate" value={point.false_positive_rate}
                        interval={point.false_positive_rate_95_ci} tone="warn"
                        hint={point.false_positive_rate_definition
                          || "The share of authentic files wrongly flagged as manipulated."} />
            <MetricTile label="False-negative rate" value={point.false_negative_rate}
                        interval={point.false_negative_rate_95_ci} tone="warn"
                        hint={point.false_negative_rate_definition
                          || "The share of manipulated files wrongly cleared."} />
            <MetricTile label="ROC AUC" value={metrics.roc_auc}
                        hint="Threshold-free separation. 0.5 is chance." />
          </div>
          <ConfusionLine point={point} positive="manipulated" negative="authentic" />
          <p className="panel-note">
            Measured at the same {point.threshold} threshold the application itself uses, so these
            figures describe the behaviour a demo actually shows. Intervals are 95% Wilson.
          </p>
        </>
      ) : (
        <div className="form-alert">
          <AlertTriangle size={18} />
          <span>
            Only one class was present in the dataset, so precision, recall, F1 and the
            false-positive rate are undefined and are reported as such rather than as zero.
          </span>
        </div>
      )}

      <BelowChance auc={metrics.roc_auc} />

      <FamilyBreakdownTable families={metrics.per_family} threshold={point?.threshold} />

      {metrics.dataset_provenance && <Provenance provenance={metrics.dataset_provenance} />}

      {point && metrics.threshold_sweep && metrics.threshold_sweep.length > 0 && (
        <details className="technical-details">
          <summary>Show the threshold sweep — what moving the operating point costs</summary>
          <div className="mini-table sweep-table">
            <div className="mini-table-head">
              <span>Threshold</span><span>Precision</span><span>Recall</span><span>F1</span><span>FPR</span>
            </div>
            {metrics.threshold_sweep.map((row) => (
              <div className="mini-table-row" key={row.threshold}>
                <span>{row.threshold.toFixed(2)}</span>
                <span>{ratio(row.precision)}</span>
                <span>{ratio(row.recall_sensitivity)}</span>
                <span>{ratio(row.f1)}</span>
                <span>{ratio(row.false_positive_rate)}</span>
              </div>
            ))}
          </div>
          <p className="panel-note">
            Lowering the threshold catches more manipulated files and flags more authentic ones. The
            application does not tune this per case.
          </p>
        </details>
      )}

      <Caveats items={metrics.caveats} heading="What these figures do not say" />

      {metrics.dataset_fingerprint && (
        <p className="panel-note">
          Dataset fingerprint <code>{metrics.dataset_fingerprint}</code> — a digest of the evaluated
          files&apos; contents, so a result cannot be silently reused for a different dataset.
        </p>
      )}
    </>
  );
}

/**
 * An AUC below 0.5 is not a weak result, it is a differently-shaped one, and the
 * distinction is worth spelling out where a reviewer will see it. It means the
 * ranking runs the wrong way on this corpus, so no choice of threshold produces a
 * working detector — moving the operating point only trades one error for the
 * other. Reported here rather than left to be inferred from a number in a tile.
 */
function BelowChance({ auc }: { auc?: number | null }) {
  if (auc === null || auc === undefined || auc >= 0.5) return null;
  return (
    <div className="form-alert">
      <AlertTriangle size={18} />
      <span>
        The ROC AUC of {ratio(auc)} is below 0.5, so on this corpus the score ranks manipulated media{" "}
        <strong>below</strong> authentic media. This is a measured generalisation failure, not a
        tuning problem: no threshold recovers a usable detector from a ranking that runs the wrong
        way. It is shown because it is the evidence for the position DeepTrace takes everywhere else
        — that no conclusion may rest on a manipulation score alone.
      </span>
    </div>
  );
}

/**
 * Each family of media on its own terms.
 *
 * An authentic family can only produce false positives and a manipulated family
 * can only produce misses, so the two report different metrics and the row says
 * which. A single averaged figure would hide whichever of the two is worse.
 */
function FamilyBreakdownTable({ families, threshold }: { families?: FamilyBreakdown[]; threshold?: number }) {
  if (!families || families.length === 0) return null;

  const metricLabel = (metric: string) => metric === "false_positive_rate"
    ? "wrongly flagged"
    : metric === "recall"
      ? "correctly caught"
      : metric.replace(/_/g, " ");

  return (
    <details className="technical-details" open>
      <summary>Show each family separately ({families.length}) — the two error types are not one number</summary>
      <div className="mini-table family-table">
        <div className="mini-table-head">
          <span>Family</span><span>Files</span><span>Flagged</span><span>What that is</span><span>Rate</span><span>Mean score</span>
        </div>
        {families.map((family) => (
          <div className="mini-table-row" key={`${family.class}-${family.family}`}>
            <span>{family.family} · {family.class}</span>
            <span>{family.evaluated}</span>
            <span>{family.flagged}</span>
            <span>{metricLabel(family.metric)}</span>
            <span>
              {ratio(family.value)}
              {family.value_95_ci && ` (${ratio(family.value_95_ci[0])}–${ratio(family.value_95_ci[1])})`}
            </span>
            <span>{ratio(family.mean_score)}</span>
          </div>
        ))}
      </div>
      <p className="panel-note">
        Rates are at the {threshold ?? "operating"} threshold, with the 95% Wilson interval beside
        each. Mean score is the raw signal for that family: if a manipulated family&apos;s mean sits
        below an authentic family&apos;s, the detector is not merely imprecise on this corpus, it is
        pointing the wrong way.
      </p>
    </details>
  );
}

function Provenance({ provenance }: { provenance: DatasetProvenance }) {
  const corpus = provenance.source_corpus;
  const sourceLabel = provenance.label_source === "manifest"
    ? "A generator manifest, quoted below"
    : provenance.label_source === "directory_placement"
      ? "Directory placement only — nothing verified it"
      : provenance.label_source;

  return (
    <details className="technical-details" open={provenance.manifest_matches_directory === false}>
      <summary>Where the labels came from</summary>
      <div className="kv-grid">
        <Row label="Label source" value={sourceLabel} />
        {provenance.declared_by && <Row label="Declared by" value={provenance.declared_by} />}
        {provenance.generated_at_utc && <Row label="Set built" value={formatDate(provenance.generated_at_utc)} />}
        {corpus?.dataset && (
          <Row label="Corpus" value={corpus.dataset_url
            ? <a href={corpus.dataset_url} target="_blank" rel="noreferrer">{corpus.dataset}</a>
            : corpus.dataset} />
        )}
        {corpus?.split && <Row label="Split" value={`${corpus.config ? `${corpus.config}/` : ""}${corpus.split}`} />}
        {corpus?.revision && <Row label="Revision" value={<code>{corpus.revision.slice(0, 12)}</code>} />}
        {corpus?.licence && <Row label="Declared licence" value={corpus.licence} />}
        {typeof corpus?.rows_read === "number" && (
          <Row label="Rows read" value={corpus.rows_available
            ? `${corpus.rows_read} of ${corpus.rows_available}`
            : String(corpus.rows_read)} />
        )}
      </div>
      {provenance.construction && <p className="panel-note">{provenance.construction}</p>}
      {provenance.confound_control && <p className="panel-note">{provenance.confound_control}</p>}
      {provenance.licence_note && <p className="panel-note">{provenance.licence_note}</p>}
      {provenance.manipulation_families && provenance.manipulation_families.length > 0 && (
        <div className="excluded-list">
          {provenance.manipulation_families.map((family) => (
            <div key={`${family.class}-${family.name}`}>
              <span>{family.name} · {family.count} file(s) · {family.class}</span>
              <small>{family.description}</small>
            </div>
          ))}
        </div>
      )}
      {provenance.manifest_mismatch && (
        <div className="form-alert">
          <AlertTriangle size={18} />
          <span>{provenance.manifest_mismatch}</span>
        </div>
      )}
    </details>
  );
}

/* ── robustness ────────────────────────────────────────────────────────────── */

function RobustnessBlock({ robustness, harness }: { robustness: RobustnessPayload; harness?: HarnessCommands }) {
  if (!robustness.available) {
    return (
      <>
        <h3 className="custody-subhead"><Gauge size={15} /> Robustness under degradation</h3>
        <NotMeasured
          reason={robustness.reason || "No robustness evaluation has been run in this environment."}
          command={harness?.robustness_command ?? "scripts/robustness.py"}
          note={harness?.interpreter_note}
        />
      </>
    );
  }

  return (
    <>
      <h3 className="custody-subhead"><Gauge size={15} /> Robustness under degradation</h3>
      <p className="panel-lead">{robustness.what_this_measures}</p>
      {robustness.source && (
        <p className="panel-note">
          {robustness.source.file_count} source file(s) from {robustness.source.description}, run{" "}
          {formatDate(robustness.generated_at_utc)}. Source fingerprint{" "}
          <code>{robustness.source.fingerprint}</code>.
        </p>
      )}

      <ChannelSummary channel={robustness.visual} title="Image and video manipulation signal" />
      <ChannelSummary channel={robustness.audio} title="Audio editing indicator" />

      <Caveats items={robustness.caveats} heading="What the robustness figures do not say" />
    </>
  );
}

function ChannelSummary({ channel, title }: { channel?: RobustnessChannel; title: string }) {
  if (!channel || !channel.overall || channel.overall.paired_comparisons === 0) {
    return (
      <div className="robustness-channel">
        <h4>{title}</h4>
        <p className="panel-note">
          No paired comparison completed for this channel, so no robustness figure is reported for
          it. That is not a passing result.
        </p>
      </div>
    );
  }

  const { overall } = channel;

  return (
    <div className="robustness-channel">
      <h4>{title}</h4>
      <div className="metric-tiles">
        <MetricTile label="Decision agreement" value={overall.decision_agreement}
                    interval={overall.decision_agreement_95_ci}
                    hint={`Share of the ${overall.paired_comparisons} pairs where the degraded copy landed on the same side of the threshold as the original.`} />
        <MetricTile label="Agreement, clear-cut only" value={overall.clear_cut_agreement}
                    interval={overall.clear_cut_agreement_95_ci}
                    hint={`Restricted to the ${overall.clear_cut_comparisons} file(s) whose original score was not borderline.${
                      overall.borderline_baselines > 0
                        ? ` ${overall.borderline_baselines} borderline file(s) were excluded — a file whose original score sat within 0.05 of the threshold flips under almost any transform.`
                        : " No baseline sat close enough to the threshold to be excluded, so this matches the figure beside it."
                    }`} />
        <MetricTile label="Mean score shift" value={overall.mean_absolute_delta} tone="warn"
                    hint="Mean absolute change in the score itself. Small agreement loss with a large shift still means the score moved." />
      </div>

      {overall.most_disruptive_transform && (
        <p className="panel-note">
          Most disruptive transform: <strong>{overall.most_disruptive_transform.label}</strong>{" "}
          ({overall.most_disruptive_transform.media_type}), mean shift{" "}
          {ratio(overall.most_disruptive_transform.mean_absolute_delta)}.
        </p>
      )}

      <details className="technical-details">
        <summary>Show every transform ({channel.per_transform.length})</summary>
        <div className="mini-table robustness-table">
          <div className="mini-table-head">
            <span>Transform</span><span>Media</span><span>Pairs</span><span>Mean shift</span><span>Agreement</span><span>Direction</span>
          </div>
          {channel.per_transform.map((row) => (
            <div className="mini-table-row" key={`${row.media_type}-${row.key}`}>
              <span title={row.stands_for}>{row.label}</span>
              <span>{row.media_type}</span>
              <span>{row.files_compared}{row.files_failed > 0 && ` (+${row.files_failed} failed)`}</span>
              <span>{ratio(row.mean_absolute_delta)}</span>
              <span>{ratio(row.decision_agreement)}</span>
              <span>{row.signed_delta_direction || "—"}</span>
            </div>
          ))}
        </div>
        <p className="panel-note">
          Hover a transform name for what it stands for in the real world. Direction is the sign of
          the mean change, reported so a systematic drift is visible even where agreement is 100%.
        </p>
      </details>
    </div>
  );
}

/* ── shared pieces ─────────────────────────────────────────────────────────── */

/**
 * The four raw counts behind the rates above.
 *
 * Rates compress; counts do not. "0.000" as a false-positive rate reads as a
 * claim about the world, whereas "0 of 100" states the sample it was measured on
 * and lets a reviewer see immediately how much weight it can carry.
 */
function ConfusionLine({
  point,
  positive,
  negative,
}: {
  point: ConfusionPoint;
  positive: string;
  negative: string;
}) {
  const { true_positive: tp, false_positive: fp, true_negative: tn, false_negative: fn } = point;
  if ([tp, fp, tn, fn].some((count) => typeof count !== "number")) return null;

  return (
    <p className="panel-note confusion-line">
      At the {point.threshold} threshold: <strong>{tp}</strong> of {tp! + fn!} {positive} correctly
      identified, <strong>{fn}</strong> missed; <strong>{tn}</strong> of {tn! + fp!} {negative} left
      alone, <strong>{fp}</strong> wrongly flagged.
    </p>
  );
}

function NotMeasured({ reason, command, note }: { reason: string; command: string; note?: string }) {
  return (
    <div className="not-measured">
      <div className="inline-empty">
        <ShieldAlert size={19} /> Not measured in this environment
      </div>
      <p className="panel-note">{reason}</p>
      <code className="hash-box">{command}</code>
      {note && <p className="panel-note">{note}</p>}
    </div>
  );
}

function MetricTile({
  label,
  value,
  interval,
  hint,
  tone,
}: {
  label: string;
  value?: number | null;
  interval?: [number, number] | null;
  hint: string;
  tone?: "warn";
}) {
  const missing = value === null || value === undefined;
  return (
    <div className={`metric-tile${tone === "warn" ? " metric-tile-warn" : ""}`}>
      <span className="metric-tile-label">
        <BarChart3 size={13} /> {label}
      </span>
      <strong className={missing ? "metric-tile-missing" : undefined}>
        {missing ? "Not defined" : ratio(value)}
      </strong>
      {interval && !missing && (
        <small className="metric-tile-interval">
          95% CI {ratio(interval[0])} – {ratio(interval[1])}
        </small>
      )}
      <small>{hint}</small>
    </div>
  );
}

function Caveats({ items, heading }: { items?: string[]; heading: string }) {
  if (!items || items.length === 0) return null;
  return (
    <details className="technical-details" open>
      <summary>{heading} ({items.length})</summary>
      <ul className="caveat-list">
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </details>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return <div className="kv-row"><span>{label}</span><strong>{value}</strong></div>;
}

/**
 * Ratios are shown to three decimals rather than as a rounded percentage.
 * A false-positive rate of 0.043 and one of 0.038 both round to 4%, and the
 * difference between them is exactly the kind of detail a reviewer is checking.
 */
function ratio(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}
