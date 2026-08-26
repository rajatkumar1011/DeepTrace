export const APP = {
  name: "DeepTrace",
  descriptor: "Digital Impersonation Evidence Assistance",
  team: "Team Algorythm · SIH26_28",
  prototypeNotice: "Hackathon prototype — not an official Government of India portal",
} as const;

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export const API_PATHS = {
  health: "/api/health",
  stats: "/api/dashboard/stats",
  consentText: "/api/consent-text",
  identities: "/api/identities",
  enrollIdentity: "/api/identity/enroll",
  investigate: "/api/investigate",
  investigations: "/api/investigations",
  investigation: (id: number) => `/api/investigation/${id}`,
  analyze: (id: number) => `/api/investigation/${id}/analyze`,
  timeline: (id: number) => `/api/investigation/${id}/timeline`,
  evidence: (id: number) => `/api/investigation/${id}/evidence`,
  verify: (id: number) => `/api/investigation/${id}/verify`,
  custody: (id: number) => `/api/investigation/${id}/custody`,
  trace: (id: number) => `/api/investigation/${id}/trace`,
  guidance: (id: number) => `/api/investigation/${id}/response-guidance`,
  report: (id: number) => `/api/investigation/${id}/report`,
  reportDownload: (id: number) => `/api/report/${id}/download`,
  demoAssets: "/api/demo/assets",
} as const;

export const EXTERNAL_LINKS = {
  cybercrimePortal: "https://cybercrime.gov.in/",
  indiaPortal: "https://www.india.gov.in/",
} as const;

export const ACCEPTED_MEDIA = {
  suspicious: "image/*,video/*,audio/*",
  image: "image/*",
  audio: "audio/*",
} as const;

export const ANALYSIS_POLL_INTERVAL_MS = 3000;

export const NAV_ITEMS = [
  { key: "home", label: "Home" },
  { key: "start", label: "Start evidence collection" },
  { key: "cases", label: "My cases" },
  { key: "help", label: "How it works" },
] as const;

export const RISK_COPY: Record<string, { label: string; tone: "danger" | "warning" | "safe" | "neutral"; description: string }> = {
  CRITICAL: {
    label: "Critical indicators",
    tone: "danger",
    description: "Multiple forensic signals need careful review. Preserve the evidence and consider reporting promptly.",
  },
  HIGH: {
    label: "High indicators",
    tone: "danger",
    description: "Strong forensic indicators were found. Review the evidence package before taking action.",
  },
  MEDIUM: {
    label: "Some indicators",
    tone: "warning",
    description: "Some signals deserve review, but the result is not proof by itself.",
  },
  LOW: {
    label: "Low indicators",
    tone: "safe",
    description: "Few suspicious signals were found in this analysis. Keep the preserved evidence if you still need to report the incident.",
  },
  MINIMAL: {
    label: "Minimal indicators",
    tone: "safe",
    description: "Very few suspicious signals were found. This does not rule out misuse or impersonation.",
  },
};

export const MODULE_LABELS: Record<string, { title: string; plain: string; inverse?: boolean }> = {
  deepfake: {
    title: "Manipulation indicators",
    plain: "Checks whether the media contains visual signs commonly associated with synthetic or altered content.",
  },
  identity: {
    title: "Face identity match",
    plain: "Compares the suspicious media with the reference identity you provided.",
  },
  voice: {
    title: "Voice identity match",
    plain: "Compares available speech with the reference voice sample, when one is available.",
  },
  audio: {
    title: "Audio editing indicators",
    plain: "Looks for abrupt level changes, clipping and re-encoding traces in the audio track.",
  },
  consistency: {
    title: "Audio-video consistency",
    plain: "Checks whether visual and audio activity appear broadly aligned. Higher consistency is generally less suspicious.",
    inverse: true,
  },
  provenance: {
    title: "Content provenance",
    plain: "Checks whether Content Credentials or other provenance information is available.",
  },
  similarity: {
    title: "Known-copy similarity",
    plain: "Looks for exact or perceptually similar evidence already preserved in this local DeepTrace database.",
  },
};

/** Module status values the backend reports, and how to describe each honestly. */
export const MODULE_STATUS_COPY: Record<string, { label: string; tone: "ok" | "muted" | "warn" }> = {
  completed: { label: "Completed", tone: "ok" },
  not_applicable: { label: "Not applicable", tone: "muted" },
  unavailable: { label: "Unavailable", tone: "warn" },
  no_credentials: { label: "None present", tone: "muted" },
  failed: { label: "Error", tone: "warn" },
  not_run: { label: "Not run", tone: "muted" },
};

export const INTEGRITY_COPY: Record<string, { label: string; tone: "ok" | "warn" | "muted" }> = {
  verified: { label: "Verified", tone: "ok" },
  mismatch: { label: "Hash mismatch", tone: "warn" },
  missing: { label: "File missing", tone: "warn" },
  no_recorded_hash: { label: "No recorded hash", tone: "muted" },
};

/**
 * Who DeepTrace is for, stated rather than implied.
 *
 * The interface is written for the person the impersonation happened to, because
 * they are the one under pressure and the one who has to decide what to do next.
 * The exported report is written for the officer who receives it. Naming both,
 * and saying which surface belongs to which, stops a reader assuming a screen
 * was meant for someone else.
 */
export const PRIMARY_USER = {
  primary: {
    role: "The person being impersonated",
    also: "the complainant",
    statement:
      "DeepTrace is built first for the person whose face or voice was misused. Every screen here is written for you, in plain language, with no forensic vocabulary you have to learn first.",
  },
  secondary: {
    role: "The cybercrime investigator or forensic examiner",
    also: "who receives your report",
    statement:
      "The case view and the exported PDF are written for the officer handling your complaint: full digests, per-module findings, the chain of custody, the methods used and the limits of each one — in the order an investigator needs them.",
  },
  readsWhat: [
    {
      who: "You, the person affected",
      reads: "The plain-language findings, the risk explanation and the next-steps page.",
      why: "So you can understand what was found and decide whether to report it, without needing a forensics background.",
    },
    {
      who: "The investigating officer",
      reads: "The exported PDF — 22 sections covering the evidence register with full hash values, the chain of custody, every module's method and its stated limitations.",
      why: "So the case can be assessed and taken forward on the record, not on a screenshot of a score.",
    },
    {
      who: "Neither of you",
      reads: "A verdict. DeepTrace does not decide whether media is genuine or fake.",
      why: "That determination belongs to a qualified examiner and, ultimately, to a court.",
    },
  ],
} as const;
