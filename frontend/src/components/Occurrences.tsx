import { useEffect, useMemo, useRef, useState } from "react";
import { fmtTime, keptFraction } from "../timelineMath";
import type { Asset, Category, Suggestion, TimelineDoc, Word } from "../types";
import { Hint } from "./Hint";
import { CAT } from "./Timeline";

const LEVEL: Record<string, string> = { alta: "confiança alta", media: "confiança média", baixa: "confiança baixa" };
const STATUS: Record<Suggestion["status"], string> = { pending: "pendente", accepted: "aceita", rejected: "rejeitada", adjusted: "ajustada" };

interface Props {
  suggestions: Suggestion[]; doc: TimelineDoc | null; main: Asset; words: Word[]; selectedId: string | null;
  onSelect: (id: string) => void; onPlay: (s: Suggestion) => void;
  onDecide: (id: string, decision: "accept" | "reject" | "adjust", start?: number, end?: number) => void;
  onCut: (ids: string[]) => void; onRestore: (s: Suggestion) => void; hasTranscript: boolean;
}

export function excerpt(words: Word[], s: number, e: number, max = 170): string {
  const t = words.filter((w) => w.end_ms > s && w.start_ms < e).map((w) => w.text).join(" ");
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

export function Occurrences(p: Props) {
  const [cat, setCat] = useState<"all" | Category>("all");
  const [st, setSt] = useState<"all" | Suggestion["status"]>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [adj, setAdj] = useState({ s: "", e: "" });
  const refs = useRef<Record<string, HTMLLIElement | null>>({});
  const list = useMemo(() => p.suggestions.filter((s) => (cat === "all" || s.category === cat) && (st === "all" || s.status === st)), [p.suggestions, cat, st]);
  const removed = (s: Suggestion) => !!p.doc && keptFraction(p.doc, p.main.id, s.start_ms, s.end_ms) < 0.02;
  const pendingCut = p.suggestions.filter((s) => (s.status === "accepted" || s.status === "adjusted") && !removed(s));

  useEffect(() => { if (p.selectedId) refs.current[p.selectedId]?.scrollIntoView({ block: "nearest" }); }, [p.selectedId]);

  if (!p.suggestions.length) {
    return <div className="empty">{p.hasTranscript ? "A IA não encontrou ocorrências nesta análise. Você ainda pode editar manualmente pela timeline." : "Sem sugestões ainda. Transcreva o vídeo e rode a análise na aba IA."}<Hint id="analyze" /></div>;
  }
  return (
    <div className="occ">
      <div className="toolbar">
        <label>Categoria <select value={cat} onChange={(e) => setCat(e.target.value as typeof cat)}>
          <option value="all">todas</option>{(Object.keys(CAT) as Category[]).map((c) => <option key={c} value={c}>{CAT[c].label}</option>)}</select></label>
        <label>Estado <select value={st} onChange={(e) => setSt(e.target.value as typeof st)}>
          <option value="all">todos</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <button className="btn" disabled={!pendingCut.length || !p.doc} onClick={() => p.onCut(pendingCut.map((s) => s.id))}
          title="Aplica na timeline os trechos que você aceitou">Aplicar {pendingCut.length} aceita{pendingCut.length === 1 ? "" : "s"}</button>
        <Hint id="occ" />
      </div>
      <ul className="occ-list" aria-label="Ocorrências">
        {list.map((s) => {
          const c = CAT[s.category], cut = removed(s), sel = s.id === p.selectedId;
          return (
            <li key={s.id} ref={(el) => { refs.current[s.id] = el; }} className={`occ-item ${sel ? "sel" : ""} st-${s.status}`}
              style={{ ["--cat" as string]: c.color }}>
              <div className="occ-head" tabIndex={0} role="button" aria-pressed={sel} aria-label={`${c.label} de ${fmtTime(s.start_ms)} a ${fmtTime(s.end_ms)}, ${STATUS[s.status]}`}
                onClick={() => p.onSelect(s.id)} onDoubleClick={() => p.onPlay(s)}
                onKeyDown={(e) => { if (e.key === "Enter") p.onSelect(s.id); if (e.key === " ") { e.preventDefault(); p.onPlay(s); } }}>
                <span className={`badge cat-${s.category}`}>{c.short}</span>
                <span className="mono">{fmtTime(s.start_ms)} → {fmtTime(s.end_ms)}</span>
                <span className="muted">({((s.end_ms - s.start_ms) / 1000).toFixed(1)} s)</span>
                {s.evidence?.level && <span className={`chip lvl-${s.evidence.level}`}>{LEVEL[s.evidence.level] ?? s.evidence.level}</span>}
                <span className={`chip st-${s.status}`}>{STATUS[s.status]}</span>
                {cut && <span className="chip cut">no corte</span>}
                {s.origin !== "rules" && s.origin !== "manual" && <span className="chip llm" title={`Origem: ${s.origin}`}>🤖 LLM</span>}
                {s.evidence?.llm?.disputed && <span className="chip bad" title="O LLM discorda desta sugestão; revise com atenção">LLM discorda</span>}
              </div>
              <p className="occ-text">{excerpt(p.words, s.start_ms, s.end_ms) || s.evidence?.removed_text || "—"}</p>
              <p className="muted small">{s.rationale}{s.evidence?.redo_text ? <> Recomeço: “{s.evidence.redo_text.slice(0, 80)}”.</> : null}</p>
              {s.evidence?.llm?.reason && <p className="small llm-note" title={s.evidence.llm.model}>🤖 {s.evidence.llm.verdict === "found" ? "Achado do LLM" : `LLM (${s.evidence.llm.verdict === "confirm" ? "confirma" : s.evidence.llm.verdict === "reject" ? "contesta" : "ajusta"})`}: {s.evidence.llm.reason}{s.evidence.llm.note ? ` — ${s.evidence.llm.note}` : ""}</p>}
              {s.evidence?.llm_extra && <p className="small llm-note">🤖 O LLM também apontou este trecho: {s.evidence.llm_extra}</p>}
              {s.evidence?.memory?.note && <p className="small mem-note" title={`${s.evidence.memory.similar} exemplo(s) parecido(s) na memória do projeto`}>🧠 {s.evidence.memory.note}</p>}
              {editing === s.id ? (
                <form className="adjust" onSubmit={(e) => { e.preventDefault(); const a = Math.round(parseFloat(adj.s) * 1000), b = Math.round(parseFloat(adj.e) * 1000); if (b > a && a >= 0) { p.onDecide(s.id, "adjust", a, b); setEditing(null); } }}>
                  <label>Início (s) <input value={adj.s} onChange={(e) => setAdj({ ...adj, s: e.target.value })} inputMode="decimal" /></label>
                  <label>Fim (s) <input value={adj.e} onChange={(e) => setAdj({ ...adj, e: e.target.value })} inputMode="decimal" /></label>
                  <button className="btn primary" type="submit">Salvar</button>
                  <button className="btn" type="button" onClick={() => setEditing(null)}>Cancelar</button>
                </form>
              ) : (
                <div className="actions">
                  <button className="btn" onClick={() => p.onPlay(s)}>▶ Ouvir</button>
                  <button className="btn ok" disabled={s.status === "accepted"} onClick={() => p.onDecide(s.id, "accept")}>✓ Aceitar</button>
                  <button className="btn bad" disabled={s.status === "rejected"} onClick={() => p.onDecide(s.id, "reject")}>✗ Rejeitar</button>
                  <button className="btn" onClick={() => { setEditing(s.id); setAdj({ s: (s.start_ms / 1000).toFixed(2), e: (s.end_ms / 1000).toFixed(2) }); }}>Ajustar</button>
                  {cut ? <button className="btn" onClick={() => p.onRestore(s)}>↺ Restaurar</button>
                    : <button className="btn danger" disabled={!p.doc} onClick={() => p.onCut([s.id])} title="Aceita e remove da timeline (reversível com Ctrl+Z)">✂ Cortar</button>}
                </div>
              )}
            </li>
          );
        })}
        {!list.length && <li className="empty">Nenhuma ocorrência com esses filtros.</li>}
      </ul>
    </div>
  );
}
