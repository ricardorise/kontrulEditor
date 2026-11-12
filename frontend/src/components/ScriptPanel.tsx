import { useMemo, useRef, useState } from "react";
import type { Alignment, Script, TranscriptFull } from "../types";
import { Hint } from "./Hint";

interface Props {
  scripts: Script[]; scriptId: string | null; onScript: (id: string) => void; alignment: Alignment[]; transcript?: TranscriptFull;
  onSave: (text: string) => void; onFile: (f: File) => void; onSeek: (ms: number) => void; onToggle: (a: Alignment) => void;
  onAnalyze: () => void; canAnalyze: boolean; busy: boolean;
}

export function ScriptPanel(p: Props) {
  const [draft, setDraft] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const script = p.scripts.find((s) => s.id === p.scriptId);
  const segByW0 = useMemo(() => new Map((p.transcript?.segments ?? []).map((s) => [s.w0, s])), [p.transcript]);

  const pieces = useMemo(() => {
    if (!script) return [];
    const spans = p.alignment.filter((a) => a.kind !== "off_script" && a.script_end > a.script_start);
    const cuts = new Set<number>([0, script.text.length]);
    spans.forEach((a) => { cuts.add(a.script_start); cuts.add(Math.min(a.script_end, script.text.length)); });
    const pts = [...cuts].sort((a, b) => a - b);
    return pts.slice(0, -1).map((s, i) => {
      const e = pts[i + 1], cover = spans.filter((a) => a.script_start <= s && a.script_end >= e);
      const m = cover.find((a) => a.kind === "matched"), u = cover.find((a) => a.kind === "unspoken");
      return { s, e, text: script.text.slice(s, e), kind: m ? "matched" : u ? "unspoken" : "plain", al: m };
    });
  }, [script, p.alignment]);

  return (
    <div className="script">
      <div className="toolbar">
        <label>Versão <select value={p.scriptId ?? ""} onChange={(e) => p.onScript(e.target.value)} disabled={!p.scripts.length}>
          {!p.scripts.length && <option value="">nenhum roteiro</option>}
          {p.scripts.map((s) => <option key={s.id} value={s.id}>v{s.version} · {s.format}</option>)}</select></label>
        <button className="btn" onClick={() => file.current?.click()}>Enviar .txt/.md</button>
        <input ref={file} type="file" accept=".txt,.md" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onFile(f); e.target.value = ""; }} />
        <button className="btn primary" disabled={!p.canAnalyze || p.busy} onClick={p.onAnalyze}
          title={p.canAnalyze ? "Reanalisa usando o roteiro como contexto" : "Transcreva o vídeo primeiro"}>Analisar com este roteiro</button>
        <Hint id="script" />
      </div>
      <details className="paste" open={!p.scripts.length}>
        <summary>Colar um roteiro (opcional)</summary>
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} placeholder="Cole aqui o roteiro usado na gravação. Ele serve só como contexto para a IA: nunca substitui o que foi falado." />
        <button className="btn" disabled={!draft.trim()} onClick={() => { p.onSave(draft); setDraft(""); }}>Salvar como nova versão</button>
      </details>
      {!script ? <div className="empty">Sem roteiro. A análise funciona sem ele; com ele, a IA distingue melhor fala fora do roteiro e tomadas repetidas.</div> : (
        <div className="cols">
          <div className="col">
            <h4>Roteiro (v{script.version})</h4>
            <div className="script-text">
              {pieces.map((pc, i) => pc.kind === "matched" && pc.al?.word_start_idx != null ? (
                <span key={i} role="button" tabIndex={0} className="sp matched" title={`Aderente (${Math.round((pc.al.adherence ?? 0) * 100)}%) — clique para ir à fala`}
                  onClick={() => { const seg = segByW0.get(pc.al!.word_start_idx!); if (seg) p.onSeek(seg.start_ms); }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLElement).click(); }}>{pc.text}</span>
              ) : <span key={i} className={`sp ${pc.kind}`} title={pc.kind === "unspoken" ? "Trecho do roteiro que não foi falado" : undefined}>{pc.text}</span>)}
            </div>
            <p className="legend small"><span className="sp matched">falado</span> <span className="sp unspoken">não falado</span></p>
          </div>
          <div className="col">
            <h4>Fala × roteiro</h4>
            {!p.transcript ? <div className="empty">Sem transcrição para alinhar.</div> : !p.alignment.length ? <div className="empty">Rode “Analisar com este roteiro” para alinhar.</div> : (
              <ul className="align-list">
                {p.alignment.filter((a) => a.word_start_idx != null).map((a) => {
                  const seg = segByW0.get(a.word_start_idx!); if (!seg) return null;
                  return (
                    <li key={a.id} className={`al ${a.kind}`}>
                      <button className="seg-time" onClick={() => p.onSeek(seg.start_ms)}>{Math.round(seg.start_ms / 1000)}s</button>
                      <span className={`chip ${a.kind === "matched" ? "ok" : "warn"}`}>{a.kind === "matched" ? `aderente ${Math.round((a.adherence ?? 0) * 100)}%` : "fora do roteiro"}</span>
                      <span className="al-text">{seg.text}</span>
                      <button className="btn tiny" onClick={() => p.onToggle(a)} title="Corrigir manualmente o alinhamento">{a.kind === "matched" ? "marcar fora" : "marcar aderente"}</button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
