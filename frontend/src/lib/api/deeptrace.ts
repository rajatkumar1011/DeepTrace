import { API_PATHS } from "@/config/constants";
import type {
  DashboardStats,
  IdentityItem,
  InvestigationDetail,
  InvestigationItem,
  TimelineEvent,
} from "@/types";
import { api } from "./client";

export async function getDashboardStats() {
  return (await api.get<DashboardStats>(API_PATHS.stats)).data;
}

export async function getIdentities() {
  return (await api.get<IdentityItem[]>(API_PATHS.identities)).data;
}

export async function enrollIdentity(input: {
  name: string;
  referenceImage: File;
  referenceAudio?: File | null;
}) {
  const form = new FormData();
  form.append("name", input.name);
  form.append("reference_image", input.referenceImage);
  if (input.referenceAudio) form.append("reference_audio", input.referenceAudio);
  return (await api.post<IdentityItem>(API_PATHS.enrollIdentity, form)).data;
}

export async function getInvestigations() {
  return (await api.get<InvestigationItem[]>(API_PATHS.investigations)).data;
}

export async function createInvestigation(input: { file: File; identityId?: number | null }) {
  const form = new FormData();
  form.append("file", input.file);
  if (input.identityId) form.append("identity_id", String(input.identityId));
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

export async function generateReport(id: number) {
  return (await api.get(API_PATHS.report(id))).data;
}
