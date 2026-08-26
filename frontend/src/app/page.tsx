"use client";

import {
  AlertCircle,
  ArrowRight,
  Camera,
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
  Mic,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Upload,
  UserRoundCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AnalysisProgress } from "@/components/AnalysisProgress";
import { AudioPanel } from "@/components/AudioPanel";
import { CameraCapture } from "@/components/CameraCapture";
import { CustodyPanel } from "@/components/CustodyPanel";
import { EmptyState } from "@/components/EmptyState";
import { Footer } from "@/components/Footer";
import { GuidancePanel } from "@/components/GuidancePanel";
import { Header } from "@/components/Header";
import { IntegrityPanel } from "@/components/IntegrityPanel";
import { MetadataPanel } from "@/components/MetadataPanel";
import { RiskExplanation } from "@/components/RiskExplanation";
import { RiskPanel } from "@/components/RiskPanel";
import { StatusPill } from "@/components/StatusPill";
import { SuspiciousFramesPanel } from "@/components/SuspiciousFramesPanel";
import { TracePanel } from "@/components/TracePanel";
import { ValidationPanel } from "@/components/ValidationPanel";
import { VoiceRecorder } from "@/components/VoiceRecorder";
import {
  ACCEPTED_MEDIA,
  ANALYSIS_POLL_INTERVAL_MS,
  API_BASE_URL,
  API_PATHS,
  EXTERNAL_LINKS,
  MODULE_LABELS,
  MODULE_STATUS_COPY,
  PRIMARY_USER,
} from "@/config/constants";
import { getApiError } from "@/lib/api/client";
import {
  createInvestigation,
  enrollIdentity,
  generateReport,
  getConsentText,
  getDashboardStats,
  getDemoAssets,
  getIdentities,
  getInvestigation,
  getInvestigations,
  getTimeline,
  startAnalysis,
} from "@/lib/api/deeptrace";
import { formatBytes, formatDate, formatPercent } from "@/lib/format";
import { num, str } from "@/lib/modules";
import type {
  DashboardStats,
  DemoAsset,
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

type CaseTab = "findings" | "frames" | "audio" | "technical" | "evidence" | "tracing" | "next";

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
        <div className="section-heading">
          <span>Who this is for</span>
          <h2>Built for the person it happened to. Written so an investigator can use it.</h2>
        </div>

        <div className="role-banner">
          <div className="role-card is-primary">
            <HeartHandshake size={26} />
            <div>
              <em>Primary user</em>
              <strong>{PRIMARY_USER.primary.role} <span>({PRIMARY_USER.primary.also})</span></strong>
              <p>{PRIMARY_USER.primary.statement}</p>
            </div>
          </div>
          <div className="role-card is-secondary">
            <UserRoundCheck size={26} />
            <div>
              <em>Secondary user</em>
              <strong>{PRIMARY_USER.secondary.role} <span>({PRIMARY_USER.secondary.also})</span></strong>
              <p>{PRIMARY_USER.secondary.statement}</p>
            </div>
          </div>
        </div>

        <div className="reads-what">
          <div><span>Who</span><span>Reads</span><span>Why</span></div>
          {PRIMARY_USER.readsWhat.map((row) => (
            <div key={row.who}>
              <strong>{row.who}</strong>
              <span>{row.reads}</span>
              <small>{row.why}</small>
            </div>
          ))}
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
  const [consentGiven, setConsentGiven] = useState(false);
  const [consentText, setConsentText] = useState<{ version: string; text: string } | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [recorderOpen, setRecorderOpen] = useState(false);
  const [suspiciousFile, setSuspiciousFile] = useState<File | null>(null);
  const [sourceUrls, setSourceUrls] = useState("");
  const [demoAssets, setDemoAssets] = useState<DemoAsset[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void getConsentText().then(setConsentText).catch(() => setConsentText(null));
      void getDemoAssets().then((payload) => setDemoAssets(payload.assets)).catch(() => setDemoAssets([]));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

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
    if (identityMode === "new") {
      if (!name.trim() || !referenceImage) {
        return setError("Add a name and a clear reference photo, or choose ‘Continue without identity comparison’.");
      }
      if (!consentGiven) {
        return setError("A reference face or voice sample is only enrolled with recorded consent. Tick the consent box to continue.");
      }
    }
    setStep(2);
  };

  const continueFromMedia = () => {
    setError("");
    if (!suspiciousFile) return setError("Choose the suspicious image, video or audio file you want to preserve.");
    setStep(3);
  };

  /** Load a bundled demo file as the submission, so the demo path needs no local media. */
  const loadDemoAsset = async (asset: DemoAsset) => {
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}${asset.url}`);
      if (!response.ok) throw new Error(`Demo asset returned HTTP ${response.status}`);
      const blob = await response.blob();
      setSuspiciousFile(new File([blob], asset.filename, { type: blob.type }));
    } catch (assetError) {
      setError(getApiError(assetError, "The demo file could not be loaded from the backend."));
    }
  };

  const submit = async () => {
    if (!suspiciousFile) return;
    setBusy(true);
    setError("");
    try {
      let identityId: number | null = identityMode === "existing" ? existingIdentityId : null;
      if (identityMode === "new") {
        if (!referenceImage) throw new Error("Reference image is missing.");
        const identity = await enrollIdentity({ name: name.trim(), referenceImage, referenceAudio, consentGiven });
        identityId = identity.id;
      }
      const investigation = await createInvestigation({ file: suspiciousFile, identityId, sourceUrls });
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
            <>
              <div className="form-grid">
                <div className="form-field span-2"><label htmlFor="name">Name or case label</label><input id="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="For example: My identity" /></div>
                <FileField
                  label="Reference face photo"
                  hint="Required · use a clear, front-facing original photo"
                  accept={ACCEPTED_MEDIA.image}
                  file={referenceImage}
                  onChange={setReferenceImage}
                  capture={
                    <div className="capture-row">
                      <span className="or">or</span>
                      <button type="button" className="capture-btn" onClick={() => setCameraOpen(true)}>
                        <Camera size={14} /> Take a photo now
                      </button>
                    </div>
                  }
                />
                <FileField
                  label="Reference voice sample"
                  hint="Optional · a clean recording improves voice comparison"
                  accept={ACCEPTED_MEDIA.audio}
                  file={referenceAudio}
                  onChange={setReferenceAudio}
                  capture={
                    <div className="capture-row">
                      <span className="or">or</span>
                      <button type="button" className="capture-btn" onClick={() => setRecorderOpen(true)}>
                        <Mic size={14} /> Record my voice now
                      </button>
                    </div>
                  }
                />
              </div>

              <div className="consent-box">
                <label>
                  <input type="checkbox" checked={consentGiven} onChange={(event) => setConsentGiven(event.target.checked)} />
                  <span>
                    <strong>I consent to enrolling this reference sample.</strong>
                    {consentText && <small>Consent notice version {consentText.version} — recorded with the enrollment.</small>}
                  </span>
                </label>
                {consentText && (
                  <details>
                    <summary>Read the consent notice</summary>
                    <p>{consentText.text}</p>
                  </details>
                )}
              </div>
            </>
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

          {demoAssets.length > 0 && (
            <div className="demo-picker">
              <strong>No file to hand? Use a bundled sample.</strong>
              <p>These are demo <em>inputs</em> only. Every score, hash and finding shown afterwards is computed live from the file you pick.</p>
              <div className="chip-row">
                {demoAssets.map((asset) => (
                  <button className="chip chip-button" key={asset.filename} onClick={() => loadDemoAsset(asset)}>
                    {asset.filename} · {formatBytes(asset.size_bytes)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="form-field">
            <label htmlFor="source-urls">Where did you see it? (optional)</label>
            <textarea
              id="source-urls"
              rows={2}
              value={sourceUrls}
              onChange={(event) => setSourceUrls(event.target.value)}
              placeholder="https://example.com/the-post — one per line"
            />
            <small>Recorded with the case. You can also ask DeepTrace to fetch and compare a public HTTPS copy later, from the case&rsquo;s Tracing tab.</small>
          </div>

          <div className="support-note"><Info size={17} /><span>If this came from social media, also keep screenshots, the username and the date/time. DeepTrace preserves the uploaded media and can compare copies you point it at; it does not search the internet on your behalf.</span></div>
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
            <ReviewRow label="Source noted" value={sourceUrls.trim() ? `${sourceUrls.trim().split(/\s+/).length} URL(s)` : "None"} />
            <ReviewRow label="What happens next" value="Integrity hash → forensic analysis → evidence package → report" />
          </div>
          <div className="consent-note"><LockKeyhole size={19} /><div><strong>Your evidence is treated separately from the AI result.</strong><p>A model score does not overwrite the preserved original. DeepTrace keeps the evidence integrity hash and analytical findings as distinct records.</p></div></div>
          <div className="flow-actions"><button className="btn btn-ghost" onClick={() => setStep(2)} disabled={busy}><ChevronLeft size={17} /> Back</button><button className="btn btn-primary btn-lg" onClick={submit} disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} /> Creating your case…</> : <>Create case and begin analysis <ArrowRight size={18} /></>}</button></div>
        </div>
      )}

      {/* Live capture modals. Each hands a File back to the form; the enrollment
          request uploads it normally so the server hashes what it receives. */}
      {cameraOpen && <CameraCapture onCapture={setReferenceImage} onClose={() => setCameraOpen(false)} />}
      {recorderOpen && <VoiceRecorder onRecorded={setReferenceAudio} onClose={() => setRecorderOpen(false)} />}
    </section>
  );
}

function StepItem({ number, active, complete, label }: { number: number; active: boolean; complete: boolean; label: string }) {
  return <li className={`${active ? "active" : ""} ${complete ? "complete" : ""}`}><span>{complete ? <Check size={17} /> : number}</span><small>{label}</small></li>;
}

function FileField({ label, hint, accept, file, onChange, capture }: { label: string; hint: string; accept: string; file: File | null; onChange: (file: File | null) => void; capture?: React.ReactNode }) {
  return (
    <div className="form-field file-field">
      <label>{label}</label>
      <div className="compact-file-input">
        <input type="file" accept={accept} onChange={(event) => onChange(event.target.files?.[0] || null)} />
      </div>
      {capture}
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

const CASE_TABS: { key: CaseTab; label: string }[] = [
  { key: "findings", label: "Findings" },
  { key: "frames", label: "Flagged frames" },
  { key: "audio", label: "Audio & sync" },
  { key: "technical", label: "Metadata" },
  { key: "evidence", label: "Evidence & integrity" },
  { key: "tracing", label: "Tracing" },
  { key: "next", label: "Next steps" },
];

function CaseView({ id, onBack, onRefreshShared }: { id: number; onBack: () => void; onRefreshShared: () => void }) {
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [tab, setTab] = useState<CaseTab>("findings");
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [reportReady, setReportReady] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [detail, events] = await Promise.all([getInvestigation(id), getTimeline(id)]);
      setInvestigation(detail);
      setTimeline(events);
      setReportReady(detail.report_available);
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
  const completed = investigation.status === "completed";

  return (
    <section className="page-shell section-block case-page">
      <button className="back-link" onClick={onBack}><ChevronLeft size={17} /> Back to my cases</button>
      <div className="case-header">
        <div>
          <span className="eyebrow">Case #{investigation.id}</span>
          <h1>{investigation.filename}</h1>
          <div className="case-meta-line">
            <span className="media-kind">{investigation.media_type}</span><span>•</span>
            <span>{formatBytes(investigation.file_size_bytes)}</span><span>•</span>
            <span>{formatDate(investigation.created_at)}</span>
            {investigation.identity_name && <><span>•</span><span>vs {investigation.identity_name}</span></>}
          </div>
        </div>
        <StatusPill status={investigation.status} />
      </div>

      {error && <div className="form-alert"><AlertCircle size={18} /><span>{error}</span></div>}

      <AnalysisProgress investigation={investigation} />
      {investigation.status === "pending" && (
        <div className="analysis-progress pending"><Info size={22} /><div><strong>Your evidence has been preserved, but analysis has not started.</strong><p>Start the forensic analysis when you are ready.</p></div><button className="btn btn-primary" onClick={runAnalysis} disabled={actionBusy}>Start analysis</button></div>
      )}
      {investigation.status === "failed" && (
        <div className="flow-actions end"><button className="btn btn-secondary" onClick={runAnalysis} disabled={actionBusy}><RefreshCw size={16} /> Retry analysis</button></div>
      )}

      <div className="case-main-grid">
        <div className="case-main-column">
          <nav className="case-tabs" aria-label="Case sections">
            {CASE_TABS.map((item) => (
              <button key={item.key} className={tab === item.key ? "active" : ""} onClick={() => setTab(item.key)} aria-current={tab === item.key}>
                {item.label}
              </button>
            ))}
          </nav>

          {tab === "findings" && (
            <>
              <section className="content-card">
                <div className="content-card-heading"><div><span>Plain-language assessment</span><h2>What DeepTrace found</h2></div><button className="icon-button" onClick={load} aria-label="Refresh case"><RefreshCw size={17} /></button></div>
                <RiskPanel level={investigation.risk_level} score={investigation.overall_risk_score} />

                {moduleEntries.length > 0 ? (
                  <div className="finding-list">
                    {moduleEntries.map(([key, copy]) => {
                      const analysis = modules[key];
                      const statusCopy = MODULE_STATUS_COPY[analysis.status] || { label: analysis.status, tone: "muted" as const };
                      return (
                        <div className="finding-row" key={key}>
                          <span className="finding-icon"><SearchCheck size={19} /></span>
                          <div className="finding-copy">
                            <strong>{copy.title} <em className={`status-tag tone-${statusCopy.tone}`}>{statusCopy.label}</em></strong>
                            <p>{plainModuleResult(key, analysis.status, analysis.score, analysis.data)}</p>
                          </div>
                          <span className="finding-score">{analysis.status === "completed" ? formatPercent(analysis.score) : "—"}</span>
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
                        const data = analysis.data || {};
                        return (
                          <div key={key} className="technical-card">
                            <strong>{copy.title}</strong>
                            <span>Status: {analysis.status}</span>
                            <span>Score: {analysis.status === "completed" ? formatPercent(analysis.score) : "Not available"}</span>
                            <span>Confidence: {formatPercent(analysis.confidence)}</span>
                            <span>Method: {str(data, "method") || str(data, "model_name") || "Not recorded"}</span>
                            {str(data, "model_version") && <span>Version: {str(data, "model_version")}</span>}
                            {num(data, "threshold") !== null && <span>Threshold: {num(data, "threshold")}</span>}
                          </div>
                        );
                      })}
                    </div>
                  </details>
                )}

                <p className="micro-disclaimer">
                  These are forensic indicators produced by research models on a local CPU. They are not a verdict, and a
                  module marked unavailable is neither evidence of authenticity nor evidence of manipulation.
                </p>
              </section>

              <RiskExplanation investigation={investigation} />

              <section className="content-card">
                <div className="content-card-heading"><div><span>Chain of actions</span><h2>Investigation timeline</h2></div><span className="count-badge">{timeline.length} events</span></div>
                {timeline.length === 0 ? <div className="inline-empty"><Clock3 size={19} /> Timeline events will appear as the case progresses.</div> : (
                  <div className="timeline-simple">
                    {timeline.map((event) => <div key={event.id}><span className="timeline-dot" /><div><strong>{humanizeEvent(event.event_type, event.description)}</strong><small>{event.description}</small><small>{formatDate(event.created_at)}</small></div></div>)}
                  </div>
                )}
              </section>
            </>
          )}

          {tab === "frames" && <SuspiciousFramesPanel investigation={investigation} />}
          {tab === "audio" && <AudioPanel investigation={investigation} />}
          {tab === "technical" && <MetadataPanel investigation={investigation} />}
          {tab === "evidence" && (
            <>
              <CustodyPanel investigationId={investigation.id} />
              <IntegrityPanel investigationId={investigation.id} evidence={evidence} />
            </>
          )}
          {tab === "tracing" && <TracePanel investigation={investigation} onChanged={load} />}
          {tab === "next" && <GuidancePanel investigationId={investigation.id} ready={completed} />}
        </div>

        <aside className="case-side-column">
          <section className="content-card">
            <div className="side-heading"><Fingerprint size={20} /><div><span>Evidence integrity</span><h2>Original file hash</h2></div></div>
            <p className="side-copy">This SHA-256 value fingerprints the exact file received by DeepTrace. It was computed server-side as the upload was written to disk.</p>
            <code className="hash-box">{investigation.sha256_hash}</code>
            <button className="btn btn-secondary btn-full" onClick={copyHash}><Copy size={16} /> Copy hash</button>
            <div className="evidence-facts">
              <div><span>Resolution</span><strong>{investigation.resolution || "—"}</strong></div>
              <div><span>Duration</span><strong>{investigation.duration_seconds ? `${investigation.duration_seconds.toFixed(2)} s` : "—"}</strong></div>
              <div><span>Frames preserved</span><strong>{investigation.frames_extracted ?? 0}</strong></div>
              <div><span>Artifacts preserved</span><strong>{evidence.length}</strong></div>
              <div><span>Audio stream</span><strong>{investigation.has_audio_stream === null ? "—" : investigation.has_audio_stream ? "Present" : "None"}</strong></div>
            </div>
          </section>

          <section className="content-card next-actions-card">
            <div className="side-heading"><ClipboardCheck size={20} /><div><span>Next step</span><h2>Prepare to report</h2></div></div>
            <ol className="next-actions">
              <li><span>1</span><div><strong>Keep screenshots and source URLs</strong><p>Save the post/page URL, username, date/time and any threats or messages.</p></div></li>
              <li><span>2</span><div><strong>Generate the DeepTrace report</strong><p>Twenty-two sections covering the chain of custody, evidence hashes, per-module findings, the timeline and reporting routes.</p></div></li>
              <li><span>3</span><div><strong>File or support your official complaint</strong><p>Use the National Cyber Crime Reporting Portal or the appropriate police/cyber cell process.</p></div></li>
            </ol>
            <button className="btn btn-primary btn-full" onClick={buildReport} disabled={actionBusy || !completed}>{actionBusy ? <><LoaderCircle className="spin" size={17} /> Preparing…</> : <><Download size={17} /> {reportReady ? "Regenerate report" : "Generate evidence report"}</>}</button>
            {reportReady && <a className="btn btn-success btn-full" href={`${API_BASE_URL}${API_PATHS.reportDownload(id)}`} target="_blank" rel="noreferrer"><Download size={17} /> Download PDF report</a>}
            <button className="btn btn-secondary btn-full" onClick={() => setTab("next")}><FileCheck2 size={16} /> See recommended next steps</button>
            <p className="micro-disclaimer">DeepTrace does not submit complaints automatically and does not claim that model outputs are legal proof.</p>
          </section>
        </aside>
      </div>
    </section>
  );
}

/**
 * Plain-language sentence for one module. A module that did not produce a result
 * says so and says why — it is never described as if it had found nothing.
 */
function plainModuleResult(key: string, status: string, score: number | null, data?: Record<string, unknown> | null) {
  const payload = data || {};

  if (status !== "completed") {
    const reason = str(payload, "reason") || str(payload, "details") || str(payload, "status");
    if (key === "provenance") {
      return payload.credentials_found === true
        ? "Content Credentials were detected. They may provide useful provenance context."
        : "No Content Credentials are attached to this file. That is normal for media shared on social platforms and is not itself suspicious.";
    }
    if (status === "not_applicable") return reason || "This check does not apply to the submitted media.";
    return reason || "This signal was not available for the current media or environment.";
  }

  if (score === null || score === undefined) {
    return str(payload, "summary") || str(payload, "interpretation") || MODULE_LABELS[key]?.plain || "Completed.";
  }

  const pct = Math.round(score * 100);
  // A module that completed may still have established that its own measurement
  // does not describe this media — a speaker cosine from a half-second clip, an
  // alignment figure from B-roll. It says so with `excluded_from_risk` and gives
  // its reason, and that reason is the finding. Restating the raw number as a
  // verdict here would contradict the module that made the measurement.
  if (payload.excluded_from_risk === true) {
    const withheld = str(payload, "exclusion_reason");
    if (withheld) return withheld;
  }
  if (key === "deepfake") {
    const frames = num(payload, "suspicious_frame_count");
    const total = num(payload, "frames_analyzed");
    const detail = frames !== null && total !== null ? ` ${frames} of ${total} sampled frames crossed the threshold.` : "";
    if (pct >= 75) return `Strong manipulation indicators were detected.${detail}`;
    if (pct >= 50) return `Some manipulation indicators were detected and deserve review.${detail}`;
    return `Few manipulation indicators were detected by this module.${detail}`;
  }
  if (key === "identity") return str(payload, "interpretation") || (pct >= 60 ? "The face is similar to the protected reference identity." : "The visual identity match is below the same-person threshold.");
  // The module's own `interpretation` is authoritative — it knows the threshold it
  // was decided against and whether the clip was long enough to decide anything.
  // The fallback deliberately does not guess a verdict from the score.
  if (key === "voice") return str(payload, "interpretation") || "A speaker comparison was recorded; see the score and threshold below.";
  if (key === "audio") return `${num(payload, "discontinuity_count") ?? 0} abrupt level change(s) were measured in the audio track.`;
  // Low alignment is expected for voice-overs, reaction shots and B-roll, so the
  // number alone does not support "inconsistency was observed". Where the module
  // judged its measurement applicable it says so in `details`.
  if (key === "consistency") {
    return pct >= 70
      ? "Audio and visual activity appear broadly consistent in the sampled regions."
      : "Audio and visual activity agreed in a minority of sampled moments. This is common in legitimate edits such as voice-overs, so treat it as a supporting signal only.";
  }
  if (key === "similarity") return str(payload, "summary") || (pct >= 80 ? "A strong local similarity match was found against evidence already preserved in DeepTrace." : "No strong local match was found in the current DeepTrace evidence database.");
  return MODULE_LABELS[key]?.plain || "Review this forensic signal together with the preserved evidence.";
}

function humanizeEvent(type: string, fallback: string) {
  // Keys here must match the event types backend/main.py actually writes. An
  // invented key is silently dead — `fallback` covers for it — so this list was
  // taken from the add_timeline call sites rather than from what reads well.
  const labels: Record<string, string> = {
    investigation_created: "Case created",
    evidence_uploaded: "Original evidence received",
    hash_generated: "Integrity hash generated",
    metadata_extracted: "Media metadata recorded",
    frames_sampled: "Video evidence frames preserved",
    audio_extracted: "Audio track extracted",
    audio_analysis: "Audio forensics completed",
    analysis_started: "Forensic analysis started",
    analysis_restarted: "Forensic analysis re-run",
    manipulation_analysis: "Manipulation analysis completed",
    localization: "Manipulation localization completed",
    identity_analysis: "Identity comparison completed",
    identity_attached: "Protected identity attached to case",
    voice_analysis: "Speaker verification completed",
    av_consistency: "Audio-video consistency reviewed",
    provenance_check: "Content provenance checked",
    similarity_search: "Local similarity search completed",
    source_recorded: "Source URL recorded",
    source_traced: "External copy traced and compared",
    source_trace_failed: "External copy could not be retrieved",
    integrity_verified: "Evidence integrity re-verified",
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
        <HelpStep icon={<FolderLock />} number="1" title="Preserve the media" body="DeepTrace saves the uploaded original and calculates a SHA-256 integrity hash server-side. For videos, sampled frames, the extracted audio track and manipulation overlays are preserved as separate artifacts, each with its own digest." />
        <HelpStep icon={<SearchCheck />} number="2" title="Run separate forensic checks" body="Manipulation detection, localization, face matching, speaker verification, audio forensics, audio-video consistency, provenance and local copy tracing are kept as separate signals rather than collapsing everything into one fake/real answer." />
        <HelpStep icon={<ClipboardCheck />} number="3" title="Build an evidence package" body="The case combines file details, hashes, preserved artifacts, the chain of custody, per-module findings, a weighted risk explanation and a chronological timeline into one twenty-two-section report." />
        <HelpStep icon={<ExternalLink />} number="4" title="Use the official reporting channel" body="DeepTrace is a pre-reporting support layer. Official complaints should still go through the National Cyber Crime Reporting Portal or the appropriate law-enforcement channel." />
      </div>

      <div className="boundaries-card">
        <div><CircleHelp size={22} /><div><strong>What DeepTrace does not claim</strong><p>No internet-wide surveillance, no creator identification, no 100% accurate deepfake verdict, no guaranteed legal admissibility, and no automatic police or platform submission. Copy tracing compares only the specific public URLs or files you provide.</p></div></div>
        <button className="btn btn-primary" onClick={onStart}>Start evidence collection <ArrowRight size={17} /></button>
      </div>

      <ValidationPanel />
    </section>
  );
}

function HelpStep({ icon, number, title, body }: { icon: React.ReactNode; number: string; title: string; body: string }) {
  return <article className="help-step"><div className="help-step-top"><span>{icon}</span><small>{number}</small></div><h2>{title}</h2><p>{body}</p></article>;
}
