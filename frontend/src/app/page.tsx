"use client";
import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const API = "http://localhost:8000";

// ─── Types ────────────────────────────────────────────
interface DashboardStats {
  active_investigations: number;
  evidence_items: number;
  high_risk_findings: number;
  protected_identities: number;
}
interface IdentityItem {
  id: number;
  name: string;
  face_enrolled: boolean;
  voice_enrolled: boolean;
  created_at: string;
}
interface InvestigationItem {
  id: number;
  filename: string;
  media_type: string;
  status: string;
  risk_level: string | null;
  created_at: string;
  identity_id: number | null;
}
interface InvestigationDetail {
  id: number;
  filename: string;
  file_path: string;
  file_size_bytes: number;
  sha256_hash: string;
  media_type: string;
  status: string;
  identity_id: number | null;
  duration_seconds: number | null;
  resolution: string | null;
  fps: number | null;
  frames_extracted: number | null;
  overall_risk_score: number | null;
  risk_level: string | null;
  created_at: string;
  analysis_results: Record<string, AnalysisModule>;
  evidence: EvidenceItem[];
}
interface AnalysisModule {
  score: number | null;
  confidence: number | null;
  data: Record<string, unknown>;
  created_at: string;
}
interface EvidenceItem {
  id: number;
  type: string;
  file_path: string;
  sha256: string | null;
  perceptual_hash: string | null;
  timestamp_offset: number | null;
}
interface TimelineEvent {
  id: number;
  event_type: string;
  description: string;
  created_at: string;
}

// ─── Main App ─────────────────────────────────────────
export default function DeepTraceDashboard() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [identities, setIdentities] = useState<IdentityItem[]>([]);
  const [investigations, setInvestigations] = useState<InvestigationItem[]>([]);
  const [selectedInvestigation, setSelectedInvestigation] = useState<InvestigationDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const fetchStats = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/dashboard/stats`);
      setStats(res.data);
    } catch { /* ignore */ }
  }, []);

  const fetchIdentities = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/identities`);
      setIdentities(res.data);
    } catch { /* ignore */ }
  }, []);

  const fetchInvestigations = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/investigations`);
      setInvestigations(res.data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchStats();
    fetchIdentities();
    fetchInvestigations();
  }, [fetchStats, fetchIdentities, fetchInvestigations]);

  useEffect(() => {
    if (activeTab !== "timeline" || !selectedInvestigation) return;
    axios.get(`${API}/api/investigation/${selectedInvestigation.id}/timeline`)
      .then((res) => setTimeline(res.data))
      .catch(() => setMessage("Failed to refresh investigation timeline"));
  }, [activeTab, selectedInvestigation]);

  const loadInvestigation = async (id: number) => {
    try {
      const [invRes, tlRes] = await Promise.all([
        axios.get(`${API}/api/investigation/${id}`),
        axios.get(`${API}/api/investigation/${id}/timeline`),
      ]);
      setSelectedInvestigation(invRes.data);
      setTimeline(tlRes.data);
      setActiveTab("analysis");
    } catch { setMessage("Failed to load investigation"); }
  };

  const tabs = [
    { key: "dashboard", label: "Dashboard", icon: "📊" },
    { key: "identity", label: "Protected Identity", icon: "🛡️" },
    { key: "investigate", label: "New Investigation", icon: "🔍" },
    { key: "analysis", label: "Analysis", icon: "🧬" },
    { key: "evidence", label: "Evidence", icon: "📁" },
    { key: "timeline", label: "Timeline", icon: "⏱️" },
    { key: "similarity", label: "Similarity", icon: "🔗" },
    { key: "report", label: "Report", icon: "📄" },
  ];

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-64 bg-[#0d1224] border-r border-cyan-900/30 flex flex-col py-6 px-3 shrink-0">
        <div className="flex items-center gap-2 px-3 mb-8">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-violet-500 flex items-center justify-center text-sm font-bold">DT</div>
          <span className="text-lg font-bold tracking-tight bg-gradient-to-r from-cyan-400 to-violet-400 bg-clip-text text-transparent">DeepTrace</span>
        </div>
        <nav className="flex flex-col gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                activeTab === t.key
                  ? "bg-cyan-500/15 text-cyan-400 border border-cyan-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              }`}
            >
              <span>{t.icon}</span> {t.label}
            </button>
          ))}
        </nav>
        <div className="mt-auto px-3 pt-4 border-t border-cyan-900/20">
          <p className="text-[10px] text-slate-500 leading-relaxed">DeepTrace v1.0 — Hackathon Prototype<br/>Team Algorythm · SIH26_28</p>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-6">
        {message && (
          <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-sm flex justify-between">
            {message}
            <button onClick={() => setMessage("")} className="text-cyan-400 hover:text-white">✕</button>
          </div>
        )}

        {activeTab === "dashboard" && <DashboardView stats={stats} investigations={investigations} onSelect={loadInvestigation} />}
        {activeTab === "identity" && <IdentityView identities={identities} onRefresh={fetchIdentities} setMessage={setMessage} />}
        {activeTab === "investigate" && <InvestigateView identities={identities} onCreated={(id: number) => { fetchInvestigations(); fetchStats(); loadInvestigation(id); }} setMessage={setMessage} />}
        {activeTab === "analysis" && <AnalysisView investigation={selectedInvestigation} onRefresh={() => selectedInvestigation && loadInvestigation(selectedInvestigation.id)} setMessage={setMessage} loading={loading} setLoading={setLoading} />}
        {activeTab === "evidence" && <EvidenceView investigation={selectedInvestigation} />}
        {activeTab === "timeline" && <TimelineView timeline={timeline} investigation={selectedInvestigation} />}
        {activeTab === "similarity" && <SimilarityView investigation={selectedInvestigation} />}
        {activeTab === "report" && <ReportView investigation={selectedInvestigation} setMessage={setMessage} />}
      </main>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────
function DashboardView({ stats, investigations, onSelect }: { stats: DashboardStats | null; investigations: InvestigationItem[]; onSelect: (id: number) => void }) {
  const cards = [
    { label: "Active Investigations", value: stats?.active_investigations ?? 0, color: "from-cyan-500 to-blue-600", icon: "🔍" },
    { label: "Evidence Items", value: stats?.evidence_items ?? 0, color: "from-violet-500 to-purple-600", icon: "📁" },
    { label: "High Risk Findings", value: stats?.high_risk_findings ?? 0, color: "from-red-500 to-rose-600", icon: "⚠️" },
    { label: "Protected Identities", value: stats?.protected_identities ?? 0, color: "from-emerald-500 to-green-600", icon: "🛡️" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Forensic Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {cards.map((c) => (
          <div key={c.label} className="glass-card p-5 glow">
            <div className="flex items-center justify-between mb-3">
              <span className="text-2xl">{c.icon}</span>
              <span className={`text-3xl font-bold bg-gradient-to-r ${c.color} bg-clip-text text-transparent`}>{c.value}</span>
            </div>
            <p className="text-sm text-slate-400">{c.label}</p>
          </div>
        ))}
      </div>

      <h2 className="text-lg font-semibold mb-4">Recent Investigations</h2>
      {investigations.length === 0 ? (
        <p className="text-slate-500">No investigations yet. Create one to get started.</p>
      ) : (
        <div className="space-y-2">
          {investigations.slice(0, 10).map((inv) => (
            <button key={inv.id} onClick={() => onSelect(inv.id)} className="w-full glass-card p-4 flex items-center justify-between hover:border-cyan-400/40 transition-all text-left">
              <div className="flex items-center gap-4">
                <span className="text-lg">{inv.media_type === "video" ? "🎬" : inv.media_type === "image" ? "🖼️" : "🔊"}</span>
                <div>
                  <p className="font-medium text-sm">{inv.filename}</p>
                  <p className="text-xs text-slate-500">{inv.created_at}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <RiskBadge level={inv.risk_level} />
                <StatusBadge status={inv.status} />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Identity ─────────────────────────────────────────
function IdentityView({ identities, onRefresh, setMessage }: { identities: IdentityItem[]; onRefresh: () => void; setMessage: (m: string) => void }) {
  const [name, setName] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [enrolling, setEnrolling] = useState(false);

  const handleEnroll = async () => {
    if (!name || !imageFile) { setMessage("Name and reference image are required"); return; }
    setEnrolling(true);
    const fd = new FormData();
    fd.append("name", name);
    fd.append("reference_image", imageFile);
    if (audioFile) fd.append("reference_audio", audioFile);
    try {
      const res = await axios.post(`${API}/api/identity/enroll`, fd);
      setMessage(`✅ Identity "${res.data.name}" enrolled (Face: ${res.data.face_enrolled ? "Yes" : "No"}, Voice: ${res.data.voice_enrolled ? "Yes" : "No"})`);
      setName(""); setImageFile(null); setAudioFile(null);
      onRefresh();
    } catch (err: unknown) {
      const axErr = err as { response?: { data?: { detail?: string } } };
      setMessage(`❌ Enrollment failed: ${axErr.response?.data?.detail || "Unknown error"}`);
    } finally { setEnrolling(false); }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Protected Identity Management</h1>
      
      {/* Enrollment Form */}
      <div className="glass-card p-6 mb-8 max-w-xl">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">🛡️ Enroll New Identity</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Identity Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., CEO, Public Figure" className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-white text-sm focus:border-cyan-500 outline-none" />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Reference Face Image *</label>
            <input type="file" accept="image/*" onChange={(e) => setImageFile(e.target.files?.[0] || null)} className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-cyan-500/10 file:text-cyan-400 hover:file:bg-cyan-500/20" />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Reference Voice Sample (optional)</label>
            <input type="file" accept="audio/*" onChange={(e) => setAudioFile(e.target.files?.[0] || null)} className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-violet-500/10 file:text-violet-400 hover:file:bg-violet-500/20" />
          </div>
          <button onClick={handleEnroll} disabled={enrolling} className="px-6 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-semibold text-sm hover:opacity-90 transition disabled:opacity-50">
            {enrolling ? "Enrolling..." : "Enroll Identity"}
          </button>
        </div>
      </div>

      {/* List */}
      <h2 className="text-lg font-semibold mb-4">Enrolled Identities</h2>
      {identities.length === 0 ? (
        <p className="text-slate-500">No identities enrolled yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {identities.map((id) => (
            <div key={id.id} className="glass-card p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-400 to-violet-500 flex items-center justify-center font-bold text-sm">{id.name[0]}</div>
                <div>
                  <p className="font-medium">{id.name}</p>
                  <p className="text-xs text-slate-500">ID: {id.id}</p>
                </div>
              </div>
              <div className="flex gap-2 mt-2">
                <span className={`text-xs px-2 py-1 rounded ${id.face_enrolled ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
                  Face: {id.face_enrolled ? "✓" : "✗"}
                </span>
                <span className={`text-xs px-2 py-1 rounded ${id.voice_enrolled ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-500/20 text-slate-400"}`}>
                  Voice: {id.voice_enrolled ? "✓" : "N/A"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── New Investigation ────────────────────────────────
function InvestigateView({ identities, onCreated, setMessage }: { identities: IdentityItem[]; onCreated: (id: number) => void; setMessage: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [identityId, setIdentityId] = useState<string>("");
  const [uploading, setUploading] = useState(false);

  const handleUpload = async () => {
    if (!file) { setMessage("Please select a suspicious media file."); return; }
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    if (identityId) fd.append("identity_id", identityId);
    try {
      const res = await axios.post(`${API}/api/investigate`, fd);
      setMessage(`✅ Investigation #${res.data.id} created. SHA-256: ${res.data.sha256?.substring(0, 16)}...`);
      setFile(null); setIdentityId("");
      onCreated(res.data.id);
    } catch (err: unknown) {
      const axErr = err as { response?: { data?: { detail?: string } } };
      setMessage(`❌ Upload failed: ${axErr.response?.data?.detail || "Unknown error"}`);
    } finally { setUploading(false); }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">New Investigation</h1>
      <div className="glass-card p-6 max-w-xl">
        <div className="space-y-4">
          <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 text-xs text-slate-400">
            <p className="font-semibold text-cyan-300 mb-2">Demo assets</p>
            <p className="mb-2">Use these existing local files for the two-minute demo:</p>
            <div className="flex flex-wrap gap-3">
              <a className="text-cyan-300 underline" href={`${API}/demo-assets/demo/lena.jpg`} target="_blank" rel="noreferrer">Demo face: lena.jpg</a>
              <a className="text-cyan-300 underline" href={`${API}/demo-assets/test_video.mp4`} target="_blank" rel="noreferrer">Demo media: test_video.mp4</a>
            </div>
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Suspicious Media File</label>
            <div className="border-2 border-dashed border-slate-700 rounded-lg p-8 text-center hover:border-cyan-500/50 transition">
              <input type="file" accept="image/*,video/*,audio/*" onChange={(e) => setFile(e.target.files?.[0] || null)} className="w-full text-sm text-slate-400" />
              <p className="text-xs text-slate-500 mt-2">Supports: JPG, PNG, MP4, AVI, MOV, WAV, MP3</p>
              {file && <p className="text-sm text-cyan-400 mt-2">Selected: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)</p>}
            </div>
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Reference Identity (optional)</label>
            <select value={identityId} onChange={(e) => setIdentityId(e.target.value)} className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-white text-sm focus:border-cyan-500 outline-none">
              <option value="">None — skip identity comparison</option>
              {identities.map((id) => <option key={id.id} value={id.id}>{id.name} (ID: {id.id})</option>)}
            </select>
          </div>
          <button onClick={handleUpload} disabled={uploading} className="w-full px-6 py-3 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-semibold text-sm hover:opacity-90 transition disabled:opacity-50">
            {uploading ? "Uploading & Processing..." : "🔍 Start Investigation"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Analysis ─────────────────────────────────────────
function AnalysisView({ investigation, onRefresh, setMessage, loading, setLoading }: {
  investigation: InvestigationDetail | null;
  onRefresh: () => void;
  setMessage: (m: string) => void;
  loading: boolean;
  setLoading: (l: boolean) => void;
}) {
  if (!investigation) return <p className="text-slate-500">Select an investigation from the Dashboard first.</p>;
  const inv = investigation;
  const ar = inv.analysis_results;
  const riskLevel = typeof inv.risk_level === "string" ? String(inv.risk_level) : "";
  const riskData = (ar.risk_fusion?.data || {}) as Record<string, unknown>;
  const contributors = (riskData.contributors || {}) as Record<string, string>;
  const riskFormula = typeof riskData.formula === "string" ? riskData.formula : "Available-signal weighted calculation";
  const hasRiskData = Boolean(ar.risk_fusion && ar.risk_fusion.data);

  const startAnalysis = async () => {
    setLoading(true);
    try {
      await axios.post(`${API}/api/investigation/${inv.id}/analyze`);
      setMessage("⏳ Analysis started. This may take 1-2 minutes for video. Refresh to see results.");
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const res = await axios.get(`${API}/api/investigation/${inv.id}`);
          if (res.data.status === "completed" || res.data.status === "failed") {
            clearInterval(poll);
            setLoading(false);
            onRefresh();
            setMessage(res.data.status === "completed" ? "✅ Analysis completed!" : "❌ Analysis failed.");
          }
        } catch { /* continue polling */ }
      }, 3000);
    } catch { setMessage("❌ Failed to start analysis."); setLoading(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Analysis — INV#{inv.id}</h1>
        <div className="flex gap-3">
          <button onClick={onRefresh} className="px-4 py-2 rounded-lg bg-slate-700 text-sm hover:bg-slate-600 transition">🔄 Refresh</button>
          {inv.status === "pending" && (
            <button onClick={startAnalysis} disabled={loading} className="px-6 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-semibold text-sm hover:opacity-90 transition disabled:opacity-50">
              {loading ? "⏳ Analyzing..." : "▶ Run Analysis"}
            </button>
          )}
        </div>
      </div>

      {/* File Info */}
      <div className="glass-card p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div><span className="text-slate-500">File:</span><br/><span className="font-mono text-xs">{inv.filename}</span></div>
          <div><span className="text-slate-500">Type:</span><br/>{inv.media_type}</div>
          <div><span className="text-slate-500">Size:</span><br/>{(inv.file_size_bytes / 1024 / 1024).toFixed(2)} MB</div>
          <div><span className="text-slate-500">Status:</span><br/><StatusBadge status={inv.status} /></div>
        </div>
        <div className="mt-3 text-xs font-mono text-slate-500 break-all">SHA-256: {inv.sha256_hash}</div>
      </div>

      {/* Overall Risk */}
      <div className="glass-card p-5 mb-6 glow">
        <h2 className="text-lg font-semibold mb-3">Overall Risk Assessment</h2>
        <div className="flex items-center gap-4 mb-4">
          <span className="text-sm px-3 py-1 rounded border bg-amber-500/20 text-amber-300 border-amber-500/30 font-bold">{riskLevel || "PENDING"}</span>
          <p className="text-sm text-slate-400">Risk Score: <span className="font-bold text-white">{String(((inv.overall_risk_score || 0) * 100).toFixed(1))}%</span></p>
        </div>
        <p className="text-xs text-slate-400">Contributing evidence: {String(JSON.stringify(contributors))}</p>
        <p className="text-[10px] text-slate-600 mt-3">Formula: {String(riskFormula)}</p>
        <p className="text-[10px] text-amber-300 mt-2">Risk score is an analytical aid, not proof of manipulation or identity.</p>
        </div>

      {/* Analysis Modules */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ModuleCard title="🧬 Manipulation Signal" module={ar.deepfake} type="deepfake" />
        <ModuleCard title="👤 Identity / Visual Similarity" module={ar.identity} type="identity" />
        <ModuleCard title="🎙️ Voice" module={ar.voice} type="voice" />
        <ModuleCard title="🔄 A/V Consistency" module={ar.consistency} type="consistency" />
        <ModuleCard title="📜 Provenance" module={ar.provenance} type="provenance" />
        <ModuleCard title="🔗 Similarity" module={ar.similarity} type="similarity" />
      </div>

      {/* Deepfake Frame Timeline */}
      {Boolean(ar.deepfake && (ar.deepfake.data as Record<string, unknown>).frame_results) ? (
        <div className="glass-card p-5 mt-6">
          <h2 className="text-lg font-semibold mb-4">Suspicious Frame Timeline</h2>
          <div className="flex gap-2 overflow-x-auto pb-2">
            {((ar.deepfake.data as Record<string, unknown>).frame_results as Array<Record<string, unknown>>).map((fr, i) => (
              <div key={i} className={`shrink-0 p-3 rounded-lg border text-center text-xs ${(fr.manipulation_signal as number) > 0.5 ? "border-red-500/50 bg-red-500/10" : "border-emerald-500/30 bg-emerald-500/5"}`}>
                <p className="font-mono mb-1">Frame {i + 1}</p>
                <p className={`font-bold ${(fr.manipulation_signal as number) > 0.5 ? "text-red-400" : "text-emerald-400"}`}>
                  {((fr.manipulation_signal as number) * 100).toFixed(1)}%
                </p>
                <p className="text-slate-500">{(fr.manipulation_signal as number) > 0.5 ? "⚠ Elevated signal" : "✓ Low signal"}</p>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-600 mt-2">Model: {String((ar.deepfake.data as Record<string, unknown>).model_name || "Pretrained classifier")} — actual frame-level output.</p>
        </div>
      ) : null}
    </div>
  );
}

// ─── Module Card ──────────────────────────────────────
function ModuleCard({ title, module, type }: { title: string; module?: AnalysisModule; type: string }) {
  if (!module) return (
    <div className="glass-card p-4 opacity-60">
      <h3 className="font-semibold text-sm mb-2">{title}</h3>
      <p className="text-xs text-slate-500">Analysis not yet run</p>
    </div>
  );

  const data = module.data as Record<string, unknown> || {};
  const hasError = !!data.error;
  const statusMsg = data.status as string;
  const method = (data.method as string) || (type === "deepfake" ? "Lightweight fallback" : "Recorded forensic signal");
  const modelStatus = (data.model_status as string) || (type === "deepfake" || type === "identity" || type === "voice" || type === "provenance" ? "Unavailable on this machine" : "Available");
  const modelName = typeof data.model_name === "string" ? data.model_name : "Not applicable";
  const modelVersion = typeof data.model_version === "string" ? data.model_version : "";
  const note = typeof data.note === "string" ? data.note : "";
  const explanation: string = (data.explanation as string) || {
    deepfake: "A manipulation signal, not a trained deepfake detector.",
    identity: "Visual similarity signal (fallback), not identity probability.",
    voice: "Speaker comparison requires a reference voice.",
    consistency: "Heuristic audio/video alignment signal.",
    provenance: "No Content Credentials were independently verified.",
    similarity: "Matches are limited to indexed local evidence.",
  }[type] || "Supporting forensic signal.";

  if (hasError || (module.score === null && statusMsg)) {
    return (
      <div className="glass-card p-4 border-l-2 border-yellow-500/50">
        <h3 className="font-semibold text-sm mb-2">{title}</h3>
        <p className="text-xs text-amber-400">{statusMsg || data.error as string}</p>
        <p className="text-[10px] text-slate-500 mt-2">Method: {method}</p>
        <p className="text-[10px] text-slate-500">Model: {modelName}</p>
        <p className="text-[10px] text-slate-500">Status: {modelStatus}</p>
        <p className="text-[10px] text-slate-500 mt-1">{explanation}</p>
      </div>
    );
  }

  const scoreColor = type === "consistency" 
    ? (module.score ?? 0) > 0.7 ? "text-emerald-400" : "text-amber-400"
    : (module.score ?? 0) > 0.5 ? "text-red-400" : "text-emerald-400";

  return (
    <div className="glass-card p-4">
      <h3 className="font-semibold text-sm mb-2">{title}</h3>
      <p className={`text-2xl font-bold ${scoreColor}`}>{((module.score ?? 0) * 100).toFixed(1)}%</p>
      <p className="text-xs text-slate-400 mt-2">Result: {type === "identity" ? "Visual similarity signal" : type === "deepfake" ? "Manipulation signal" : type === "consistency" ? "Alignment signal" : type === "voice" ? "Voice similarity signal" : `${((module.score ?? 0) * 100).toFixed(1)}%`}</p>
      <p className="text-[10px] text-slate-500 mt-1">Method: {method}</p>
      <p className="text-[10px] text-slate-500">Model: {modelName}{modelVersion ? ` (${modelVersion})` : ""}</p>
      <p className="text-[10px] text-slate-500">Status: {modelStatus}</p>
      <p className="text-[10px] text-slate-500 mt-1">{explanation}</p>
      {note && <p className="text-[10px] text-slate-600 mt-2">{note}</p>}
    </div>
  );
}

// ─── Evidence ─────────────────────────────────────────
function EvidenceView({ investigation }: { investigation: InvestigationDetail | null }) {
  if (!investigation) return <p className="text-slate-500">Select an investigation first.</p>;
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Evidence — INV#{investigation.id}</h1>
      <div className="glass-card p-4 mb-4">
        <h2 className="text-sm font-semibold mb-3">File Details</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
          <div><span className="text-slate-500">Filename:</span><br/>{investigation.filename}</div>
          <div><span className="text-slate-500">Media Type:</span><br/>{investigation.media_type}</div>
          <div><span className="text-slate-500">File Size:</span><br/>{(investigation.file_size_bytes / 1024).toFixed(1)} KB</div>
          {investigation.resolution && <div><span className="text-slate-500">Resolution:</span><br/>{investigation.resolution}</div>}
          {investigation.fps && <div><span className="text-slate-500">FPS:</span><br/>{investigation.fps}</div>}
          {investigation.duration_seconds && <div><span className="text-slate-500">Duration:</span><br/>{investigation.duration_seconds.toFixed(2)}s</div>}
        </div>
        <div className="mt-4 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3">
          <p className="text-xs font-semibold text-cyan-300">Evidence integrity hash</p>
          <p className="mt-1 font-mono text-xs break-all text-slate-300">SHA-256: {investigation.sha256_hash}</p>
          <p className="mt-1 text-[10px] text-slate-500">Hash calculated from original uploaded file. The original upload is preserved.</p>
        </div>
      </div>
      
      <h2 className="text-lg font-semibold mb-4">Evidence Artifacts ({investigation.evidence.length})</h2>
      <div className="space-y-2">
        {investigation.evidence.map((ev) => (
          <div key={ev.id} className="glass-card p-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-3">
              <span className="text-lg">{ev.type === "original" ? "📎" : ev.type === "frame" ? "🖼️" : "📄"}</span>
              <div>
                <p className="font-medium">{ev.type.toUpperCase()}</p>
                {ev.timestamp_offset !== null && <p className="text-slate-500">@ {ev.timestamp_offset.toFixed(2)}s</p>}
              </div>
            </div>
            <div className="text-right text-slate-500">
              {ev.sha256 && <p className="font-mono">{ev.sha256.substring(0, 16)}...</p>}
              {ev.perceptual_hash && <p>pHash: {ev.perceptual_hash}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SimilarityView({ investigation }: { investigation: InvestigationDetail | null }) {
  if (!investigation) return <p className="text-slate-500">Select an investigation first.</p>;
  const module = investigation.analysis_results.similarity;
  const data = (module?.data || {}) as Record<string, unknown>;
  const matches = (data.matches || []) as Array<Record<string, unknown>>;
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Similarity — INV#{investigation.id}</h1>
      <div className="glass-card p-5 mb-5">
        <h2 className="text-lg font-semibold">Supported indexed sources</h2>
        <p className="text-sm text-slate-400 mt-2">Local perceptual and exact-hash matching only. This is not universal internet crawling or attribution.</p>
        <p className="text-sm text-cyan-300 mt-3">{(data.status as string) || "Similarity analysis not yet completed"}</p>
      </div>
      {matches.length === 0 ? (
        <div className="glass-card p-5 text-sm text-slate-500">No local similarity matches.</div>
      ) : (
        <div className="space-y-2">
          {matches.map((match, index) => <div key={index} className="glass-card p-4 text-sm">{JSON.stringify(match)}</div>)}
        </div>
      )}
    </div>
  );
}

// ─── Timeline ─────────────────────────────────────────
function TimelineView({ timeline, investigation }: { timeline: TimelineEvent[]; investigation: InvestigationDetail | null }) {
  if (!investigation) return <p className="text-slate-500">Select an investigation first.</p>;
  
  const icons: Record<string, string> = {
    investigation_created: "🆕", evidence_uploaded: "📤", hash_generated: "🔐",
    metadata_extracted: "📋", frames_sampled: "🎞️", analysis_started: "▶️",
    manipulation_analysis: "🧬", identity_analysis: "👤", audio_analysis: "🎙️",
    av_consistency: "🔄", provenance_check: "📜", similarity_search: "🔗", risk_assessment: "⚖️",
    evidence_preserved: "💾", analysis_completed: "✅", analysis_failed: "❌",
    report_generated: "📄",
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Investigation Timeline — INV#{investigation.id}</h1>
      <div className="relative border-l-2 border-cyan-500/30 ml-4">
        {timeline.map((ev, i) => (
          <div key={ev.id} className="mb-4 ml-6 relative">
            <div className="absolute -left-[33px] w-5 h-5 rounded-full bg-[#0a0e1a] border-2 border-cyan-500 flex items-center justify-center text-[10px]">
              {icons[ev.event_type] || "•"}
            </div>
            <div className="glass-card p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">{ev.description}</p>
                <span className="text-[10px] text-slate-500">{ev.created_at}</span>
              </div>
              <p className="text-[10px] text-cyan-500 mt-1">{ev.event_type}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Report ───────────────────────────────────────────
function ReportView({ investigation, setMessage }: { investigation: InvestigationDetail | null; setMessage: (m: string) => void }) {
  const [generating, setGenerating] = useState(false);
  const [reportReady, setReportReady] = useState(false);

  if (!investigation) return <p className="text-slate-500">Select an investigation first.</p>;

  const generate = async () => {
    setGenerating(true);
    try {
      await axios.get(`${API}/api/investigation/${investigation.id}/report`);
      setReportReady(true);
      setMessage("✅ Report generated successfully!");
    } catch { setMessage("❌ Report generation failed."); }
    finally { setGenerating(false); }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Forensic Report — INV#{investigation.id}</h1>
      
      {/* Report Preview */}
      <div className="glass-card p-6 mb-6 max-w-2xl">
        <h2 className="text-lg font-semibold mb-4">Report Preview</h2>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between"><span className="text-slate-400">Investigation ID:</span><span>{investigation.id}</span></div>
          <div className="flex justify-between"><span className="text-slate-400">File:</span><span>{investigation.filename}</span></div>
          <div className="flex justify-between"><span className="text-slate-400">Media Type:</span><span>{investigation.media_type}</span></div>
          <div className="flex justify-between"><span className="text-slate-400">Risk Level:</span><span><RiskBadge level={investigation.risk_level} /></span></div>
          <div className="flex justify-between"><span className="text-slate-400">Status:</span><span><StatusBadge status={investigation.status} /></span></div>
          <div><span className="text-slate-400">SHA-256:</span><p className="font-mono text-xs break-all mt-1">{investigation.sha256_hash}</p></div>
        </div>
        
        <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-300">
          ⚠️ DISCLAIMER: This report is an analytical aid and evidence-preparation artifact. Model outputs are not by themselves proof of identity, manipulation, authorship, or criminal conduct.
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={generate} disabled={generating} className="px-6 py-3 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-semibold text-sm hover:opacity-90 transition disabled:opacity-50">
          {generating ? "⏳ Generating..." : "📄 Generate PDF Report"}
        </button>
        {reportReady && (
          <a href={`${API}/api/report/${investigation.id}/download`} target="_blank" rel="noopener noreferrer" className="px-6 py-3 rounded-lg bg-emerald-500/20 text-emerald-400 font-semibold text-sm border border-emerald-500/30 hover:bg-emerald-500/30 transition">
            ⬇ Download Report
          </a>
        )}
      </div>
    </div>
  );
}

// ─── Shared Components ────────────────────────────────
function RiskBadge({ level, large }: { level: string | null; large?: boolean }) {
  const colors: Record<string, string> = {
    CRITICAL: "bg-red-500/20 text-red-400 border-red-500/30",
    HIGH: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    MEDIUM: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    LOW: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    MINIMAL: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  if (!level) return <span className={`${large ? "text-sm px-3 py-1" : "text-xs px-2 py-0.5"} rounded border bg-slate-500/20 text-slate-500 border-slate-500/30`}>PENDING</span>;
  return <span className={`${large ? "text-sm px-3 py-1 font-bold" : "text-xs px-2 py-0.5"} rounded border ${colors[level] || colors.MINIMAL}`}>{level}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-slate-500/20 text-slate-400",
    analyzing: "bg-cyan-500/20 text-cyan-400 animate-pulse",
    completed: "bg-emerald-500/20 text-emerald-400",
    failed: "bg-red-500/20 text-red-400",
  };
  return <span className={`text-xs px-2 py-0.5 rounded ${colors[status] || "bg-slate-500/20 text-slate-400"}`}>{status}</span>;
}
