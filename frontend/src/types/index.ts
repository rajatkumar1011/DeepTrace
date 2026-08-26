export interface DashboardStats {
  active_investigations: number;
  evidence_items: number;
  high_risk_findings: number;
  protected_identities: number;
}

export interface HealthPayload {
  status: string;
  service: string;
  version: string;
  capabilities: Record<string, boolean>;
  limits: { max_upload_mb: number; max_reference_mb: number; frame_samples: number };
  note: string;
}

export interface ConsentText {
  version: string;
  text: string;
}

export interface IdentityItem {
  id: number;
  name: string;
  face_enrolled: boolean;
  voice_enrolled: boolean;
  consent_given?: boolean;
  consent_at?: string | null;
  consent_version?: string | null;
  face_model?: string | null;
  face_embedding_dimensions?: number | null;
  reference_image_path?: string | null;
  created_at: string;
}

export interface InvestigationItem {
  id: number;
  filename: string;
  media_type: string;
  status: string;
  risk_level: string | null;
  created_at: string;
  identity_id: number | null;
  overall_risk_score?: number | null;
}

/** One module's output. `status` distinguishes a real result from an honest gap. */
export interface AnalysisModule {
  score: number | null;
  confidence: number | null;
  status: string;
  data: Record<string, unknown> | null;
  created_at: string | null;
}

export interface EvidenceItem {
  id: number;
  type: string;
  file_path: string | null;
  url: string | null;
  filename: string;
  sha256: string | null;
  perceptual_hash: string | null;
  timestamp_offset: number | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

export interface TraceSource {
  id: number;
  source_url: string | null;
  title: string | null;
  description: string | null;
  origin: string | null;
  retrieval_status: string | null;
  retrieval_error: string | null;
  file_path: string | null;
  url: string | null;
  content_type: string | null;
  bytes_downloaded: number | null;
  sha256: string | null;
  perceptual_hash: string | null;
  similarity: number | null;
  match_type: string | null;
  similarity_label: string | null;
  details: Record<string, unknown> | null;
  discovered_at: string | null;
}

export interface TracePayload {
  investigation_id: number;
  source_count: number;
  retrieved_count: number;
  sources: TraceSource[];
  scope: string;
}

export interface IntegrityArtifact {
  evidence_id: number;
  evidence_type: string;
  label: string;
  public_path: string | null;
  timestamp_offset: number | null;
  preserved_at: string | null;
  status: "verified" | "mismatch" | "missing" | "no_recorded_hash" | string;
  recorded_sha256: string | null;
  current_sha256: string | null;
  detail: string;
}

export interface IntegrityReport {
  investigation_id: number;
  verified_at: string;
  algorithm: string;
  artifacts_checked: number;
  counts: { verified: number; mismatch: number; missing: number; no_recorded_hash: number };
  chain_intact: boolean;
  summary: string;
  artifacts: IntegrityArtifact[];
  method: string;
  limitations: string;
}

/** One statement from the custody boundary lists, with the basis for it. */
export interface CustodyClaim {
  claim: string;
  detail: string;
}

export interface CustodyGap {
  gap: string;
  detail: string;
}

export interface CustodyLedgerEntry {
  evidence_id: number;
  evidence_type: string | null;
  origin: "acquired" | "derived" | string;
  role: string;
  role_detail: string;
  preserved_at: string | null;
  timestamp_offset: number | null;
  sha256: string | null;
  digest_recorded: boolean;
}

export interface CustodyRecord {
  investigation_id: number;
  custody_scope: {
    definition: string;
    deeptrace_supplies: string[];
    investigator_supplies: string[];
    statement: string;
  };
  acquisition: {
    case_reference: string;
    submitted_filename: string | null;
    media_type: string | null;
    file_size_bytes: number | null;
    received_at: string | null;
    algorithm: string;
    sha256: string | null;
    perceptual_hash: string | null;
    hash_binding: string;
    derived_hash_binding: string;
    type_determination: string;
    filename_note: string;
    clock_source: string;
  };
  derivation_note: string;
  artifact_ledger: CustodyLedgerEntry[];
  counts: { artifacts: number; acquired: number; derived: number; without_digest: number };
  chronology: { sequence: number; event_type: string; description: string; recorded_at: string | null }[];
  chronology_note: string;
  integrity_check: {
    verified_at: string | null;
    algorithm: string | null;
    artifacts_checked: number | null;
    chain_intact: boolean | null;
    summary: string | null;
    counts: IntegrityReport["counts"] | null;
    method: string | null;
    limitations: string | null;
  };
  hashing_proves: CustodyClaim[];
  hashing_does_not_prove: CustodyClaim[];
  ai_establishes: CustodyClaim[];
  ai_does_not_establish: CustodyClaim[];
  custody_gaps: CustodyGap[];
  boundary_summary: string;
}

export interface GuidanceAction {
  step: number;
  action: string;
  why: string;
  who_acts: string;
  deeptrace_role: string;
}

export interface ReportingRoute {
  route: string;
  detail: string;
  who_acts: string;
}

export interface ResponseGuidance {
  investigation_id: number;
  generated_at: string;
  priority: string;
  risk_level: string | null;
  case_findings: string[];
  recommended_actions: GuidanceAction[];
  evidence_package: string[];
  reporting_routes: ReportingRoute[];
  deeptrace_boundary: string;
  caveats: string[];
}

export interface InvestigationDetail extends InvestigationItem {
  file_path: string | null;
  media_url: string | null;
  file_size_bytes: number;
  sha256_hash: string;
  perceptual_hash: string | null;
  progress_stage: string | null;
  progress_percent: number | null;
  error_message: string | null;
  identity_name: string | null;
  duration_seconds: number | null;
  resolution: string | null;
  fps: number | null;
  frames_extracted: number | null;
  has_audio_stream: boolean | null;
  media_metadata: Record<string, unknown> | null;
  source_urls: string[];
  overall_risk_score: number | null;
  analysis_started_at: string | null;
  analysis_completed_at: string | null;
  analysis_results: Record<string, AnalysisModule>;
  evidence: EvidenceItem[];
  trace_sources: TraceSource[];
  report_available: boolean;
}

export interface TimelineEvent {
  id: number;
  event_type: string;
  description: string;
  created_at: string;
}

export interface DemoAsset {
  filename: string;
  media_type: string;
  size_bytes: number;
  url: string;
}

export interface DemoAssets {
  available: boolean;
  count: number;
  assets: DemoAsset[];
  note: string;
}

export type ViewKey = "home" | "start" | "cases" | "case" | "help";
