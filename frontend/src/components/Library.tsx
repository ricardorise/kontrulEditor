import { useRef, useState } from "react";
import { useAssetUrl } from "../hooks";
import { fmtTime } from "../timelineMath";
import type { Asset } from "../types";
import { Hint } from "./Hint";

interface Props {
  pid: string; assets: Asset[]; onUpload: (f: File, role: "main" | "auxiliary") => void; uploading: number | null;
  onTags: (id: string, tags: string[], description: string | null) => void;
  onMeta: (id: string, meta: { priority?: number; intended_use?: string | null; suggested_duration_ms?: number | null }) => void;
  onPropose: () => void; proposing: boolean; hasTranscript: boolean; onInsert: (a: Asset) => void; canInsert: boolean;
}

export function Library({ pid, assets, onUpload, uploading, onTags, onMeta, onInsert, canInsert, onPropose, proposing, hasTranscript }: Props) {
  const [q, setQ] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const aux = assets.filter((a) => a.role === "auxiliary");
  const shown = aux.filter((a) => !q || [a.filename, a.description ?? "", ...a.tags].join(" ").toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="library">
      <div className="toolbar">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nome, tag ou descrição" aria-label="Buscar mídias" />
        <button className="btn primary" onClick={() => file.current?.click()}>＋ Adicionar mídia</button>
        <button className="btn" disabled={!aux.length || !hasTranscript || proposing} onClick={onPropose}
          title={hasTranscript ? "Casa as tags com o que é dito e propõe onde inserir (nada é aplicado sozinho)" : "Transcreva o vídeo primeiro"}>✨ Sugerir posições</button>
        <Hint id="library" />
        <input ref={file} type="file" accept="image/*,video/*" multiple hidden onChange={(e) => { [...(e.target.files ?? [])].forEach((f) => onUpload(f, "auxiliary")); e.target.value = ""; }} />
      </div>
      {uploading !== null && <div className="progress" role="progressbar" aria-valuenow={Math.round(uploading * 100)} aria-label="Enviando mídia"><div style={{ width: `${uploading * 100}%` }} /></div>}
      <p className="muted small">Arraste para a timeline (B-roll/PiP) ou use “Inserir no cursor”. Busca externa de mídias não faz parte do MVP.</p>
      {!aux.length ? <div className="empty">Nenhuma mídia complementar. Adicione imagens ou vídeos e marque tags para a IA associar ao conteúdo.</div>
        : !shown.length ? <div className="empty">Nenhuma mídia corresponde à busca.</div> : (
          <div className="grid">{shown.map((a) => <Card key={a.id} pid={pid} a={a} onTags={onTags} onMeta={onMeta} onInsert={onInsert} canInsert={canInsert} />)}</div>
        )}
    </div>
  );
}

function Card({ pid, a, onTags, onMeta, onInsert, canInsert }: { pid: string; a: Asset; onTags: Props["onTags"]; onMeta: Props["onMeta"]; onInsert: Props["onInsert"]; canInsert: boolean }) {
  const [dur, setDur] = useState(a.suggested_duration_ms ? String(a.suggested_duration_ms / 1000) : "");
  const [use, setUse] = useState(a.intended_use ?? "");
  const th = useAssetUrl(pid, a.id, "thumbnail", a.has_thumbnail);
  const [tags, setTags] = useState(a.tags.join(", "));
  const [desc, setDesc] = useState(a.description ?? "");
  const commit = () => { const t = tags.split(",").map((x) => x.trim()).filter(Boolean); if (t.join() !== a.tags.join() || desc !== (a.description ?? "")) onTags(a.id, t, desc || null); };
  return (
    <div className="card" draggable={a.status === "ready" && canInsert} onDragStart={(e) => e.dataTransfer.setData("application/x-kontrul-asset", a.id)}>
      <div className="thumb">{th.data ? <img src={th.data} alt={a.filename} /> : <span>{a.status === "failed" ? "erro" : a.status === "ready" ? a.kind : "processando…"}</span>}</div>
      <div className="card-body">
        <strong title={a.filename} className="ellipsis">{a.filename}</strong>
        <span className="muted small">{a.kind}{a.duration_ms && a.kind === "video" ? ` · ${fmtTime(a.duration_ms, 0)}` : ""}{a.width ? ` · ${a.width}×${a.height}` : ""}</span>
        {a.status === "failed" && <span className="chip bad" title={a.error ?? ""}>falhou: {a.error?.slice(0, 60) ?? "codec"}</span>}
        <label className="small">Tags <input value={tags} onChange={(e) => setTags(e.target.value)} onBlur={commit} placeholder="ex.: produto, logo" /></label>
        <label className="small">Descrição <input value={desc} onChange={(e) => setDesc(e.target.value)} onBlur={commit} /></label>
        <div className="meta-row">
          <label className="small">Prioridade <select value={a.priority} onChange={(e) => onMeta(a.id, { priority: Number(e.target.value) })}>
            <option value={0}>baixa</option><option value={1}>normal</option><option value={2}>alta</option></select></label>
          <label className="small">Duração (s) <input value={dur} inputMode="decimal" placeholder="auto" onChange={(e) => setDur(e.target.value)}
            onBlur={() => { const v = Math.round(parseFloat(dur) * 1000); if (v >= 500 && v !== a.suggested_duration_ms) onMeta(a.id, { suggested_duration_ms: v }); }} /></label>
        </div>
        <label className="small">Uso pretendido <input value={use} onChange={(e) => setUse(e.target.value)} placeholder="b-roll, pip, logo…"
          onBlur={() => use !== (a.intended_use ?? "") && onMeta(a.id, { intended_use: use || null })} /></label>
        <button className="btn" disabled={!canInsert || a.status !== "ready"} onClick={() => onInsert(a)} title={canInsert ? "" : "Inicie a edição primeiro"}>Inserir no cursor</button>
      </div>
    </div>
  );
}
