export function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatBytes(bytes?: number | null) {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(2)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

export function formatPercent(score?: number | null) {
  if (score === null || score === undefined || Number.isNaN(score)) return "Not available";
  return `${Math.round(score * 100)}%`;
}

export function shortHash(hash?: string | null) {
  if (!hash) return "—";
  return hash.length > 24 ? `${hash.slice(0, 12)}…${hash.slice(-8)}` : hash;
}
