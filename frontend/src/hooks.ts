import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { api, ApiError } from "./api";
import type { Alignment, Asset, Job, LlmStatus, Project, RenderItem, Rule, Script, SuggestedRule, Suggestion, TimelineRev, TranscriptFull, TranscriptMeta, Waveform } from "./types";

const ACTIVE = new Set(["queued", "running"]);

export const useProjects = () => useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
export const useProject = (pid?: string) =>
  useQuery({ queryKey: ["project", pid], queryFn: () => api<Project>(`/projects/${pid}`), enabled: !!pid });
export const useAssets = (pid?: string) =>
  useQuery({
    queryKey: ["assets", pid], enabled: !!pid, queryFn: () => api<Asset[]>(`/projects/${pid}/assets`),
    refetchInterval: (q) => (q.state.data?.some((a) => a.status === "uploaded" || a.status === "processing") ? 1500 : false),
  });
export const useJobs = (pid?: string) =>
  useQuery({
    queryKey: ["jobs", pid], enabled: !!pid, queryFn: () => api<Job[]>(`/projects/${pid}/jobs`),
    refetchInterval: (q) => (q.state.data?.some((j) => ACTIVE.has(j.state)) ? 1200 : 5000),
  });
export const useSuggestions = (pid?: string) =>
  useQuery({ queryKey: ["suggestions", pid], enabled: !!pid, queryFn: () => api<Suggestion[]>(`/projects/${pid}/suggestions`) });
export const useTimeline = (pid?: string, revision?: number) =>
  useQuery({
    queryKey: ["timeline", pid, revision], enabled: !!pid && (revision ?? 0) > 0,
    queryFn: () => api<TimelineRev>(`/projects/${pid}/timeline`),
  });
export const useTranscripts = (pid?: string) =>
  useQuery({ queryKey: ["transcripts", pid], enabled: !!pid, queryFn: () => api<TranscriptMeta[]>(`/projects/${pid}/transcriptions`) });
export const useTranscript = (pid?: string, tid?: string) =>
  useQuery({ queryKey: ["transcript", pid, tid], enabled: !!pid && !!tid, queryFn: () => api<TranscriptFull>(`/projects/${pid}/transcriptions/${tid}`) });
export const useScripts = (pid?: string) =>
  useQuery({ queryKey: ["scripts", pid], enabled: !!pid, queryFn: () => api<Script[]>(`/projects/${pid}/scripts`) });
export const useAlignment = (pid?: string, sid?: string) =>
  useQuery({ queryKey: ["alignment", pid, sid], enabled: !!pid && !!sid, queryFn: () => api<Alignment[]>(`/projects/${pid}/scripts/${sid}/alignment`) });
export const useRenders = (pid?: string) =>
  useQuery({
    queryKey: ["renders", pid], enabled: !!pid, queryFn: () => api<RenderItem[]>(`/projects/${pid}/renders`),
    refetchInterval: (q) => (q.state.data?.some((r) => ACTIVE.has(r.state)) ? 1200 : false),
  });
export const useLlmStatus = () =>
  useQuery({ queryKey: ["llm-status"], queryFn: () => api<LlmStatus>("/llm/status"), staleTime: 60_000 });
export const useRules = (pid?: string) =>
  useQuery({ queryKey: ["rules", pid], enabled: !!pid, queryFn: () => api<Rule[]>(`/projects/${pid}/rules`) });
export const useSuggestedRules = (pid?: string, dep?: number) =>
  useQuery({ queryKey: ["rules-suggested", pid, dep], enabled: !!pid, queryFn: () => api<SuggestedRule[]>(`/projects/${pid}/rules/suggested`) });
export const useWaveform = (pid?: string, aid?: string, enabled = true) =>
  useQuery({ queryKey: ["waveform", pid, aid], enabled: !!pid && !!aid && enabled, staleTime: Infinity, retry: false,
    queryFn: () => api<Waveform>(`/projects/${pid}/assets/${aid}/waveform`) });

/** URL assinada (expira em 1 h; renovamos aos 50 min). */
export const useAssetUrl = (pid?: string, aid?: string, variant: "proxy" | "original" | "thumbnail" = "proxy", enabled = true) =>
  useQuery({
    queryKey: ["asset-url", pid, aid, variant], enabled: !!pid && !!aid && enabled, staleTime: 50 * 60_000, retry: false,
    queryFn: async () => (await api<{ url: string }>(`/projects/${pid}/assets/${aid}/file-url?variant=${variant}`)).url,
  });

export type Op = Record<string, unknown> & { type: string };

/** Operações de timeline com lock otimista e pilhas de undo/redo (revert_to cria nova revisão; o histórico é preservado). */
export function useTimelineOps(pid: string | undefined, currentRevision: number, notify: (msg: string, kind?: "error" | "info") => void) {
  const qc = useQueryClient();
  const undo = useRef<number[]>([]);
  const redo = useRef<number[]>([]);
  const rev = useRef(currentRevision);
  rev.current = currentRevision;

  const refresh = useCallback(async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: ["project", pid] }), qc.invalidateQueries({ queryKey: ["timeline", pid] }),
      qc.invalidateQueries({ queryKey: ["suggestions", pid] }), qc.invalidateQueries({ queryKey: ["renders", pid] })]);
  }, [qc, pid]);

  const run = useMutation({
    mutationFn: async ({ ops, track }: { ops: Op[]; track: boolean }) => {
      const before = rev.current;
      const r = await api<TimelineRev>(`/projects/${pid}/timeline/operations`, { method: "POST", json: { expected_revision: before, operations: ops } });
      return { r, before, track };
    },
    onSuccess: async ({ before, track }) => {
      if (track && before > 0) { undo.current.push(before); redo.current = []; }
      await refresh();
    },
    onError: async (e: unknown) => {
      if (e instanceof ApiError && e.status === 409) notify("A timeline mudou em outro lugar (agente/aba). Recarreguei; tente de novo.", "error");
      else notify(e instanceof Error ? e.message : "falha na operação", "error");
      await refresh();
    },
  });

  const apply = useCallback((ops: Op[]) => run.mutateAsync({ ops, track: true }).catch(() => undefined), [run]);
  const doUndo = useCallback(async () => {
    const t = undo.current.pop();
    if (t === undefined) return notify("Nada para desfazer", "info");
    redo.current.push(rev.current);
    await run.mutateAsync({ ops: [{ type: "revert_to", revision: t }], track: false }).catch(() => undefined);
  }, [run, notify]);
  const doRedo = useCallback(async () => {
    const t = redo.current.pop();
    if (t === undefined) return notify("Nada para refazer", "info");
    undo.current.push(rev.current);
    await run.mutateAsync({ ops: [{ type: "revert_to", revision: t }], track: false }).catch(() => undefined);
  }, [run, notify]);

  return { apply, undo: doUndo, redo: doRedo, busy: run.isPending, canUndo: () => undo.current.length > 0, canRedo: () => redo.current.length > 0 };
}
