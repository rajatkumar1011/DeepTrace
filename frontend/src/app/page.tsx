"use client";

import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleHelp,
  ClipboardCheck,
  Clock3,
  Copy,
  Download,
  ExternalLink,
  FileCheck2,
  FileImage,
  FileSearch,
  Fingerprint,
  FolderLock,
  HeartHandshake,
  Info,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Upload,
  UserRoundCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { RiskPanel } from "@/components/RiskPanel";
import { StatusPill } from "@/components/StatusPill";
import {
  ACCEPTED_MEDIA,
  ANALYSIS_POLL_INTERVAL_MS,
  API_BASE_URL,
  API_PATHS,
  EXTERNAL_LINKS,
  MODULE_LABELS,
} from "@/config/constants";
import { getApiError } from "@/lib/api/client";
import {
  createInvestigation,
  enrollIdentity,
  generateReport,
  getDashboardStats,
  getIdentities,
  getInvestigation,
  getInvestigations,
  getTimeline,
  startAnalysis,
} from "@/lib/api/deeptrace";
import { formatBytes, formatDate, formatPercent, shortHash } from "@/lib/format";
import type {
  DashboardStats,
  IdentityItem,
  InvestigationDetail,
  InvestigationItem,
  TimelineEvent,
  ViewKey,
} from "@/types";

const emptyStats: DashboardStats = {
  active_investigations: 0,
  evidence_items: 0,
  high_risk_findings: 0,
  protected_identities: 0,
};

export default function DeepTraceApp() {
  const [view, setView] = useState<ViewKey>("home");
  const [stats, setStats] = useState<DashboardStats>(emptyStats);
  const [identities, setIdentities] = useState<IdentityItem[]>([]);
  const [investigations, setInvestigations] = useState<InvestigationItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [backendError, setBackendError] = useState<string>("");

  const refreshSharedData = useCallback(async () => {
    const results = await Promise.allSettled([
      getDashboardStats(),
      getIdentities(),
      getInvestigations(),
    ]);
    const [statsResult, identitiesResult, investigationsResult] = results;
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (identitiesResult.status === "fulfilled") setIdentities(identitiesResult.value);
    if (investigationsResult.status === "fulfilled") setInvestigations(investigationsResult.value);

    const failure = results.find((item) => item.status === "rejected");
    setBackendError(failure && failure.status === "rejected" ? getApiError(failure.reason) : "");
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshSharedData(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshSharedData]);

  const openCase = (id: number) => {
    setSelectedCaseId(id);
    setView("case");
  };

  return (
    <div className="app-root">
      <Header current={view} onNavigate={setView} />
      {backendError && (
        <div className="backend-banner" role="status">
          <div className="page-shell backend-banner-inner">
            <AlertCircle size={18} />
            <span>{backendError}</span>
            <button onClick={refreshSharedData}><RefreshCw size={15} /> Retry</button>
          </div>
        </div>
      )}
      <main>
        {view === "home" && (
          <HomeView stats={stats} recentCases={investigations.slice(0, 3)} onStart={() => setView("start")} onOpenCase={openCase} />
        )}
        {view === "start" && (
          <StartView
            identities={identities}
            onCreated={(id) => {
              refreshSharedData();
              openCase(id);
            }}
          />
        )}
        {view === "cases" && <CasesView investigations={investigations} onOpenCase={openCase} onStart={() => setView("start")} />}
        {view === "case" && selectedCaseId !== null && (
          <CaseView id={selectedCaseId} onBack={() => setView("cases")} onRefreshShared={refreshSharedData} />
        )}
        {view === "help" && <HowItWorksView onStart={() => setView("start")} />}
      </main>
      <Footer />
    </div>
  );
}

function HomeView({
  stats,
  recentCases,
  onStart,
  onOpenCase,
}: {
  stats: DashboardStats;
  recentCases: InvestigationItem[];
  onStart: () => void;
  onOpenCase: (id: number) => void;
}) {
  return (
    <>
      <section className="hero-section">
        <div className="page-shell hero-grid">
          <div className="hero-copy">
            <span className="eyebrow"><HeartHandshake size={17} /> Evidence help when you are under pressure</span>
            <h1>If someone has misused your face or voice, start by preserving the evidence.</h1>
            <p className="hero-lead">
              DeepTrace helps you securely preserve suspicious media, check forensic indicators, and prepare a structured evidence report for your next step.
            </p>
            <div className="hero-actions">
              <button className="btn btn-primary btn-lg" onClick={onStart}>Start evidence collection <ArrowRight size={18} /></button>
              <a className="btn btn-secondary btn-lg" href={EXTERNAL_LINKS.cybercrimePortal} target="_blank" rel="noreferrer">
                Go to official cybercrime portal <ExternalLink size={17} />
              </a>
            </div>
            <div className="reassurance-line">
              <CheckCircle2 size={18} /> You do not need to understand AI or forensics. We explain the findings in plain language.
            </div>
          </div>

          <aside className="calm-card" aria-label="What happens next">
            <span className="calm-card-icon"><ShieldCheck size={28} /></span>
            <h2>You are not filing a complaint here.</h2>
            <p>DeepTrace is the evidence-preparation step before an official report. You remain in control of what you upload and what you choose to submit elsewhere.</p>
            <ul className="calm-list">
              <li><Check size={16} /> Original media is hashed for integrity.</li>
              <li><Check size={16} /> Analysis is separated from preserved evidence.</li>
              <li><Check size={16} /> You can download an incident-ready PDF report.</li>
            </ul>
          </aside>
        </div>
      </section>

      <section className="page-shell section-block">
        <div className="section-heading center">
          <span>Simple by design</span>
          <h2>Three steps, one clear outcome</h2>
          <p>Instead of a forensic dashboard full of technical modules, DeepTrace leads you through the minimum actions needed to preserve and organize a case.</p>
        </div>
        <div className="three-step-grid">
          <ProcessCard number="1" icon={<Upload />} title="Add what you have" body="Upload the suspicious image, video or audio. A reference photo or voice sample is optional but improves identity matching." />
          <ProcessCard number="2" icon={<SearchCheck />} title="Let DeepTrace examine it" body="The system preserves hashes, extracts evidence, and runs manipulation, identity, audio, consistency and provenance checks." />
          <ProcessCard number="3" icon={<ClipboardCheck />} title="Review and prepare" body="You get plain-language findings, an evidence inventory, a timeline and a downloadable report to support your complaint." />
        </div>
      </section>

      <section className="soft-section">
        <div className="page-shell section-block">
          <div className="section-heading">
            <span>Why this exists</span>
            <h2>Evidence collection should not become another burden.</h2>
          </div>
          <div className="pain-grid">
            <div className="pain-card"><FileImage /><strong>Preserve the original</strong><p>Keep the suspicious media, screenshots, URLs and account details together.</p></div>
            <div className="pain-card"><Fingerprint /><strong>Protect integrity</strong><p>SHA-256 hashing records the exact state of the file you submitted.</p></div>
            <div className="pain-card"><Clock3 /><strong>Keep a timeline</strong><p>Analysis and preservation events are recorded in order, so the case is easier to explain later.</p></div>
            <div className="pain-card"><FolderLock /><strong>Package the findings</strong><p>Generate one structured report instead of manually rebuilding the story from scattered evidence.</p></div>
          </div>
        </div>
      </section>

      <section className="page-shell section-block">
        <div className="case-overview-grid">
          <div className="overview-card">
            <span className="overview-number">{stats.active_investigations}</span>
            <span>active or pending cases</span>
          </div>
          <div className="overview-card">
            <span className="overview-number">{stats.evidence_items}</span>
            <span>preserved evidence items</span>
          </div>
          <div className="overview-card">
            <span className="overview-number">{stats.protected_identities}</span>
            <span>reference identities enrolled</span>
          </div>
          <div className="overview-card">
            <span className="overview-number">{stats.high_risk_findings}</span>
            <span>cases needing close review</span>
          </div>
        </div>

        {recentCases.length > 0 && (
          <div className="recent-block">
            <div className="recent-heading">
              <div><span>Continue where you left off</span><h2>Recent cases</h2></div>
            </div>
            <div className="recent-list">
              {recentCases.map((item) => (
                <button className="recent-case" key={item.id} onClick={() => onOpenCase(item.id)}>
                  <span className="case-file-icon"><FileSearch size={20} /></span>
                  <span className="recent-case-main"><strong>Case #{item.id} · {item.filename}</strong><small>{formatDate(item.created_at)}</small></span>
                  <StatusPill status={item.status} />
                  <ArrowRight size={18} />
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </>
  );
}

function ProcessCard({ number, icon, title, body }: { number: string; icon: React.ReactNode; title: string; body: string }) {
  return (
    <article className="process-card">
      <div className="process-top"><span className="process-number">{number}</span><span className="process-icon">{icon}</span></div>
      <h3>{title}</h3><p>{body}</p>
    </article>
  );
}

function StartView({ identities, onCreated }: { identities: IdentityItem[]; onCreated: (id: number) => void }) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [identityMode, setIdentityMode] = useState<"existing" | "new" | "skip">(identities.length > 0 ? "existing" : "new");
  const [existingIdentityId, setExistingIdentityId] = useState<number | null>(identities[0]?.id ?? null);
  const [name, setName] = useState("");
  const [referenceImage, setReferenceImage] = useState<File | null>(null);
  const [referenceAudio, setReferenceAudio] = useState<File | null>(null);
  const [suspiciousFile, setSuspiciousFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const identitySummary = useMemo(() => {
    if (identityMode === "skip") return "No identity comparison";
    if (identityMode === "existing") {
      return identities.find((item) => item.id === existingIdentityId)?.name || "Existing identity";
    }
    return name || "New reference identity";
  }, [identityMode, existingIdentityId, identities, name]);

  const continueFromIdentity = () => {
    setError("");
    if (identityMode === "existing" && !existingIdentityId) return setError("Choose a reference identity or select the skip option.");
    if (identityMode === "new" && (!name.trim() || !referenceImage)) return setError("Add a name and a clear reference photo, or choose ‘Continue without identity comparison’. ");
    setStep(2);
  };

  const continueFromMedia = () => {
    setError("");
    if (!suspiciousFile) return setError("Choose the suspicious image, video or audio file you want to preserve.");
    setStep(3);
  };

  const submit = async () => {
    if (!suspiciousFile) return;
    setBusy(true);
    setError("");
    try {
      let identityId: number | null = identityMode === "existing" ? existingIdentityId : null;
      if (identityMode === "new") {
        if (!referenceImage) throw new Error("Reference image is missing.");
        const identity = await enrollIdentity({ name: name.trim(), referenceImage, referenceAudio });
        identityId = identity.id;
      }
      const investigation = await createInvestigation({ file: suspiciousFile, identityId });
      try {
        await startAnalysis(investigation.id);
      } catch {
        // The case still exists even if automatic analysis cannot be started; case view allows retry.
      }
      onCreated(investigation.id);
    } catch (submitError) {
      setError(getApiError(submitError, "DeepTrace could not create the case."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page-shell section-block start-flow">
      <div className="flow-heading">
        <span className="eyebrow"><ShieldCheck size={17} /> Start a new evidence case</span>
        <h1>We will guide you one step at a time.</h1>
        <p>You can skip identity comparison if you do not have a clean reference photo right now. The suspicious media can still be preserved and analyzed.</p>
      </div>

      <ol className="stepper" aria-label="Evidence collection steps">
        <StepItem number={1} active={step === 1} complete={step > 1} label="Reference identity" />
        <StepItem number={2} active={step === 2} complete={step > 2} label="Suspicious media" />
        <StepItem number={3} active={step === 3} complete={false} label="Review & begin" />
      </ol>

      {error && <div className="form-alert"><AlertCircle size={18} /><span>{error}</span></div>}

      {step === 1 && (
        <div className="flow-card">
          <div className="flow-card-heading"><span className="flow-card-icon"><UserRoundCheck /></span><div><span>Step 1</span><h2>Who is being impersonated?</h2><p>This helps DeepTrace compare the suspicious media with a trusted reference.</p></div></div>

          <div className="choice-grid">
            {identities.length > 0 && (
              <button className={`choice-card ${identityMode === "existing" ? "selected" : ""}`} onClick={() => setIdentityMode("existing")}>
                <strong>Use a saved identity</strong><span>Choose a reference profile you already enrolled.</span>
              </button>
            )}
            <button className={`choice-card ${identityMode === "new" ? "selected" : ""}`} onClick={() => setIdentityMode("new")}>
              <strong>Add a new reference</strong><span>Use a clear original face image and optional voice sample.</span>
            </button>
            <button className={`choice-card ${identityMode === "skip" ? "selected" : ""}`} onClick={() => setIdentityMode("skip")}>
              <strong>Continue without identity comparison</strong><span>You can still preserve the suspicious file and run other forensic checks.</span>
            </button>
          </div>

          {identityMode === "existing" && identities.length > 0 && (
            <div className="form-field">
              <label htmlFor="identity">Saved identity</label>
              <select id="identity" value={existingIdentityId ?? ""} onChange={(event) => setExistingIdentityId(Number(event.target.value))}>
                {identities.map((item) => <option key={item.id} value={item.id}>{item.name}{item.voice_enrolled ? " · face + voice" : " · face"}</option>)}
              </select>
            </div>
          )}

          {identityMode === "new" && (
            <div className="form-grid">
              <div className="form-field span-2"><label htmlFor="name">Name or case label</label><input id="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="For example: My identity" /></div>
              <FileField label="Reference face photo" hint="Required · use a clear, front-facing original photo" accept={ACCEPTED_MEDIA.image} file={referenceImage} onChange={setReferenceImage} />
              <FileField label="Reference voice sample" hint="Optional · a clean recording improves voice comparison" accept={ACCEPTED_MEDIA.audio} file={referenceAudio} onChange={setReferenceAudio} />
            </div>
          )}

          <div className="flow-actions end"><button className="btn btn-primary" onClick={continueFromIdentity}>Continue <ArrowRight size={17} /></button></div>
        </div>
      )}

      {step === 2 && (
        <div className="flow-card">
          <div className="flow-card-heading"><span className="flow-card-icon"><Upload /></span><div><span>Step 2</span><h2>Add the suspicious media</h2><p>Upload the image, video or audio you want to preserve. DeepTrace will calculate an integrity hash as soon as the case is created.</p></div></div>
          <div className="upload-zone">
            <input id="suspicious-file" type="file" accept={ACCEPTED_MEDIA.suspicious} onChange={(event) => setSuspiciousFile(event.target.files?.[0] || null)} />
            <label htmlFor="suspicious-file">
              <span className="upload-icon"><Upload size={26} /></span>
              <strong>{suspiciousFile ? suspiciousFile.name : "Choose suspicious media"}</strong>
              <span>{suspiciousFile ? `${formatBytes(suspiciousFile.size)} selected` : "Image, video or audio"}</span>
            </label>
          </div>
          <div className="support-note"><Info size={17} /><span>If this came from social media, also keep the post URL, username, date/time and screenshots. The current backend preserves the uploaded media; source-URL tracing is a separate integration.</span></div>
          <div className="flow-actions"><button className="btn btn-ghost" onClick={() => setStep(1)}><ChevronLeft size={17} /> Back</button><button className="btn btn-primary" onClick={continueFromMedia}>Continue <ArrowRight size={17} /></button></div>
        </div>
      )}

      {step === 3 && (
        <div className="flow-card">
          <div className="flow-card-heading"><span className="flow-card-icon"><ClipboardCheck /></span><div><span>Step 3</span><h2>Review before DeepTrace begins</h2><p>No technical choices are needed. DeepTrace will create the case, preserve the file and start the available analysis modules automatically.</p></div></div>
          <div className="review-list">
            <ReviewRow label="Reference identity" value={identitySummary} />
            <ReviewRow label="Suspicious media" value={suspiciousFile?.name || "—"} />
            <ReviewRow label="File size" value={formatBytes(suspiciousFile?.size)} />
            <ReviewRow label="What happens next" value="Integrity hash → forensic analysis → evidence package → report" />
          </div>
          <div className="consent-note"><LockKeyhole size={19} /><div><strong>Your evidence is treated separately from the AI result.</strong><p>A model score does not overwrite the preserved original. DeepTrace keeps the evidence integrity hash and analytical findings as distinct records.</p></div></div>
          <div className="flow-actions"><button className="btn btn-ghost" onClick={() => setStep(2)} disabled={busy}><ChevronLeft size={17} /> Back</button><button className="btn btn-primary btn-lg" onClick={submit} disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} /> Creating your case…</> : <>Create case and begin analysis <ArrowRight size={18} /></>}</button></div>
        </div>
      )}
    </section>
  );
}

function StepItem({ number, active, complete, label }: { number: number; active: boolean; complete: boolean; label: string }) {
  return <li className={`${active ? "active" : ""} ${complete ? "complete" : ""}`}><span>{complete ? <Check size={17} /> : number}</span><small>{label}</small></li>;
}

function FileField({ label, hint, accept, file, onChange }: { label: string; hint: string; accept: string; file: File | null; onChange: (file: File | null) => void }) {
  return (
    <div className="form-field file-field">
      <label>{label}</label>
      <div className="compact-file-input">
        <input type="file" accept={accept} onChange={(event) => onChange(event.target.files?.[0] || null)} />
      </div>
      <small>{file ? `${file.name} · ${formatBytes(file.size)}` : hint}</small>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return <div className="review-row"><span>{label}</span><strong>{value}</strong></div>;
}

function CasesView({ investigations, onOpenCase, onStart }: { investigations: InvestigationItem[]; onOpenCase: (id: number) => void; onStart: () => void }) {
  return (
    <section className="page-shell section-block">
      <div className="page-title-row"><div><span className="eyebrow"><FolderLock size={17} /> Preserved cases</span><h1>My evidence cases</h1><p>Open a case to review findings, evidence integrity, timeline and report options.</p></div><button className="btn btn-primary" onClick={onStart}>Start a new case <ArrowRight size={17} /></button></div>
      {investigations.length === 0 ? (
        <EmptyState title="No cases yet" body="Start with the suspicious media you want to preserve." action={<button className="btn btn-primary" onClick={onStart}>Start evidence collection</button>} />
      ) : (
        <div className="case-list">
          {investigations.map((item) => (
            <button key={item.id} className="case-row" onClick={() => onOpenCase(item.id)}>
              <span className="case-row-icon"><FileSearch size={21} /></span>
              <span className="case-row-main"><strong>Case #{item.id}</strong><span>{item.filename}</span><small>{formatDate(item.created_at)}</small></span>
              <span className="case-media">{item.media_type}</span>
              <StatusPill status={item.status} />
              <span className={`risk-mini risk-${(item.risk_level || "pending").toLowerCase()}`}>{item.risk_level || "Awaiting result"}</span>
              <ArrowRight size={19} />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function CaseView({ id, onBack, onRefreshShared }: { id: number; onBack: () => void; onRefreshShared: () => void }) {
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [reportReady, setReportReady] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [detail, events] = await Promise.all([getInvestigation(id), getTimeline(id)]);
      setInvestigation(detail);
      setTimeline(events);
      setError("");
      return detail;
    } catch (loadError) {
      setError(getApiError(loadError, "DeepTrace could not load this case."));
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const investigationStatus = investigation?.status;
  useEffect(() => {
    if (investigationStatus !== "analyzing") return;
    const timer = window.setInterval(async () => {
      const updated = await load();
      if (updated?.status === "completed" || updated?.status === "failed") onRefreshShared();
    }, ANALYSIS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [investigationStatus, load, onRefreshShared]);

  const runAnalysis = async () => {
    setActionBusy(true); setError("");
    try { await startAnalysis(id); await load(); onRefreshShared(); }
    catch (actionError) { setError(getApiError(actionError, "Analysis could not be started.")); }
    finally { setActionBusy(false); }
  };

  const buildReport = async () => {
    setActionBusy(true); setError("");
    try { await generateReport(id); setReportReady(true); }
    catch (actionError) { setError(getApiError(actionError, "The PDF report could not be generated.")); }
    finally { setActionBusy(false); }
  };

  const copyHash = async () => {
    if (!investigation?.sha256_hash) return;
    try { await navigator.clipboard.writeText(investigation.sha256_hash); }
    catch { /* clipboard may be blocked */ }
  };

  if (loading) return <section className="page-shell section-block"><div className="loading-panel"><LoaderCircle className="spin" /> Loading case…</div></section>;
  if (!investigation) return <section className="page-shell section-block"><div className="form-alert"><AlertCircle />{error || "Case not found."}</div></section>;

  const modules = investigation.analysis_results || {};
  const moduleEntries = Object.entries(MODULE_LABELS).filter(([key]) => modules[key]);
  const evidence = investigation.evidence || [];

  return (
    <section className="page-shell section-block case-page">
      <button className="back-link" onClick={onBack}><ChevronLeft size={17} /> Back to my cases</button>
      <div className="case-header">
        <div>
          <span className="eyebrow">Case #{investigation.id}</span>
          <h1>{investigation.filename}</h1>
          <div className="case-meta-line"><span>{investigation.media_type}</span><span>•</span><span>{formatBytes(investigation.file_size_bytes)}</span><span>•</span><span>{formatDate(investigation.created_at)}</span></div>
        </div>
        <StatusPill status={investigation.status} />
      </div>

      {error && <div className="form-alert"><AlertCircle size={18} /><span>{error}</span></div>}

      {investigation.status === "analyzing" && (
        <div className="analysis-progress"><LoaderCircle className="spin" size={22} /><div><strong>DeepTrace is analyzing the preserved media.</strong><p>You can stay on this page. Findings refresh automatically every few seconds.</p></div></div>
      )}
      {investigation.status === "pending" && (
        <div className="analysis-progress pending"><Info size={22} /><div><strong>Your evidence has been preserved, but analysis has not started.</strong><p>Start the forensic analysis when you are ready.</p></div><button className="btn btn-primary" onClick={runAnalysis} disabled={actionBusy}>Start analysis</button></div>
      )}

      <div className="case-main-grid">
        <div className="case-main-column">
          <section className="content-card">
            <div className="content-card-heading"><div><span>Plain-language assessment</span><h2>What DeepTrace found</h2></div><button className="icon-button" onClick={load} aria-label="Refresh case"><RefreshCw size={17} /></button></div>
            <RiskPanel level={investigation.risk_level} score={investigation.overall_risk_score} />

            {moduleEntries.length > 0 ? (
              <div className="finding-list">
                {moduleEntries.map(([key, copy]) => {
                  const analysis = modules[key];
                  const score = analysis?.score;
                  return (
                    <div className="finding-row" key={key}>
                      <span className="finding-icon"><SearchCheck size={19} /></span>
                      <div className="finding-copy"><strong>{copy.title}</strong><p>{plainModuleResult(key, score, analysis?.data)}</p></div>
                      <span className="finding-score">{formatPercent(score)}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="inline-empty"><Clock3 size={19} /> Findings will appear here after analysis is complete.</div>
            )}

            {moduleEntries.length > 0 && (
              <details className="technical-details">
                <summary>Show technical model details</summary>
                <div className="technical-grid">
                  {moduleEntries.map(([key, copy]) => {
                    const analysis = modules[key];
                    return (
                      <div key={key} className="technical-card">
                        <strong>{copy.title}</strong>
                        <span>Score: {formatPercent(analysis.score)}</span>
                        <span>Confidence: {formatPercent(analysis.confidence)}</span>
                        <span>Method: {String(analysis.data?.method || analysis.data?.model_name || "Available backend method")}</span>
                        {analysis.data?.model_status ? <span>Status: {String(analysis.data.model_status)}</span> : null}
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </section>

          <section className="content-card">
            <div className="content-card-heading"><div><span>Preserved artifacts</span><h2>Evidence inventory</h2></div><span className="count-badge">{evidence.length} items</span></div>
            {evidence.length === 0 ? <div className="inline-empty"><FileCheck2 size={19} /> No evidence artifacts listed yet.</div> : (
              <div className="evidence-list">
                {evidence.map((item) => (
                  <div className="evidence-row" key={item.id}>
                    <span className="evidence-icon"><FileCheck2 size={19} /></span>
                    <div><strong>{item.type === "original" ? "Original uploaded media" : item.type === "frame" ? "Extracted video frame" : item.type}</strong><small>{item.timestamp_offset !== null ? `Timestamp ${item.timestamp_offset.toFixed(2)} seconds` : "Preserved artifact"}</small></div>
                    <code>{shortHash(item.sha256)}</code>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="content-card">
            <div className="content-card-heading"><div><span>Chain of actions</span><h2>Investigation timeline</h2></div></div>
            {timeline.length === 0 ? <div className="inline-empty"><Clock3 size={19} /> Timeline events will appear as the case progresses.</div> : (
              <div className="timeline-simple">
                {timeline.map((event) => <div key={event.id}><span className="timeline-dot" /><div><strong>{humanizeEvent(event.event_type, event.description)}</strong><small>{formatDate(event.created_at)}</small></div></div>)}
              </div>
            )}
          </section>
        </div>

        <aside className="case-side-column">
          <section className="content-card sticky-card">
            <div className="side-heading"><Fingerprint size={20} /><div><span>Evidence integrity</span><h2>Original file hash</h2></div></div>
            <p className="side-copy">This SHA-256 value fingerprints the exact file received by DeepTrace.</p>
            <code className="hash-box">{investigation.sha256_hash}</code>
            <button className="btn btn-secondary btn-full" onClick={copyHash}><Copy size={16} /> Copy hash</button>
            <div className="evidence-facts">
              <div><span>Resolution</span><strong>{investigation.resolution || "—"}</strong></div>
              <div><span>Duration</span><strong>{investigation.duration_seconds ? `${investigation.duration_seconds.toFixed(2)} s` : "—"}</strong></div>
              <div><span>Frames preserved</span><strong>{investigation.frames_extracted ?? 0}</strong></div>
            </div>
          </section>

          <section className="content-card next-actions-card">
            <div className="side-heading"><ClipboardCheck size={20} /><div><span>Next step</span><h2>Prepare to report</h2></div></div>
            <ol className="next-actions">
              <li><span>1</span><div><strong>Keep screenshots and source URLs</strong><p>Save the post/page URL, username, date/time and any threats or messages.</p></div></li>
              <li><span>2</span><div><strong>Generate the DeepTrace report</strong><p>Package the analysis, evidence integrity information and case timeline.</p></div></li>
              <li><span>3</span><div><strong>File or support your official complaint</strong><p>Use the National Cyber Crime Reporting Portal or the appropriate police/cyber cell process.</p></div></li>
            </ol>
            <button className="btn btn-primary btn-full" onClick={buildReport} disabled={actionBusy || investigation.status !== "completed"}>{actionBusy ? <><LoaderCircle className="spin" size={17} /> Preparing…</> : <><Download size={17} /> Generate evidence report</>}</button>
            {reportReady && <a className="btn btn-success btn-full" href={`${API_BASE_URL}${API_PATHS.reportDownload(id)}`} target="_blank" rel="noreferrer"><Download size={17} /> Download PDF report</a>}
            <a className="btn btn-secondary btn-full" href={EXTERNAL_LINKS.cybercrimePortal} target="_blank" rel="noreferrer">Official cybercrime portal <ExternalLink size={16} /></a>
            <p className="micro-disclaimer">DeepTrace does not submit complaints automatically and does not claim that model outputs are legal proof.</p>
          </section>
        </aside>
      </div>
    </section>
  );
}

function plainModuleResult(key: string, score: number | null, data?: Record<string, unknown>) {
  if (score === null || score === undefined) {
    if (key === "provenance") {
      const found = Boolean(data?.credentials_found);
      return found ? "Content Credentials were detected. They may provide useful provenance context." : "No usable Content Credentials were found in this file.";
    }
    return "This signal was not available for the current media or environment.";
  }
  const pct = Math.round(score * 100);
  if (key === "deepfake") return pct >= 75 ? "Strong manipulation indicators were detected." : pct >= 50 ? "Some manipulation indicators were detected and deserve review." : "Few manipulation indicators were detected by this module.";
  if (key === "identity") return pct >= 75 ? "The face appears strongly similar to the protected reference identity." : pct >= 50 ? "The face shows moderate similarity to the protected reference." : "The visual identity match is weak or inconclusive.";
  if (key === "voice") return pct >= 75 ? "The voice appears strongly similar to the protected reference sample." : pct >= 50 ? "The voice shows moderate similarity to the reference sample." : "The voice match is weak, unavailable, or inconclusive.";
  if (key === "consistency") return pct >= 70 ? "Audio and visual activity appear broadly consistent in the sampled regions." : "Some audio-video inconsistency was observed and may deserve review.";
  if (key === "similarity") return pct >= 80 ? "A strong local similarity match was found against evidence already preserved in DeepTrace." : "No strong local match was found in the current DeepTrace evidence database.";
  return MODULE_LABELS[key]?.plain || "Review this forensic signal together with the preserved evidence.";
}

function humanizeEvent(type: string, fallback: string) {
  const labels: Record<string, string> = {
    investigation_created: "Case created",
    evidence_uploaded: "Original evidence received",
    hash_generated: "Integrity hash generated",
    metadata_extracted: "Media metadata recorded",
    frames_sampled: "Video evidence frames preserved",
    analysis_started: "Forensic analysis started",
    manipulation_analysis: "Manipulation analysis completed",
    identity_analysis: "Identity comparison completed",
    audio_analysis: "Voice analysis completed",
    av_consistency: "Audio-video consistency reviewed",
    provenance_check: "Content provenance checked",
    similarity_search: "Local similarity search completed",
    risk_assessment: "Overall assessment calculated",
    evidence_preserved: "Evidence preservation completed",
    analysis_completed: "Case analysis completed",
    analysis_failed: "Analysis reported an error",
    report_generated: "Evidence report generated",
  };
  return labels[type] || fallback;
}

function HowItWorksView({ onStart }: { onStart: () => void }) {
  return (
    <section className="page-shell section-block help-page">
      <div className="section-heading center wide"><span>How DeepTrace fits into the response process</span><h1>Evidence first. Analysis second. Reporting remains official.</h1><p>The interface is deliberately simpler than a traditional forensic dashboard because a victim may be stressed, angry, frightened or unsure what to do next.</p></div>

      <div className="help-steps">
        <HelpStep icon={<FolderLock />} number="1" title="Preserve the media" body="DeepTrace saves the uploaded original and calculates a SHA-256 integrity hash. For videos, selected frames can also be preserved as evidence artifacts." />
        <HelpStep icon={<SearchCheck />} number="2" title="Run separate forensic checks" body="Manipulation detection, identity matching, voice verification, audio-video consistency, provenance and local similarity are kept as separate signals rather than collapsing everything into one fake/real answer." />
        <HelpStep icon={<ClipboardCheck />} number="3" title="Build an evidence package" body="The case combines file details, hashes, preserved artifacts, analysis results and a chronological timeline in one report." />
        <HelpStep icon={<ExternalLink />} number="4" title="Use the official reporting channel" body="DeepTrace is a pre-reporting support layer. Official complaints should still go through the National Cyber Crime Reporting Portal or the appropriate law-enforcement channel." />
      </div>

      <div className="boundaries-card">
        <div><CircleHelp size={22} /><div><strong>What DeepTrace does not claim</strong><p>No internet-wide surveillance, no creator identification, no 100% accurate deepfake verdict, and no automatic police or platform submission.</p></div></div>
        <button className="btn btn-primary" onClick={onStart}>Start evidence collection <ArrowRight size={17} /></button>
      </div>
    </section>
  );
}

function HelpStep({ icon, number, title, body }: { icon: React.ReactNode; number: string; title: string; body: string }) {
  return <article className="help-step"><div className="help-step-top"><span>{icon}</span><small>{number}</small></div><h2>{title}</h2><p>{body}</p></article>;
}
