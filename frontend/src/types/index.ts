export interface DashboardStats {
  active_investigations: number;
  evidence_items: number;
  high_risk_findings: number;
  protected_identities: number;
}

export interface IdentityItem {
  id: number;
  name: string;
  face_enrolled: boolean;
  voice_enrolled: boolean;
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

export interface AnalysisModule {
  score: number | null;
  confidence: number | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface EvidenceItem {
  id: number;
  type: string;
  file_path: string;
  sha256: string | null;
  perceptual_hash: string | null;
  timestamp_offset: number | null;
}

export interface InvestigationDetail extends InvestigationItem {
  file_path: string;
  file_size_bytes: number;
  sha256_hash: string;
  duration_seconds: number | null;
  resolution: string | null;
  fps: number | null;
  frames_extracted: number | null;
  overall_risk_score: number | null;
  analysis_results: Record<string, AnalysisModule>;
  evidence: EvidenceItem[];
}

export interface TimelineEvent {
  id: number;
  event_type: string;
  description: string;
  created_at: string;
}

export type ViewKey = "home" | "start" | "cases" | "case" | "help";
