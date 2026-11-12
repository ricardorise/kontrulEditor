import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, getToken, setToken, upload } from "./api";
import { Library } from "./components/Library";
import { Hint, useHints } from "./components/Hint";
import { GuideModal, HelpModal, InsertModal, ProposalsModal, RenderModal } from "./components/Modals";
import { Occurrences } from "./components/Occurrences";
import { Player, type PlayerApi, type PlayMode } from "./components/Player";
import { ScriptPanel } from "./components/ScriptPanel";
import { AIPanel, JobsPanel } from "./components/SidePanels";
import { Timeline, type View } from "./components/Timeline";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useAlignment, useAssets, useJobs, useLlmStatus, useProject, useProjects, useRenders, useRules, useScripts, useSuggestedRules, useSuggestions, useTimeline, useTimelineOps, useTranscript, useTranscripts, useWaveform } from "./hooks";
import { clamp, fmtTime, nextKept, sourceToOutput } from "./timelineMath";
import { useToast } from "./toast";
import type { Alignment, Asset, LlmReport, Operation, Plan, ProposalsResult, Rule, Suggestion } from "./types";

type Tab = "occ" | "transcript" | "script" | "ai" | "library" | "jobs";
const TABS: [Tab, string][] = [["occ", "Ocorrências"], ["transcript", "Transcrição"], ["script", "Roteiro"], ["ai", "IA"], ["library", "Biblioteca"], ["jobs", "Jobs"]];
const winW = () => Math.max(400, window.innerWidth - 32);

export default function App() {
  const qc = useQueryClient();
  const toast = useToast();
  const [pid, setPidState] = useState<string | undefined>(() => localStorage.getItem("kontrul_project") ?? undefined);
  const setPid = (id?: string) => { setPidState(id); if (id) localStorage.setItem("kontrul_project", id); };
  const [tab, setTab] = useState<Tab>("occ");
  const [selected, setSelected] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [mode, setMode] = useState<PlayMode>("original");
  const [view, setView] = useState<View>({ startMs: 0, msPerPx: 50 });
  const [renderDlg, setRenderDlg] = useState<"preview" | "final" | null>(null);
  const [insert, setInsert] = useState<{ asset: Asset; sourceMs: number } | null>(null);
  const [help, setHelp] = useState(false);
  const [guide, setGuide] = useState(false);
  const [scriptId, setScriptId] = useState<string | null>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const [auxUploading, setAuxUploading] = useState<number | null>(null);
  const [proposals, setProposals] = useState<ProposalsResult | null>(null);
  const [proposing, setProposing] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const llmStatus = useLlmStatus();
  const player = useRef<PlayerApi>(null);

  const projects = useProjects();
  const project = useProject(pid);
  const assets = useAssets(pid);
  const jobs = useJobs(pid);
  const renders = useRenders(pid);
  const suggestions = useSuggestions(pid);
  const rev = project.data?.current_revision ?? 0;
  const timeline = useTimeline(pid, rev);
  const doc = rev > 0 && timeline.data ? timeline.data.document : null;
  const ops = useTimelineOps(pid, rev, toast);

  const assetList = assets.data ?? [];
  const mainAsset = assetList.find((a) => a.role === "main");
  const main = mainAsset?.status === "ready" ? mainAsset : undefined;
  const transcripts = useTranscripts(pid);
  const mainTranscripts = (transcripts.data ?? []).filter((t) => t.asset_id === main?.id);
  const tMeta = mainTranscripts[mainTranscripts.length - 1];
  const transcript = useTranscript(pid, tMeta?.id);
  const scripts = useScripts(pid);
  const activeScript = scriptId ?? scripts.data?.[scripts.data.length - 1]?.id ?? null;
  const alignment = useAlignment(pid, activeScript ?? undefined);
  const rules = useRules(pid);
  const waveform = useWaveform(pid, main?.id, !!main?.audio_info);
  const words = transcript.data?.words ?? [];
  const decidedCount = (suggestions.data ?? []).filter((x) => x.status !== "pending").length;
  const suggestedRules = useSuggestedRules(pid, decidedCount);
  const sugg: Suggestion[] = useMemo(() => (suggestions.data ?? []).filter((s) => !main || !s.asset_id || s.asset_id === main.id), [suggestions.data, main]);
  const lastRender = (renders.data ?? []).find((r) => r.state === "succeeded");
  const renderUrl = useQuery({
    queryKey: ["render-url", lastRender?.job_id], enabled: !!lastRender, staleTime: 50 * 60_000,
    queryFn: async () => (await api<{ url: string }>(`/renders/${lastRender!.job_id}/artifact`)).url,
  });
  const snapPoints = useMemo(() => words.flatMap((w) => [w.start_ms, w.end_ms]), [words]);

  // ---- vista da timeline
  const fit = useCallback(() => { if (main?.duration_ms) setView({ startMs: 0, msPerPx: Math.max(2, main.duration_ms / winW()) }); }, [main?.duration_ms]);
  useEffect(() => { fit(); setSelected(null); setPlayhead(0); }, [main?.id, fit]);
  const zoom = (f: number) => setView((v) => {
    const dur = main?.duration_ms ?? 0, msPerPx = clamp(v.msPerPx * f, 2, Math.max(dur / winW(), 4));
    return { msPerPx, startMs: clamp(playhead - (playhead - v.startMs) * (msPerPx / v.msPerPx), 0, Math.max(0, dur - winW() * msPerPx)) };
  });
  const reveal = useCallback((s: number, e = s) => setView((v) => {
    const span = winW() * v.msPerPx;
    return s >= v.startMs && e <= v.startMs + span ? v : { ...v, startMs: Math.max(0, s - span * 0.25) };
  }), []);
  const onTime = useCallback((ms: number) => {
    setPlayhead(ms);
    if (player.current?.isPlaying()) setView((v) => (ms > v.startMs + winW() * v.msPerPx * 0.97 ? { ...v, startMs: Math.max(0, ms - winW() * v.msPerPx * 0.1) } : v));
  }, []);

  // ---- ações
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast(ok, "ok"); } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); }
  };
  const inv = (...keys: string[]) => Promise.all(keys.map((k) => qc.invalidateQueries({ queryKey: [k, pid] })));
  const select = (id: string | null) => {
    setSelected(id);
    const s = sugg.find((x) => x.id === id);
    if (s) { reveal(s.start_ms, s.end_ms); player.current?.seek(s.start_ms); setPlayhead(s.start_ms); }
  };
  const decide = (id: string, decision: "accept" | "reject" | "adjust", start?: number, end?: number) =>
    run(async () => { await api(`/projects/${pid}/suggestions/${id}/decision`, { method: "POST", json: { decision, start_ms: start, end_ms: end } }); await inv("suggestions"); });
  const cut = (ids: string[]) => run(async () => {
    if (!main) return;
    for (const id of ids) {
      const s = sugg.find((x) => x.id === id);
      if (s && s.status !== "accepted" && s.status !== "adjusted") await api(`/projects/${pid}/suggestions/${id}/decision`, { method: "POST", json: { decision: "accept" } });
    }
    await ops.apply(ids.map((id) => ({ type: "apply_suggestion", suggestion_id: id })));
  });
  const restore = (s: Suggestion) => ops.apply([{ type: "restore_range", asset_id: main?.id, start_ms: s.start_ms, end_ms: s.end_ms }]);
  const initTimeline = () => main && ops.apply([{ type: "init_main", asset_id: main.id }]);
  const outAt = (src: number): number => {
    if (!doc || !main) return 0;
    const direct = sourceToOutput(doc, main.id, src);
    if (direct !== null) return direct;
    const nk = nextKept(doc, main.id, src);
    return nk.jumpTo !== null ? sourceToOutput(doc, main.id, nk.jumpTo) ?? doc.duration_ms : doc.duration_ms;
  };
  const doInsert = (mode: "b_roll" | "pip" | "sequential", durationMs: number) => {
    if (!insert || !doc) return;
    const at = outAt(insert.sourceMs);
    ops.apply([mode === "sequential"
      ? { type: "insert_sequential", asset_id: insert.asset.id, at_ms: at, duration_ms: durationMs }
      : { type: "insert_overlay", asset_id: insert.asset.id, timeline_start_ms: at, duration_ms: durationMs, mode }]);
    setInsert(null);
  };
  const startUpload = (f: File, role: "main" | "auxiliary") => run(async () => {
    if (!pid) return;
    const form = new FormData(); form.append("file", f); form.append("role", role);
    const set = role === "main" ? setUploading : setAuxUploading;
    set(0);
    try { await upload(`/projects/${pid}/assets`, form, set); toast(`“${f.name}” enviado; processando…`, "ok"); await inv("assets", "jobs"); } finally { set(null); }
  });
  const newProject = (title: string) => run(async () => { const p = await api<{ id: string }>("/projects", { method: "POST", json: { title } }); await qc.invalidateQueries({ queryKey: ["projects"] }); setPid(p.id); });
  const startJob = (path: string, json: unknown, ok: string) => run(async () => { await api(path, { method: "POST", json }); await inv("jobs"); toast(ok, "ok"); setTab("jobs"); });
  const analyze = () => tMeta && startJob(`/projects/${pid}/analyses`, { transcript_id: tMeta.id, script_id: activeScript, use_llm: useLlm ? null : false }, "Análise enfileirada");
  const propose = () => run(async () => {
    setProposing(true);
    try { setProposals(await api<ProposalsResult>(`/projects/${pid}/media/proposals`, { method: "POST", json: { use_llm: useLlm ? null : false } })); } finally { setProposing(false); }
  });
  const applyProposals = (operations: Operation[]) => { setProposals(null); void ops.apply(operations).then(() => toast(`${operations.length} mídia(s) inserida(s)`, "ok")); };
  const runPlan = (prompt: string) => run(async () => {
    setPlanning(true);
    try { setPlan(await api<Plan>(`/projects/${pid}/assistant/plan`, { method: "POST", json: { prompt, use_llm: useLlm ? null : false } })); } finally { setPlanning(false); }
  });
  const applyPlan = () => run(async () => {
    if (!plan) return;
    for (const d of plan.decisions) await api(`/projects/${pid}/suggestions/${d.suggestion_id}/decision`, { method: "POST", json: { decision: d.decision } });
    if (plan.decisions.length) await inv("suggestions");
    if (plan.operations.length) await ops.apply(plan.operations);
    setPlan(null);
  }, "Plano aplicado (desfaça com Ctrl+Z)");
  const addRule = (r: { kind: Rule["kind"]; text: string; params: { phrases?: string[] }; provenance?: Record<string, unknown> }) =>
    run(async () => { await api(`/projects/${pid}/rules`, { method: "POST", json: r }); await inv("rules"); await qc.invalidateQueries({ queryKey: ["rules-suggested", pid] }); }, "Regra criada");
  const patchMeta = (id: string, meta: Record<string, unknown>) => run(async () => { await api(`/projects/${pid}/assets/${id}`, { method: "PATCH", json: meta }); await inv("assets"); });
  const retry = (id: string) => run(async () => { await api(`/jobs/${id}/retry`, { method: "POST" }); await inv("jobs", "renders", "assets"); }, "Job reenfileirado");
  const cancel = (id: string) => run(async () => { await api(`/jobs/${id}/cancel`, { method: "POST" }); await inv("jobs", "renders"); });

  // análise/transcrição concluídas → atualiza dados
  const doneKey = (jobs.data ?? []).filter((j) => j.state === "succeeded").map((j) => j.job_id).join();
  useEffect(() => { void inv("transcripts", "suggestions", "alignment", "assets"); }, [doneKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- atalhos
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable) return;
      const mod = e.ctrlKey || e.metaKey, sIdx = sugg.findIndex((s) => s.id === selected);
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); void (e.shiftKey ? ops.redo() : ops.undo()); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); void ops.redo(); }
      else if (mod || e.altKey) return;
      else if (e.key === " ") { e.preventDefault(); player.current?.toggle(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); e.shiftKey ? player.current?.seek(playhead - 1000) : player.current?.step(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); e.shiftKey ? player.current?.seek(playhead + 1000) : player.current?.step(1); }
      else if (e.key === "[" || e.key === "]") { const n = sugg[clamp(sIdx + (e.key === "]" ? 1 : -1), 0, sugg.length - 1)]; if (n) select(n.id); }
      else if (e.key.toLowerCase() === "a" && selected) void decide(selected, "accept");
      else if (e.key.toLowerCase() === "r" && selected) void decide(selected, "reject");
      else if (e.key.toLowerCase() === "x" && selected) void cut([selected]);
      else if (e.key === "+" || e.key === "=") zoom(0.8);
      else if (e.key === "-") zoom(1.25);
      else if (e.key === "?") setHelp(true);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  const activeJobs = (jobs.data ?? []).filter((j) => j.state === "queued" || j.state === "running").length;
  const staleCount = (renders.data ?? []).filter((r) => r.stale && r.state === "succeeded").length;
  const selSugg = sugg.find((s) => s.id === selected);

  return (
    <div className="app">
      <TopBar projects={projects.data ?? []} pid={pid} onPid={setPid} onNew={newProject} onUpload={(f) => startUpload(f, "main")} uploading={uploading}
        activeJobs={activeJobs} onJobs={() => setTab("jobs")} ops={ops} hasTimeline={!!doc}
        onRender={setRenderDlg} onHelp={() => setHelp(true)} onGuide={() => setGuide(true)} rev={rev} stale={staleCount > 0} />
      {!pid ? (
        <main className="welcome"><h2>Bem-vindo ao Kontrul Editor</h2>
          <p>{projects.isError ? `Não foi possível falar com a API: ${(projects.error as Error).message}. Confira se o servidor está no ar e o token (botão “?”).` : "Crie um projeto, importe o vídeo do podcast e transcreva com WhisperX."}</p>
          {projects.isError && projects.error instanceof ApiError && projects.error.status === 401 && <p className="banner warn">Token inválido. Abra “?” e informe o token.</p>}
        </main>
      ) : (
        <>
          <div className="center">
            <div className="left">
              {main ? (
                <Player pid={pid} main={main} doc={doc} mode={mode} onMode={setMode} onTime={onTime} apiRef={player} assets={assetList}
                  renderUrl={renderUrl.data ?? null} renderStale={!!lastRender?.stale} />
              ) : (
                <div className="empty big">
                  {!mainAsset ? <>
                    <p><strong>Sem vídeo principal.</strong> Importe o vídeo do podcast para começar.</p>
                    <label className="btn primary">Importar vídeo<Hint id="import" /><input type="file" accept="video/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) startUpload(f, "main"); e.target.value = ""; }} /></label>
                    {uploading !== null && <p>Enviando… {Math.round(uploading * 100)}%</p>}
                  </> : mainAsset.status === "failed" ? <p className="banner warn" role="alert">Erro ao processar o vídeo ({mainAsset.error ?? "codec não suportado"}). Tente outro arquivo.</p>
                    : <p>Processando “{mainAsset.filename}” (probe, proxy e miniatura)…</p>}
                </div>
              )}
              {main && !doc && <div className="banner">A timeline ainda não foi criada. <button className="btn primary" onClick={initTimeline}>Iniciar edição</button><Hint id="init" /></div>}
            </div>
            <aside className="side" aria-label="Painéis">
              <div role="tablist" className="tabs">
                {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => setTab(k)}>
                  {label}{k === "occ" && sugg.length ? ` (${sugg.length})` : ""}{k === "jobs" && activeJobs ? ` •${activeJobs}` : ""}</button>)}
              </div>
              <div className="panel" role="tabpanel">
                {tab === "occ" && (main ? <Occurrences suggestions={sugg} doc={doc} main={main} words={words} selectedId={selected} hasTranscript={!!tMeta}
                  onSelect={select} onPlay={(s) => { setSelected(s.id); reveal(s.start_ms, s.end_ms); player.current?.playRange(Math.max(0, s.start_ms - 1000), s.end_ms); }}
                  onDecide={decide} onCut={cut} onRestore={restore} /> : <div className="empty">Importe um vídeo para ver ocorrências.</div>)}
                {tab === "transcript" && <TranscriptPanel t={transcript.data} loading={transcript.isLoading} playhead={playhead} suggestions={sugg}
                  onSeek={(ms) => { player.current?.seek(ms); setPlayhead(ms); reveal(ms); }}
                  onEditWord={(idx, text) => run(async () => { await api(`/projects/${pid}/transcriptions/${tMeta!.id}/words/${idx}`, { method: "PATCH", json: { text } }); await qc.invalidateQueries({ queryKey: ["transcript", pid, tMeta!.id] }); })} />}
                {tab === "script" && <ScriptPanel scripts={scripts.data ?? []} scriptId={activeScript} onScript={setScriptId} alignment={alignment.data ?? []} transcript={transcript.data}
                  onSave={(text) => run(async () => { const s = await api<{ id: string }>(`/projects/${pid}/scripts`, { method: "POST", json: { text } }); await inv("scripts"); setScriptId(s.id); }, "Roteiro salvo")}
                  onFile={(f) => run(async () => { const form = new FormData(); form.append("file", f); const s = await api<{ id: string }>(`/projects/${pid}/scripts`, { method: "POST", body: form }); await inv("scripts"); setScriptId(s.id); }, "Roteiro enviado")}
                  onSeek={(ms) => { player.current?.seek(ms); setPlayhead(ms); reveal(ms); }}
                  onToggle={(a: Alignment) => run(async () => { await api(`/projects/${pid}/scripts/${activeScript}/alignment/${a.id}`, { method: "PATCH", json: { kind: a.kind === "matched" ? "off_script" : "matched" } }); await inv("alignment"); })}
                  onAnalyze={analyze} canAnalyze={!!tMeta && !!activeScript} busy={false} />}
                {tab === "ai" && <AIPanel transcripts={mainTranscripts} jobs={jobs.data ?? []} suggestions={sugg} canTranscribe={!!main} hasScript={!!activeScript} busy={false}
                  onTranscribe={(language, diarize) => main && startJob(`/projects/${pid}/transcriptions`, { asset_id: main.id, language, diarize }, "Transcrição enfileirada")} onAnalyze={analyze}
                  llm={llmStatus.data} useLlm={useLlm} onUseLlm={setUseLlm}
                  lastLlm={(jobs.data ?? []).find((j) => j.kind === "analyze" && j.state === "succeeded")?.result?.llm as LlmReport | undefined}
                  plan={plan} planning={planning} canPlan={!!doc} onPlan={runPlan} onApplyPlan={applyPlan} onClearPlan={() => setPlan(null)}
                  rules={rules.data ?? []} suggestedRules={suggestedRules.data ?? []} onAddRule={addRule}
                  onToggleRule={(r) => run(async () => { await api(`/projects/${pid}/rules/${r.id}`, { method: "PATCH", json: { enabled: !r.enabled } }); await inv("rules"); })}
                  onDeleteRule={(r) => run(async () => { await api(`/projects/${pid}/rules/${r.id}`, { method: "DELETE" }); await inv("rules"); await qc.invalidateQueries({ queryKey: ["rules-suggested", pid] }); }, "Regra apagada")} />}
                {tab === "library" && <Library pid={pid} assets={assetList} onUpload={startUpload} uploading={auxUploading} canInsert={!!doc}
                  onTags={(id, tags, description) => run(async () => { await api(`/projects/${pid}/assets/${id}`, { method: "PATCH", json: { tags, description } }); await inv("assets"); })}
                  onInsert={(a) => setInsert({ asset: a, sourceMs: playhead })}
                  onMeta={patchMeta} onPropose={propose} proposing={proposing} hasTranscript={!!tMeta} />}
                {tab === "jobs" && <JobsPanel pid={pid} jobs={jobs.data ?? []} renders={renders.data ?? []} onCancel={cancel} onRetry={retry} />}
              </div>
            </aside>
          </div>
          <section className="bottom" aria-label="Timeline">
            <div className="tl-bar">
              <strong>Timeline</strong><Hint id="timeline" />
              <span className="muted">r{rev}{doc ? ` · saída ${fmtTime(doc.duration_ms)}` : ""}{selSugg ? ` · selecionada ${fmtTime(selSugg.start_ms)}–${fmtTime(selSugg.end_ms)}` : ""}</span>
              <span className="spacer" />
              <button className="btn" onClick={() => zoom(1.25)} aria-label="Reduzir zoom">−</button>
              <button className="btn" onClick={fit}>Ajustar</button>
              <button className="btn" onClick={() => zoom(0.8)} aria-label="Aumentar zoom">+</button>
            </div>
            {main ? <Timeline main={main} doc={doc} suggestions={sugg} selectedId={selected} playhead={playhead} view={view} waveform={waveform.data}
              snapPoints={snapPoints} assets={assetList} onView={setView} onSelect={select}
              onSeek={(ms) => { player.current?.seek(ms); setPlayhead(ms); }}
              onAdjust={(id, s, e) => void decide(id, "adjust", s, e)}
              onDropAsset={(id, ms) => { const a = assetList.find((x) => x.id === id); if (!a) return; if (!doc) toast("Inicie a edição antes de inserir mídias.", "error"); else setInsert({ asset: a, sourceMs: ms }); }} />
              : <div className="empty">A timeline aparece quando o vídeo principal estiver pronto.</div>}
          </section>
        </>
      )}
      {renderDlg && <RenderModal profile={renderDlg} revision={rev} renders={renders.data ?? []} busy={false} onClose={() => setRenderDlg(null)}
        onConfirm={(profile, fitPolicy) => { setRenderDlg(null); void startJob(`/projects/${pid}/renders`, { profile, fit: fitPolicy }, profile === "final" ? "Render final enfileirado" : "Preview enfileirado").then(() => inv("renders")); }} />}
      {insert && doc && <InsertModal asset={insert.asset} outputMs={outAt(insert.sourceMs)} maxMs={Math.max(0, doc.duration_ms - outAt(insert.sourceMs))} onClose={() => setInsert(null)} onConfirm={doInsert} />}
      {proposals && <ProposalsModal result={proposals} onApply={applyProposals} onClose={() => setProposals(null)} />}
      {guide && <GuideModal onClose={() => setGuide(false)} />}
      {help && <HelpModal token={getToken()} onToken={(t) => { setToken(t); void qc.invalidateQueries(); }} onClose={() => setHelp(false)} />}
    </div>
  );
}

function TopBar(p: {
  projects: { id: string; title: string }[]; pid?: string; onPid: (id: string) => void; onNew: (t: string) => void;
  onUpload: (f: File) => void; uploading: number | null; activeJobs: number; onJobs: () => void;
  ops: ReturnType<typeof useTimelineOps>; hasTimeline: boolean; onRender: (p: "preview" | "final") => void; onHelp: () => void; onGuide: () => void; rev: number; stale: boolean;
}) {
  const { enabled, setEnabled } = useHints();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const file = useRef<HTMLInputElement>(null);
  return (
    <header className="topbar">
      <h1>Kontrul Editor</h1>
      <label className="sr-only" htmlFor="proj">Projeto</label>
      <select id="proj" value={p.pid ?? ""} onChange={(e) => e.target.value && p.onPid(e.target.value)}>
        {!p.pid && <option value="">Selecione um projeto</option>}
        {p.projects.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
      </select>
      {adding ? (
        <form className="inline" onSubmit={(e) => { e.preventDefault(); if (title.trim()) { p.onNew(title.trim()); setTitle(""); setAdding(false); } }}>
          <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Título do projeto" aria-label="Título do novo projeto" />
          <button className="btn primary" type="submit">Criar</button><button className="btn" type="button" onClick={() => setAdding(false)}>×</button>
        </form>
      ) : <button className="btn" onClick={() => setAdding(true)}>＋ Novo projeto</button>}
      {p.pid && <>
        <button className="btn" onClick={() => file.current?.click()}>⬆ Importar vídeo{p.uploading !== null ? ` ${Math.round(p.uploading * 100)}%` : ""}</button><Hint id="import" />
        <input ref={file} type="file" accept="video/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onUpload(f); e.target.value = ""; }} />
        <button className="btn" onClick={() => void p.ops.undo()} disabled={!p.hasTimeline} title="Ctrl+Z">↶ Desfazer</button>
        <button className="btn" onClick={() => void p.ops.redo()} disabled={!p.hasTimeline} title="Ctrl+Shift+Z">↷ Refazer</button><Hint id="undo" />
      </>}
      <span className="spacer" />
      {p.pid && <>
        <button className="btn jobchip" onClick={p.onJobs}>{p.activeJobs ? `⏳ ${p.activeJobs} job(s)` : "Jobs"}</button><Hint id="jobs" />
        <button className="btn" disabled={!p.hasTimeline} onClick={() => p.onRender("preview")}>Gerar Preview{p.stale ? " ⚠" : ""}</button>
        <button className="btn primary" disabled={!p.hasTimeline} onClick={() => p.onRender("final")}>Gerar Vídeo Final</button><Hint id="render" />
      </>}
      <button className="btn" aria-pressed={enabled} onClick={() => setEnabled(!enabled)} title="Mostrar/esconder os balões de dica">💡 Dicas {enabled ? "ligadas" : "desligadas"}</button>
      <button className="btn" onClick={p.onGuide} title="Tudo o que o editor faz">📘 Guia</button>
      <button className="btn" onClick={p.onHelp} aria-label="Atalhos e configuração">?</button>
    </header>
  );
}
