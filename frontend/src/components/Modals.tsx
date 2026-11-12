import { useEffect, useRef, useState, type ReactNode } from "react";
import { fmtTime } from "../timelineMath";
import { GUIDE_ORDER, HINTS, WORKFLOW } from "../hintsContent";
import { useHints } from "./Hint";
import type { Asset, Operation, ProposalsResult, RenderItem } from "../types";

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, select, input")?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <h3>{title}</h3>{children}
      </div>
    </div>
  );
}

export function RenderModal({ profile, revision, renders, busy, onConfirm, onClose }: {
  profile: "preview" | "final"; revision: number; renders: RenderItem[]; busy: boolean;
  onConfirm: (profile: "preview" | "final", fit: "letterbox" | "crop") => void; onClose: () => void;
}) {
  const [p, setP] = useState(profile);
  const [fit, setFit] = useState<"letterbox" | "crop">("letterbox");
  const lastPrev = renders.find((r) => r.profile === "preview" && r.state === "succeeded");
  return (
    <Modal title={p === "final" ? "Gerar vídeo final" : "Gerar preview"} onClose={onClose}>
      <p>Revisão atual da timeline: <strong>r{revision}</strong>. O render usa um snapshot imutável desta revisão.</p>
      <label className="row">Perfil <select value={p} onChange={(e) => setP(e.target.value as typeof p)}>
        <option value="preview">Preview · baixa resolução (720p)</option><option value="final">Final · 1920×1080</option></select></label>
      <label className="row">Proporção <select value={fit} onChange={(e) => setFit(e.target.value as typeof fit)}>
        <option value="letterbox">Letterbox (barras, sem cortar)</option><option value="crop">Crop (preenche o quadro)</option></select></label>
      {p === "preview" && lastPrev?.stale && <p className="banner warn">Há um preview de uma revisão anterior (r{lastPrev.timeline_revision}); este novo o substitui como referência.</p>}
      {p === "final" && !lastPrev && <p className="muted small">Não é preciso gerar preview antes: o vídeo final pode ser exportado direto.</p>}
      {p === "final" && lastPrev?.stale && <p className="banner warn">Seu último preview está desatualizado; o final será gerado da revisão atual (r{revision}) mesmo assim.</p>}
      <div className="actions end"><button className="btn" onClick={onClose}>Cancelar</button>
        <button className="btn primary" disabled={busy} onClick={() => onConfirm(p, fit)}>{p === "final" ? "Gerar vídeo final" : "Gerar preview"}</button></div>
    </Modal>
  );
}

export function InsertModal({ asset, outputMs, maxMs, onConfirm, onClose }: {
  asset: Asset; outputMs: number; maxMs: number | null;
  onConfirm: (mode: "b_roll" | "pip" | "sequential", durationMs: number) => void; onClose: () => void;
}) {
  const [mode, setMode] = useState<"b_roll" | "pip" | "sequential">("b_roll");
  const limit = asset.kind === "video" ? asset.duration_ms ?? 0 : null;
  const [dur, setDur] = useState(String(Math.min(limit ?? 4000, 4000) / 1000));
  const ms = Math.round(parseFloat(dur) * 1000);
  const bad = !(ms > 0) || (limit !== null && ms > limit) || (maxMs !== null && mode !== "sequential" && ms > maxMs);
  return (
    <Modal title={`Inserir “${asset.filename}”`} onClose={onClose}>
      <p>No ponto de saída <strong>{fmtTime(outputMs)}</strong> da timeline.</p>
      <label className="row">Modo <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
        <option value="b_roll">B-roll (cobre o vídeo, mantém a narração original)</option>
        <option value="pip">Picture-in-picture (canto)</option>
        <option value="sequential">Inserção sequencial (empurra o restante)</option></select></label>
      <label className="row">Duração (s) <input value={dur} onChange={(e) => setDur(e.target.value)} inputMode="decimal" />
        {limit !== null && <span className="muted small">máx. {(limit / 1000).toFixed(1)} s</span>}</label>
      {bad && <p className="banner warn">Duração inválida para esta mídia/posição.</p>}
      <p className="muted small">O áudio do vídeo principal é mantido (audio_policy: keep_primary).</p>
      <div className="actions end"><button className="btn" onClick={onClose}>Cancelar</button>
        <button className="btn primary" disabled={bad} onClick={() => onConfirm(mode, ms)}>Inserir</button></div>
    </Modal>
  );
}

export function HelpModal({ onClose, token, onToken }: { onClose: () => void; token: string; onToken: (t: string) => void }) {
  const [t, setT] = useState(token);
  const rows: [string, string][] = [
    ["Espaço", "reproduzir / pausar"], ["← / →", "quadro anterior / próximo (Shift: 1 s)"], ["[ / ]", "ocorrência anterior / próxima"],
    ["A / R", "aceitar / rejeitar a ocorrência selecionada"], ["X", "cortar a ocorrência selecionada"], ["Ctrl+Z / Ctrl+Shift+Z", "desfazer / refazer"],
    ["+ / −", "zoom da timeline"], ["Ctrl+roda", "zoom na timeline"], ["roda", "rolar a timeline"], ["duplo clique na ocorrência", "ouvir só o trecho"],
  ];
  return (
    <Modal title="Atalhos e configuração" onClose={onClose}>
      <table className="keys"><tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row"><kbd>{k}</kbd></th><td>{v}</td></tr>)}</tbody></table>
      <label className="row">Token da API <input type="password" value={t} onChange={(e) => setT(e.target.value)} autoComplete="off" /></label>
      <div className="actions end"><button className="btn" onClick={onClose}>Fechar</button><button className="btn primary" onClick={() => { onToken(t); onClose(); }}>Salvar token</button></div>
    </Modal>
  );
}

export function ProposalsModal({ result, onApply, onClose }: { result: ProposalsResult; onApply: (ops: Operation[]) => void; onClose: () => void }) {
  const [sel, setSel] = useState<Set<number>>(() => new Set(result.proposals.map((p, i) => (p.level === "baixa" ? -1 : i)).filter((i) => i >= 0)));
  const toggle = (i: number) => setSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  return (
    <Modal title="Sugestões de posição para mídias" onClose={onClose}>
      <p className="muted small">Propostas a partir das tags/descrição ↔ fala. Nada foi aplicado: marque o que quiser inserir.</p>
      {result.needs_timeline && <p className="banner warn">Inicie a edição para poder aplicar.</p>}
      {!result.proposals.length && <div className="empty">Nenhuma mídia casa com o que é dito. Revise as tags das mídias.</div>}
      {result.proposals.map((p, i) => (
        <label key={i} className="prop">
          <input type="checkbox" checked={sel.has(i)} onChange={() => toggle(i)} />
          <span><strong>{p.filename}</strong> · {p.mode === "pip" ? "PiP" : "B-roll"} · saída {fmtTime(p.timeline_start_ms)} · {(p.duration_ms / 1000).toFixed(1)} s · confiança {p.level}{p.source === "llm" && <span className="chip llm"> 🤖 semântico</span>}
            <br /><span className="muted small">{p.rationale} “{p.segment_text.slice(0, 90)}”</span></span>
        </label>))}
      {result.unmatched.length > 0 && <>
        <h4>Sem correspondência</h4>
        <ul className="small muted">{result.unmatched.map((u) => <li key={u.asset_id}><strong>{u.filename}</strong>: {u.message}</li>)}</ul></>}
      <div className="actions end"><button className="btn" onClick={onClose}>Fechar</button>
        <button className="btn primary" disabled={!sel.size || result.needs_timeline} onClick={() => onApply([...sel].sort((a, b) => a - b).map((i) => result.proposals[i].operation))}>Aplicar {sel.size} selecionada(s)</button></div>
    </Modal>
  );
}

export function GuideModal({ onClose }: { onClose: () => void }) {
  const { enabled, setEnabled, resetSeen } = useHints();
  const areas = [...new Set(GUIDE_ORDER.map((id) => HINTS[id].area))];
  return (
    <Modal title="Guia de recursos" onClose={onClose}>
      <div className="guide">
        <p className="muted small">Tudo o que o editor faz, em um lugar. Os balões <span className="hint-dot" style={{ pointerEvents: "none" }}>?</span> espalhados pela tela trazem a mesma explicação no ponto de uso.</p>
        <h4>Fluxo básico</h4>
        <ol>{WORKFLOW.map(([t, d]) => <li key={t}><b>{t}</b> — {d}</li>)}</ol>
        {areas.map((a) => (
          <section key={a}>
            <h4>{a}</h4>
            {GUIDE_ORDER.filter((id) => HINTS[id].area === a).map((id) => (
              <div key={id} className="guide-item"><h5>{HINTS[id].title}</h5><div className="hint-body">{HINTS[id].body}</div></div>))}
          </section>))}
        <h4>Dicas na tela</h4>
        <div className="actions">
          <button className="btn" onClick={() => setEnabled(!enabled)}>{enabled ? "Esconder balões" : "Mostrar balões"}</button>
          <button className="btn" onClick={resetSeen}>Fazer os balões pulsarem de novo</button>
        </div>
      </div>
      <div className="actions end"><button className="btn primary" onClick={onClose}>Fechar</button></div>
    </Modal>
  );
}
