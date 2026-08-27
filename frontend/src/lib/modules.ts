/**
 * Typed readers for analysis-module payloads.
 *
 * Module `data` is deliberately `Record<string, unknown>` — the backend adds
 * fields as detectors evolve, and the UI must not crash on a shape it has not
 * seen. Every reader here returns a nullable value rather than throwing, so a
 * missing field renders as "not available" instead of blanking the page.
 */
import type { AnalysisModule, InvestigationDetail } from "@/types";

export function moduleOf(investigation: InvestigationDetail | null, key: string): AnalysisModule | null {
  return investigation?.analysis_results?.[key] ?? null;
}

export function dataOf(investigation: InvestigationDetail | null, key: string): Record<string, unknown> {
  return moduleOf(investigation, key)?.data ?? {};
}

export function num(source: Record<string, unknown> | undefined, key: string): number | null {
  const value = source?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function str(source: Record<string, unknown> | undefined, key: string): string | null {
  const value = source?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function bool(source: Record<string, unknown> | undefined, key: string): boolean | null {
  const value = source?.[key];
  return typeof value === "boolean" ? value : null;
}

export function rows(source: Record<string, unknown> | undefined, key: string): Record<string, unknown>[] {
  const value = source?.[key];
  return Array.isArray(value) ? (value.filter((item) => typeof item === "object" && item !== null) as Record<string, unknown>[]) : [];
}

export function strings(source: Record<string, unknown> | undefined, key: string): string[] {
  const value = source?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function nested(source: Record<string, unknown> | undefined, key: string): Record<string, unknown> {
  const value = source?.[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** MM:SS.ss, matching the labels used in the PDF report. */
export function clock(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const whole = Math.floor(seconds);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${(seconds - Math.floor(whole / 60) * 60).toFixed(2).padStart(5, "0")}`;
}

/** A module produced a usable result only when it says so. */
export function hasResult(module: AnalysisModule | null) {
  return module?.status === "completed";
}

/**
 * The provenance estimator's own outcome, read from its own sub-payload.
 *
 * The `provenance` module records two independent checks under one key: the
 * Content Credentials read at the top level, and the reverse-image source
 * estimate under `external_search`. The module status the backend stores
 * describes only the first one — it is `no_credentials` for nearly every real
 * file — so any surface that badged the estimator with that status would label a
 * case holding ten located pages and two verified matches "None present".
 * Both the findings card and the metadata panel read the estimate from here, so
 * the two cannot drift apart.
 *
 * `found` and `matched` stay separate numbers on purpose. A page returned by the
 * index is a lead; only a page whose served media matched this file on
 * DeepTrace's own hash and face comparison is a match. Collapsing them would let
 * an index's guess read as a forensic finding.
 */
export function provenanceEstimate(data: Record<string, unknown> | null | undefined) {
  const search = nested(data ?? undefined, "external_search");
  const status = str(search, "status");
  const found = num(search, "sources_discovered") ?? 0;
  const matched = num(search, "sources_verified") ?? 0;

  let label: string;
  let tone: "ok" | "muted" | "warn";
  switch (status) {
    case "completed":
      label = `${found} found · ${matched} matched`;
      tone = matched > 0 ? "ok" : "muted";
      break;
    case "no_sources":
      label = "No copies located";
      tone = "muted";
      break;
    case "discovered_only":
      label = `${found} found · not verified`;
      tone = "warn";
      break;
    case "not_configured":
      label = "Search not configured";
      tone = "muted";
      break;
    case "failed":
      label = "Search failed";
      tone = "warn";
      break;
    default:
      label = "Not run";
      tone = "muted";
  }
  return { search, status, found, matched, label, tone };
}
