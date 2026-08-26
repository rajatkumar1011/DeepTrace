import { API_PATHS } from "@/config/constants";
import type {
  BenchmarkPayload,
  CaseSubmitterReceipt,
  ConsentText,
  CustodyRecord,
  DashboardStats,
  DemoAssets,
  EvidenceItem,
  HealthPayload,
  IdentityItem,
  IntegrityReport,
  InvestigationDetail,
  InvestigationItem,
  ResponseGuidance,
  TimelineEvent,
  TracePayload,
} from "@/types";
import { api } from "./client";

export async function getHealth() {
  return (await api.get<HealthPayload>(API_PATHS.health)).data;
}

export async function getDashboardStats() {
  return (await api.get<DashboardStats>(API_PATHS.stats)).data;
}

export async function getConsentText() {
  return (await api.get<ConsentText>(API_PATHS.consentText)).data;
}

export async function getIdentities() {
  return (await api.get<IdentityItem[]>(API_PATHS.identities)).data;
}

/**
 * Enroll a reference identity. `consentGiven` is mandatory: the backend refuses
 * enrollment without it (HTTP 422), because a biometric reference is only taken
 * with a recorded consent decision.
 */
export async function enrollIdentity(input: {
  name: string;
  referenceImage: File;
  referenceAudio?: File | null;
  consentGiven: boolean;
}) {
  const form = new FormData();
  form.append("name", input.name);
  form.append("consent_given", String(input.consentGiven));
  form.append("reference_image", input.referenceImage);
  if (input.referenceAudio) form.append("reference_audio", input.referenceAudio);
  return (await api.post<IdentityItem>(API_PATHS.enrollIdentity, form)).data;
}

export async function getInvestigations() {
  return (await api.get<InvestigationItem[]>(API_PATHS.investigations)).data;
}

/** Record self-declared submitter details before an investigation is opened. */
export async function createCaseSubmitter(input: {
  fullName: string;
  aadhaarNumber: string;
  gender: string;
  dateOfBirth: string;
  phoneNumber: string;
}) {
  const form = new FormData();
  form.append("full_name", input.fullName.trim());
  form.append("aadhaar_number", input.aadhaarNumber.replace(/\D/g, ""));
  form.append("gender", input.gender);
  form.append("date_of_birth", input.dateOfBirth);
  form.append("phone_number", input.phoneNumber.replace(/\D/g, ""));
  return (await api.post<CaseSubmitterReceipt>(API_PATHS.submitter, form)).data;
}

export async function createInvestigation(input: {
  file: File;
  submitterId: number;
  identityId?: number | null;
  sourceUrls?: string;
}) {
  const form = new FormData();
  form.append("file", input.file);
  form.append("submitter_id", String(input.submitterId));
  if (input.identityId) form.append("identity_id", String(input.identityId));
  if (input.sourceUrls?.trim()) form.append("source_urls", input.sourceUrls.trim());
  return (
    await api.post<{ id: number; status: string; media_type: string; sha256?: string }>(
      API_PATHS.investigate,
      form,
    )
  ).data;
}

export async function getInvestigation(id: number) {
  return (await api.get<InvestigationDetail>(API_PATHS.investigation(id))).data;
}

export async function startAnalysis(id: number) {
  return (await api.post(API_PATHS.analyze(id))).data;
}

export async function getTimeline(id: number) {
  return (await api.get<TimelineEvent[]>(API_PATHS.timeline(id))).data;
}

export async function getEvidence(id: number) {
  return (await api.get<EvidenceItem[]>(API_PATHS.evidence(id))).data;
}

/** Re-hash every preserved artifact server-side and compare with the record. */
export async function verifyEvidence(id: number) {
  return (await api.get<IntegrityReport>(API_PATHS.verify(id))).data;
}

/**
 * The chain-of-custody record: acquisition, artifact lineage, chronology and the
 * explicit boundary between what the hash proves and what the analysis
 * establishes. A read-only view — unlike `verifyEvidence`, it appends no event.
 */
export async function getCustodyRecord(id: number) {
  return (await api.get<CustodyRecord>(API_PATHS.custody(id))).data;
}

/**
 * Attach a copy for comparison — either a public HTTPS URL DeepTrace fetches
 * itself, or a file the investigator already holds. URL retrieval is validated
 * server-side; private, loopback and non-HTTPS targets are refused.
 *
 * There is no matching `getTrace` reader: the investigation detail response
 * already carries the full `trace_sources` list, so a separate GET would be a
 * second round trip for data the caller is holding. `GET .../trace` still
 * exists server-side for API clients that want sources without the whole case.
 */
export async function addTraceSource(
  id: number,
  input: { sourceUrls?: string; localCopy?: File | null; label?: string },
) {
  const form = new FormData();
  if (input.sourceUrls?.trim()) form.append("source_urls", input.sourceUrls.trim());
  if (input.localCopy) form.append("local_copy", input.localCopy);
  if (input.label?.trim()) form.append("label", input.label.trim());
  return (await api.post<{ investigation_id: number; processed: number; sources: TracePayload["sources"] }>(
    API_PATHS.trace(id),
    form,
    { timeout: 90000 },
  )).data;
}

export async function getResponseGuidance(id: number) {
  return (await api.get<ResponseGuidance>(API_PATHS.guidance(id))).data;
}

export async function generateReport(id: number) {
  return (await api.get<{ status: string; report_path: string | null; filename: string; sha256: string }>(
    API_PATHS.report(id),
    { timeout: 180000 },
  )).data;
}

export async function getDemoAssets() {
  return (await api.get<DemoAssets>(API_PATHS.demoAssets)).data;
}

/**
 * The stored validation runs. Both halves can be absent independently, and the
 * payload carries its own reason when they are — DeepTrace ships no pre-computed
 * accuracy figures, so an empty response is the correct answer on a machine where
 * neither harness has been run.
 */
export async function getBenchmark() {
  return (await api.get<BenchmarkPayload>(API_PATHS.benchmark)).data;
}
