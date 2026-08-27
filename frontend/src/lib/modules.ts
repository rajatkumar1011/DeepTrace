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
