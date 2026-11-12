import { useState } from "react";
import { api } from "../api";
import { JOB_LABEL, STATE_LABEL } from "../labels";
import type { Job, LlmReport, LlmStatus, Plan, RenderItem, Rule, SuggestedRule, Suggestion, TranscriptMeta } from "../types";
import { useToast } from "../toast";
import { Hint } from "./Hint";

interface AIProps {
  transcripts: TranscriptMeta[]; jobs: Job[]; suggestions: Suggestion[]; canTranscribe: boolean; hasScript: boolean;
  onTranscribe: (language: string, diarize: boolean) => void; onAnalyze: () => void; busy: boolean;
  plan: Plan | null; planning: boolean; canPlan: boolean; onPlan: (prompt: string) => void; onApplyPlan: () => void; onClearPlan: () => void;
  rules: Rule[]; suggestedRules: SuggestedRule[]; onAddRule: (r: { kind: Rule["kind"]; text: string; params: { phrases?: string[] }; provenance?: Record<string, unknown> }) => void;
  onToggleRule: (r: Rule) => void; onDeleteRule: (r: Rule) => void;
  llm?: LlmStatus; useLlm: boolean; onUseLlm: (v: boolean) => void; lastLlm?: LlmReport;
}

const RULE_LABEL: Record<Rule["kind"], string> = {
  note: "Anotação", ignore_erro_context: "«erro» nesta frase não é marcador", protect_phrase: "Não sugerir corte com a frase", extra_cue: "Frase é pista de correção",
};

export function AIPanel(p: AIProps) {
  const [lang, setLang] = useState("pt");
  const [dia, setDia] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [rk, setRk] = useState<Rule["kind"]>("protect_phrase");
  const [rt, setRt] = useState("");
  const running = p.jobs.filter((j) => (j.kind === "transcribe" || j.kind === "analyze") && (j.state === "queued" || j.state === "running"));
  const dec = (s: Suggestion["status"]) => p.suggestions.filter((x) => x.status === s).length;
  const addRule = () => {
    const ph = rt.split(";").map((x) => x.trim()).filter(Boolean);
    if (!ph.length) return;
    p.onAddRule({ kind: rk, text: `${RULE_LABEL[rk]}: ${ph.join("; ")}`, params: rk === "note" ? {} : { phrases: ph } });
    setRt("");
  };
  return (
    <div className="ai">
      <h4>1 · Transcrever<Hint id="transcribe" /></h4>
      <div className="toolbar">
        <label>Idioma <select value={lang} onChange={(e) => setLang(e.target.value)}><option value="pt">Português</option><option value="en">English</option><option value="es">Español</option></select></label>
        <label className="check"><input type="checkbox" checked={dia} onChange={(e) => setDia(e.target.checked)} /> Separar falantes</label>
        <button className="btn primary" disabled={!p.canTranscribe || p.busy} onClick={() => p.onTranscribe(lang, dia)}>Transcrever com WhisperX</button>
      </div>
      {dia && <p className="muted small">Separar falantes exige HF_TOKEN no servidor; sem ele a transcrição segue sem falantes.</p>}
      <p className="muted small">{p.transcripts.length ? `${p.transcripts.length} transcrição(ões) neste projeto.` : "Nenhuma transcrição ainda."}</p>
      <h4>2 · Analisar<Hint id="analyze" /></h4>
      {p.llm && (
        <div className={`llm-card ${p.llm.configured ? (p.llm.external ? "ext" : "loc") : "off"}`} role="status">
          <strong>{p.llm.configured ? `🤖 ${p.llm.provider} · ${p.llm.model}` : "🤖 LLM desativado"}<Hint id="llm" /></strong>
          <span className="small">{p.llm.message}</span>
          {!p.llm.configured && p.llm.provider === "none" && <span className="muted small">Para ativar, defina KONTRUL_LLM_PROVIDER (anthropic, openai, openrouter ou ollama) e a chave no .env.</span>}
        </div>)}
      <div className="toolbar">
        <button className="btn primary" disabled={!p.transcripts.length || p.busy} onClick={p.onAnalyze}>Analisar{p.hasScript ? " (com roteiro)" : ""}</button>
        {p.llm?.configured && <label className="check"><input type="checkbox" checked={p.useLlm} onChange={(e) => p.onUseLlm(e.target.checked)} /> Usar LLM{p.llm.external ? " (envia o texto à API)" : ""}</label>}
      </div>
      <p className="muted small">Regras determinísticas + memória de decisões{p.llm?.configured && p.useLlm ? " + revisão por LLM" : ""}. Nada é cortado sem você aceitar.</p>
      {p.lastLlm && p.lastLlm.status !== "disabled" && (
        <p className={`small ${p.lastLlm.status === "ok" ? "" : "chip warn"}`}>Última análise com LLM: {p.lastLlm.status === "ok" || p.lastLlm.status === "partial" ? `${p.lastLlm.confirmed ?? 0} confirmadas, ${p.lastLlm.rejected ?? 0} contestadas, ${p.lastLlm.adjusted ?? 0} ajustadas, ${p.lastLlm.new_findings ?? 0} novas · ${p.lastLlm.windows_used}/${p.lastLlm.windows_total} janelas · ${(p.lastLlm.input_tokens ?? 0) + (p.lastLlm.output_tokens ?? 0)} tokens${p.lastLlm.dropped_invalid ? ` · ${p.lastLlm.dropped_invalid} indicação(ões) inválida(s) descartada(s)` : ""}` : `indisponível — usou só regras (${(p.lastLlm.errors?.[0] ?? p.lastLlm.message ?? "").slice(0, 120)})`}</p>)}
      {!!running.length && <p className="chip warn">{running.map((j) => JOB_LABEL[j.kind]).join(", ")} em andamento…</p>}
      <p className="small">{p.suggestions.length} sugestões · {dec("accepted") + dec("adjusted")} aceitas · {dec("rejected")} rejeitadas · {dec("pending")} pendentes</p>

      <h4>3 · Assistente por prompt<Hint id="assistant" /></h4>
      <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="Prompt para o assistente"
        placeholder={"Ex.: insira o logo quando eu falar sobre headset\ncorte de 1:20 até 1:35\naceite todas as sugestões de confiança alta"} />
      <div className="toolbar"><button className="btn primary" disabled={!prompt.trim() || p.planning || !p.canPlan} onClick={() => p.onPlan(prompt)}>Planejar</button>
        {!p.canPlan && <span className="muted small">Inicie a edição primeiro.</span>}</div>
      <p className="muted small">{p.llm?.configured && p.useLlm ? "Regras primeiro; pedidos livres são interpretados pelo LLM." : "Planner por regras (sem LLM)."} O prompt vira operações estruturadas e validadas; nunca comandos FFmpeg. Você revisa antes de aplicar.</p>
      {p.plan && (
        <div className="plan" aria-live="polite">
          {p.plan.steps.map((st, i) => (
            <div key={i} className={`plan-step ${st.errors.length ? "err" : ""}`}>
              <strong>{st.recognized ? st.summary || st.text : st.text}</strong>{st.source === "llm" && <span className="chip llm"> 🤖 LLM</span>}
              {st.operations.map((o, k) => <div key={k} className="muted small">→ {o.type}{o.asset_id ? "" : ""} {JSON.stringify(Object.fromEntries(Object.entries(o).filter(([key]) => !["type", "asset_id", "audio_policy"].includes(key))))}</div>)}
              {st.decisions.length > 0 && <div className="muted small">→ aceitar {st.decisions.length} sugestão(ões)</div>}
              {st.errors.map((e, k) => <div key={k} className="chip bad">{e}</div>)}
            </div>))}
          <div className="actions">
            <button className="btn primary" disabled={!p.plan.operations.length && !p.plan.decisions.length} onClick={p.onApplyPlan}>Aplicar plano ({p.plan.decisions.length + p.plan.operations.length} ação(ões))</button>
            <button className="btn" onClick={p.onClearPlan}>Descartar</button>
          </div>
        </div>)}

      <h4>Memória e regras<Hint id="rules" /></h4>
      <p className="muted small">Suas decisões alimentam exemplos e regras com origem registrada. Você pode desligar ou apagar qualquer uma.</p>
      {p.suggestedRules.map((r, i) => (
        <div key={i} className="rule"><span className="chip warn">proposta</span><span className="grow small">{r.text}</span>
          <button className="btn tiny ok" onClick={() => p.onAddRule({ kind: r.kind, text: r.text, params: r.params, provenance: r.provenance })}>Criar regra</button></div>))}
      {!p.rules.length && !p.suggestedRules.length && <div className="empty">Nenhuma regra ainda. Ao rejeitar várias sugestões parecidas, a IA propõe uma regra aqui.</div>}
      {p.rules.map((r) => (
        <div key={r.id} className={`rule ${r.enabled ? "" : "muted"}`}>
          <label className="check"><input type="checkbox" checked={r.enabled} onChange={() => p.onToggleRule(r)} aria-label={`Regra ativa: ${r.text}`} /></label>
          <span className="grow small">{r.text}</span><span className="chip">{r.provenance?.source === "feedback" ? "do feedback" : "manual"}{r.scope === "user" ? " · global" : ""}</span>
          <button className="btn tiny bad" onClick={() => p.onDeleteRule(r)} aria-label="Apagar regra">Apagar</button></div>))}
      <div className="toolbar">
        <label>Nova regra <select value={rk} onChange={(e) => setRk(e.target.value as Rule["kind"])}>
          {(Object.keys(RULE_LABEL) as Rule["kind"][]).map((k) => <option key={k} value={k}>{RULE_LABEL[k]}</option>)}</select></label>
        <label>Frase(s) separadas por ; <input value={rt} onChange={(e) => setRt(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRule()} /></label>
        <button className="btn" disabled={!rt.trim()} onClick={addRule}>Adicionar</button>
      </div>
    </div>
  );
}

export function JobsPanel({ pid, jobs, renders, onCancel, onRetry }: { pid: string; jobs: Job[]; renders: RenderItem[]; onCancel: (id: string) => void; onRetry: (id: string) => void }) {
  const toast = useToast();
  const open = async (r: RenderItem) => {
    try { const a = await api<{ url: string }>(`/renders/${r.job_id}/artifact`); window.open(a.url, "_blank", "noopener"); }
    catch (e) { toast(e instanceof Error ? e.message : "falha ao abrir", "error"); }
  };
  return (
    <div className="jobs" data-pid={pid}>
      <h4>Renders<Hint id="render" /></h4>
      {!renders.length ? <div className="empty">Nenhum render. Use “Gerar Preview” ou “Gerar Vídeo Final” — são independentes.</div> : (
        <ul className="job-list">{renders.map((r) => (
          <li key={r.job_id} className={`job st-${r.state}`}>
            <div><strong>{r.profile === "final" ? "Vídeo final 1080p" : "Preview"}</strong> · rev {r.timeline_revision} · {STATE_LABEL[r.state]}
              {r.stale && r.state === "succeeded" && <span className="chip warn"> desatualizado</span>}</div>
            {(r.state === "running" || r.state === "queued") && <div className="progress" role="progressbar" aria-valuenow={Math.round(r.progress * 100)}><div style={{ width: `${r.progress * 100}%` }} /></div>}
            {r.state === "queued" && <p className="muted small">Na fila: aguardando o worker de render.</p>}
            {r.state === "failed" && <p className="chip bad small" title={r.error?.message}>Falhou: {r.error?.message.slice(0, 140)}</p>}
            {(r.state === "failed" || r.state === "cancelled") && <button className="btn tiny" onClick={() => onRetry(r.job_id)}>↻ Tentar de novo</button>}
            <div className="actions">
              {r.state === "succeeded" && <button className="btn" onClick={() => open(r)}>Abrir / baixar</button>}
              {(r.state === "queued" || r.state === "running") && <button className="btn bad" onClick={() => onCancel(r.job_id)}>Cancelar</button>}
            </div>
          </li>))}</ul>
      )}
      <h4>Todos os jobs<Hint id="jobs" /></h4>
      {!jobs.length ? <div className="empty">Nenhum job ainda.</div> : (
        <ul className="job-list">{jobs.slice(0, 30).map((j) => (
          <li key={j.job_id} className={`job st-${j.state}`}>
            <div>{JOB_LABEL[j.kind] ?? j.kind} · {STATE_LABEL[j.state]}</div>
            {(j.state === "running" || j.state === "queued") && <div className="progress" role="progressbar" aria-valuenow={Math.round(j.progress * 100)}><div style={{ width: `${j.progress * 100}%` }} /></div>}
            {j.error && <p className="chip bad small" title={j.error.message}>{j.error.message.slice(0, 140)}</p>}
            {!j.kind.startsWith("render") && (j.state === "queued" || j.state === "running") && <button className="btn tiny bad" onClick={() => onCancel(j.job_id)}>Cancelar</button>}
            {!j.kind.startsWith("render") && (j.state === "failed" || j.state === "cancelled") && <button className="btn tiny" onClick={() => onRetry(j.job_id)}>↻ Tentar de novo</button>}
          </li>))}</ul>
      )}
    </div>
  );
}
