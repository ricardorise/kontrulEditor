import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clamp, fmtTime, mainClips, outputToSource, overlayClips, removedRanges, snap } from "../timelineMath";
import type { Asset, Category, Suggestion, TimelineDoc, Waveform } from "../types";

export interface View { startMs: number; msPerPx: number }
export const CAT: Record<Category, { color: string; label: string; short: string }> = {
  speech_error: { color: "#e5484d", label: "Erro de fala", short: "ERRO" },
  off_script: { color: "#f5c542", label: "Fora do roteiro", short: "FORA" },
  repetition: { color: "#9d7bff", label: "Repetição", short: "REPET" },
  valid: { color: "#3dd68c", label: "Trecho válido", short: "OK" },
};

const LANE = { ruler: 26, sugg: 36, clips: 40, wave: 54, overlay: 26, gap: 4 };
const STEPS = [100, 200, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000, 600000, 1800000];
const EDGE = 6;

interface Props {
  main: Asset; doc: TimelineDoc | null; suggestions: Suggestion[]; selectedId: string | null; playhead: number; view: View;
  waveform?: Waveform; snapPoints: number[]; assets: Asset[];
  onView: (v: View) => void; onSeek: (ms: number) => void; onSelect: (id: string | null) => void;
  onAdjust: (id: string, start: number, end: number) => void; onDropAsset: (assetId: string, sourceMs: number) => void;
}

export function Timeline(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 800, h: 240 });
  const [draft, setDraft] = useState<{ id: string; start: number; end: number } | null>(null);
  const drag = useRef<null | { kind: "scrub" } | { kind: "edge"; id: string; side: "start" | "end"; start: number; end: number }>(null);
  const dur = p.main.duration_ms ?? 0;
  const overlays = useMemo(() => (p.doc ? overlayClips(p.doc) : []), [p.doc]);
  const tracks = useMemo(() => [...new Set(overlays.map((c) => c.track_id))], [overlays]);
  const height = LANE.ruler + LANE.sugg + LANE.clips + LANE.wave + (tracks.length || 1) * LANE.overlay + 7 * LANE.gap;
  const lanes = useMemo(() => {
    let y = 0; const out: Record<string, number> = {};
    for (const [k, h] of [["ruler", LANE.ruler], ["sugg", LANE.sugg], ["clips", LANE.clips], ["wave", LANE.wave]] as const) { out[k] = y; y += h + LANE.gap; }
    out.overlay = y; return out;
  }, []);

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.max(300, Math.floor(e.contentRect.width)), h: height }));
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [height]);

  const xOf = useCallback((ms: number) => (ms - p.view.startMs) / p.view.msPerPx, [p.view]);
  const msOf = useCallback((x: number) => p.view.startMs + x * p.view.msPerPx, [p.view]);
  const shown = (s: Suggestion) => (draft && draft.id === s.id ? { ...s, start_ms: draft.start, end_ms: draft.end } : s);

  // ---- desenho
  useEffect(() => {
    const cv = canvas.current; if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = size.w * dpr; cv.height = size.h * dpr;
    const g = cv.getContext("2d")!; g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(cv);
    const col = (n: string) => css.getPropertyValue(n).trim();
    g.clearRect(0, 0, size.w, size.h);
    g.font = "11px system-ui, sans-serif"; g.textBaseline = "middle";

    // régua
    const step = STEPS.find((s) => s / p.view.msPerPx >= 80) ?? STEPS[STEPS.length - 1];
    g.fillStyle = col("--panel-2"); g.fillRect(0, lanes.ruler, size.w, LANE.ruler);
    g.strokeStyle = col("--border"); g.fillStyle = col("--muted");
    for (let t = Math.ceil(p.view.startMs / step) * step; t < msOf(size.w); t += step) {
      const x = Math.round(xOf(t)) + 0.5;
      g.beginPath(); g.moveTo(x, lanes.ruler + 12); g.lineTo(x, lanes.ruler + LANE.ruler); g.stroke();
      g.fillText(fmtTime(t, step < 1000 ? 1 : 0), x + 3, lanes.ruler + 8);
    }
    // legenda das trilhas
    const hatch = makeHatch(g, col("--muted"));
    const laneBg = (y: number, h: number) => { g.fillStyle = col("--panel"); g.fillRect(0, y, size.w, h); };
    laneBg(lanes.sugg, LANE.sugg); laneBg(lanes.clips, LANE.clips); laneBg(lanes.wave, LANE.wave);
    for (let i = 0; i < Math.max(1, tracks.length); i++) laneBg(lanes.overlay + i * (LANE.overlay + LANE.gap), LANE.overlay);

    // cortes (lacunas) e clips mantidos
    if (p.doc) {
      g.fillStyle = col("--clip"); g.strokeStyle = col("--clip-border");
      for (const c of mainClips(p.doc)) {
        const x0 = xOf(c.source_in_ms), x1 = xOf(c.source_out_ms);
        if (x1 < 0 || x0 > size.w) continue;
        g.fillRect(x0, lanes.clips, x1 - x0, LANE.clips); g.strokeRect(x0 + 0.5, lanes.clips + 0.5, x1 - x0 - 1, LANE.clips - 1);
        if (x1 - x0 > 70) { g.fillStyle = col("--text"); g.fillText(`vídeo · saída ${fmtTime(c.timeline_start_ms, 0)}`, Math.max(x0, 0) + 6, lanes.clips + LANE.clips / 2); g.fillStyle = col("--clip"); }
      }
      for (const [a, b] of removedRanges(p.doc, p.main.id, dur)) {
        const x0 = xOf(a), x1 = xOf(b);
        if (x1 < 0 || x0 > size.w) continue;
        g.fillStyle = hatch; g.fillRect(x0, lanes.clips, x1 - x0, LANE.clips);
        g.strokeStyle = col("--muted"); g.strokeRect(x0 + 0.5, lanes.clips + 0.5, x1 - x0 - 1, LANE.clips - 1);
        if (x1 - x0 > 50) { g.fillStyle = col("--text"); g.fillText("cortado", Math.max(x0, 0) + 6, lanes.clips + LANE.clips / 2); }
      }
    } else {
      g.fillStyle = col("--panel-2"); g.fillRect(xOf(0), lanes.clips, xOf(dur) - xOf(0), LANE.clips);
      g.fillStyle = col("--muted"); g.fillText("Inicie a edição para criar a timeline", Math.max(xOf(0), 0) + 8, lanes.clips + LANE.clips / 2);
    }

    // forma de onda (máximo por pixel)
    if (p.waveform?.peaks.length) {
      const { peaks, peaks_per_second: pps } = p.waveform;
      g.fillStyle = col("--wave"); const mid = lanes.wave + LANE.wave / 2;
      for (let x = 0; x < size.w; x++) {
        const i0 = Math.max(0, Math.floor((msOf(x) / 1000) * pps)), i1 = Math.min(peaks.length, Math.max(i0 + 1, Math.ceil((msOf(x + 1) / 1000) * pps)));
        if (i0 >= peaks.length) break;
        let m = 0; for (let i = i0; i < i1; i++) if (peaks[i] > m) m = peaks[i];
        const h = Math.max(1, (m / 255) * (LANE.wave - 4)); g.fillRect(x, mid - h / 2, 1, h);
      }
    }

    // overlays (posição de saída → origem)
    if (p.doc) {
      overlays.forEach((c) => {
        const s = outputToSource(p.doc!, c.timeline_start_ms); if (!s) return;
        const row = tracks.indexOf(c.track_id), y = lanes.overlay + row * (LANE.overlay + LANE.gap);
        const x0 = xOf(s.ms), x1 = xOf(s.ms + c.duration_ms);
        g.fillStyle = c.mode === "pip" ? col("--pip") : col("--broll"); g.fillRect(x0, y, Math.max(2, x1 - x0), LANE.overlay);
        g.fillStyle = "#0b0d10"; g.fillText(`${c.mode === "pip" ? "PiP" : "B-roll"} · ${p.assets.find((a) => a.id === c.asset_id)?.filename ?? ""}`, x0 + 5, y + LANE.overlay / 2);
      });
    }

    // sugestões: cor + rótulo de texto + padrão por categoria (não dependem só da cor)
    for (const s0 of p.suggestions) {
      const s = shown(s0), x0 = xOf(s.start_ms), x1 = xOf(s.end_ms);
      if (x1 < 0 || x0 > size.w) continue;
      const c = CAT[s.category], sel = s.id === p.selectedId, w = Math.max(3, x1 - x0);
      g.globalAlpha = s.status === "rejected" ? 0.3 : 1;
      g.fillStyle = c.color; g.fillRect(x0, lanes.sugg, w, LANE.sugg);
      if (s.category === "off_script") { g.fillStyle = "rgba(0,0,0,.28)"; for (let k = -LANE.sugg; k < w; k += 8) { g.beginPath(); g.moveTo(x0 + k, lanes.sugg + LANE.sugg); g.lineTo(x0 + k + LANE.sugg, lanes.sugg); g.lineTo(x0 + k + LANE.sugg + 3, lanes.sugg); g.lineTo(x0 + k + 3, lanes.sugg + LANE.sugg); g.fill(); } }
      if (s.category === "repetition") { g.fillStyle = "rgba(255,255,255,.35)"; for (let k = 4; k < w; k += 8) g.fillRect(x0 + k, lanes.sugg + 4, 2, LANE.sugg - 8); }
      g.globalAlpha = 1;
      g.fillStyle = "#0b0d10"; if (w > 48) g.fillText(`${c.short}${s.status === "accepted" || s.status === "adjusted" ? " ✓" : s.status === "rejected" ? " ✗" : ""}`, x0 + 5, lanes.sugg + LANE.sugg / 2);
      if (sel) {
        g.strokeStyle = "#fff"; g.lineWidth = 2; g.strokeRect(x0 + 1, lanes.sugg + 1, w - 2, LANE.sugg - 2); g.lineWidth = 1;
        g.fillStyle = "#fff"; g.fillRect(x0 - 2, lanes.sugg - 2, 4, LANE.sugg + 4); g.fillRect(x0 + w - 2, lanes.sugg - 2, 4, LANE.sugg + 4);
      }
    }

    // playhead
    const px = Math.round(xOf(p.playhead)) + 0.5;
    if (px >= 0 && px <= size.w) {
      g.strokeStyle = col("--accent"); g.lineWidth = 1.5; g.beginPath(); g.moveTo(px, 0); g.lineTo(px, size.h); g.stroke(); g.lineWidth = 1;
      g.fillStyle = col("--accent"); g.beginPath(); g.moveTo(px - 6, 0); g.lineTo(px + 6, 0); g.lineTo(px, 9); g.fill();
    }
  }, [p, size, draft, lanes, tracks, overlays, xOf, msOf, dur]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- zoom (Ctrl/⌘+roda) e pan (roda)
  useEffect(() => {
    const el = canvas.current; if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect(), x = e.clientX - rect.left;
      if (e.ctrlKey || e.metaKey) {
        const f = e.deltaY < 0 ? 0.8 : 1.25, anchor = msOf(x);
        const msPerPx = clamp(p.view.msPerPx * f, 2, Math.max(dur / size.w, 4));
        p.onView({ msPerPx, startMs: clamp(anchor - x * msPerPx, 0, Math.max(0, dur - size.w * msPerPx)) });
      } else {
        const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * p.view.msPerPx;
        p.onView({ ...p.view, startMs: clamp(p.view.startMs + d, 0, Math.max(0, dur - size.w * p.view.msPerPx)) });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [p.view, p.onView, dur, size.w, msOf]); // eslint-disable-line react-hooks/exhaustive-deps

  const pos = (e: { clientX: number; clientY: number }) => { const r = canvas.current!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const inSugg = (y: number) => y >= lanes.sugg - 2 && y <= lanes.sugg + LANE.sugg + 2;
  const edgeHit = (x: number, y: number) => {
    if (!inSugg(y) || !p.selectedId) return null;
    const s = p.suggestions.find((q) => q.id === p.selectedId); if (!s) return null;
    const d = shown(s);
    if (Math.abs(x - xOf(d.start_ms)) <= EDGE) return { s, side: "start" as const };
    if (Math.abs(x - xOf(d.end_ms)) <= EDGE) return { s, side: "end" as const };
    return null;
  };
  const blockAt = (x: number, y: number) => (inSugg(y) ? [...p.suggestions].reverse().find((s) => x >= xOf(s.start_ms) - 1 && x <= Math.max(xOf(s.end_ms), xOf(s.start_ms) + 3)) : undefined);

  const onDown = (e: React.PointerEvent) => {
    const { x, y } = pos(e); canvas.current!.setPointerCapture(e.pointerId);
    const eh = edgeHit(x, y);
    if (eh) { drag.current = { kind: "edge", id: eh.s.id, side: eh.side, start: eh.s.start_ms, end: eh.s.end_ms }; return; }
    const b = blockAt(x, y);
    if (b) { p.onSelect(b.id); p.onSeek(b.start_ms); return; }
    drag.current = { kind: "scrub" }; p.onSelect(null); p.onSeek(clamp(msOf(x), 0, dur));
  };
  const onMove = (e: React.PointerEvent) => {
    const { x, y } = pos(e), d = drag.current;
    if (!d) { canvas.current!.style.cursor = edgeHit(x, y) ? "col-resize" : blockAt(x, y) ? "pointer" : "crosshair"; return; }
    if (d.kind === "scrub") return p.onSeek(clamp(msOf(x), 0, dur));
    const cands = [...p.snapPoints, p.playhead, ...p.suggestions.filter((s) => s.id !== d.id).flatMap((s) => [s.start_ms, s.end_ms])];
    const v = Math.round(snap(clamp(msOf(x), 0, dur), cands, 8 * p.view.msPerPx));
    const nd = d.side === "start" ? { start: Math.min(v, d.end - 100), end: d.end } : { start: d.start, end: Math.max(v, d.start + 100) };
    drag.current = { ...d, ...nd }; setDraft({ id: d.id, ...nd });
  };
  const onUp = () => {
    const d = drag.current; drag.current = null;
    if (d?.kind === "edge" && draft) { const orig = p.suggestions.find((s) => s.id === d.id); if (orig && (orig.start_ms !== draft.start || orig.end_ms !== draft.end)) p.onAdjust(d.id, draft.start, draft.end); }
    setDraft(null);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); const id = e.dataTransfer.getData("application/x-kontrul-asset");
    if (id) p.onDropAsset(id, clamp(msOf(pos(e).x), 0, dur));
  };

  const summary = `Timeline de ${fmtTime(dur, 0)}: ${p.suggestions.length} ocorrências (${p.suggestions.filter((s) => s.category === "speech_error").length} erros, ${p.suggestions.filter((s) => s.category === "off_script").length} fora do roteiro), ${overlays.length} mídias inseridas. Use a lista de ocorrências para navegar pelo teclado.`;
  return (
    <div ref={wrap} className="timeline-wrap">
      <canvas ref={canvas} role="img" aria-label={summary} style={{ width: size.w, height: size.h, touchAction: "none" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        onDragOver={(e) => e.preventDefault()} onDrop={onDrop} />
      <div className="timeline-legend" aria-hidden="true">
        <span><i style={{ background: CAT.speech_error.color }} /> ERRO</span>
        <span><i className="hatch" style={{ background: CAT.off_script.color }} /> FORA do roteiro</span>
        <span><i style={{ background: CAT.repetition.color }} /> REPETIÇÃO</span>
        <span><i className="cut" /> cortado</span>
      </div>
    </div>
  );
}

function makeHatch(g: CanvasRenderingContext2D, color: string): CanvasPattern | string {
  const c = document.createElement("canvas"); c.width = c.height = 8;
  const x = c.getContext("2d")!; x.strokeStyle = color; x.globalAlpha = 0.6; x.lineWidth = 1.2;
  x.beginPath(); x.moveTo(0, 8); x.lineTo(8, 0); x.stroke();
  return g.createPattern(c, "repeat") ?? "#444";
}
