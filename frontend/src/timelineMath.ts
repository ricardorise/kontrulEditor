import type { Clip, TimelineDoc } from "./types";

export const fmtTime = (ms: number, decimals = 1): string => {
  const neg = ms < 0; const a = Math.abs(ms);
  const m = Math.floor(a / 60000), s = (a % 60000) / 1000;
  return `${neg ? "-" : ""}${String(m).padStart(2, "0")}:${s.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0")}`;
};

export const mainClips = (doc: TimelineDoc): Clip[] =>
  doc.clips.filter((c) => c.track_id === "main").sort((a, b) => a.timeline_start_ms - b.timeline_start_ms);

export const overlayClips = (doc: TimelineDoc): Clip[] =>
  doc.clips.filter((c) => c.track_id !== "main").sort((a, b) => a.track_id.localeCompare(b.track_id) || a.timeline_start_ms - b.timeline_start_ms);

/** Tempo de origem → tempo de saída; null se o trecho foi cortado. */
export function sourceToOutput(doc: TimelineDoc, assetId: string, ms: number): number | null {
  for (const c of mainClips(doc)) {
    if (c.asset_id === assetId && c.source_in_ms <= ms && ms < c.source_out_ms) return c.timeline_start_ms + ms - c.source_in_ms;
  }
  return null;
}

export function outputToSource(doc: TimelineDoc, ms: number): { assetId: string; ms: number } | null {
  for (const c of mainClips(doc)) {
    if (c.timeline_start_ms <= ms && ms < c.timeline_start_ms + c.duration_ms) return { assetId: c.asset_id, ms: c.source_in_ms + ms - c.timeline_start_ms };
  }
  return null;
}

/** Lacunas (trechos de origem removidos) do asset principal, em ordem. */
export function removedRanges(doc: TimelineDoc, assetId: string, durationMs: number): [number, number][] {
  const kept = mainClips(doc).filter((c) => c.asset_id === assetId).sort((a, b) => a.source_in_ms - b.source_in_ms);
  const out: [number, number][] = [];
  let t = 0;
  for (const c of kept) {
    if (c.source_in_ms > t) out.push([t, c.source_in_ms]);
    t = Math.max(t, c.source_out_ms);
  }
  if (t < durationMs) out.push([t, durationMs]);
  return out;
}

/** Quanto do intervalo [s,e) ainda está na timeline (0..1). */
export function keptFraction(doc: TimelineDoc, assetId: string, s: number, e: number): number {
  let kept = 0;
  for (const c of mainClips(doc)) {
    if (c.asset_id !== assetId) continue;
    kept += Math.max(0, Math.min(e, c.source_out_ms) - Math.max(s, c.source_in_ms));
  }
  return e > s ? kept / (e - s) : 0;
}

/** Reprodução do editado: se `t` caiu num corte, devolve onde pular (início do próximo clip) ou null no fim. */
export function nextKept(doc: TimelineDoc, assetId: string, t: number): { inKept: boolean; jumpTo: number | null } {
  let next: number | null = null;
  for (const c of mainClips(doc)) {
    if (c.asset_id !== assetId) continue;
    if (c.source_in_ms <= t && t < c.source_out_ms) return { inKept: true, jumpTo: null };
    if (c.source_in_ms > t && (next === null || c.source_in_ms < next)) next = c.source_in_ms;
  }
  return { inKept: false, jumpTo: next };
}

export function snap(value: number, candidates: number[], thresholdMs: number): number {
  let best = value, bestD = thresholdMs;
  for (const c of candidates) {
    const d = Math.abs(c - value);
    if (d <= bestD) { best = c; bestD = d; }
  }
  return best;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
