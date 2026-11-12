export interface Project { id: string; title: string; status: string; current_revision: number; created_at: string }
export interface Asset {
  id: string; project_id: string; role: "main" | "auxiliary"; kind: string; filename: string; size_bytes: number;
  duration_ms: number | null; width: number | null; height: number | null; fps_num: number | null; fps_den: number | null;
  audio_info: Record<string, unknown> | null; tags: string[]; description: string | null;
  priority: number; intended_use: string | null; suggested_duration_ms: number | null;
  status: "uploaded" | "processing" | "ready" | "failed"; error: string | null; has_proxy: boolean; has_thumbnail: boolean;
}
export interface Job {
  job_id: string; project_id: string; kind: string; state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number; timeline_revision: number | null; result: Record<string, unknown> | null;
  error: { code: string; message: string } | null; created_at: string;
}
export type Category = "speech_error" | "off_script" | "repetition" | "valid";
export interface Suggestion {
  id: string; asset_id: string | null; script_id: string | null; start_ms: number; end_ms: number; category: Category;
  rationale: string; evidence: { level?: string; rule?: string; reasons?: string[]; removed_text?: string; redo_text?: string;
    memory?: { similar: number; accepted: number; rejected: number; note?: string };
    llm?: { verdict: string; level: string; reason: string; model: string; disputed?: boolean; note?: string; adjusted_from?: number[]; kept_take?: number[] | null };
    llm_extra?: string } | null;
  confidence: number | null; status: "pending" | "accepted" | "rejected" | "adjusted"; origin: "rules" | "rules+llm" | "llm" | string;
}
export interface Segment { w0: number; w1: number; text: string; start_ms: number; end_ms: number; speaker: string | null }
export interface Word { idx: number; text: string; start_ms: number; end_ms: number; confidence: number | null; speaker_id: string | null }
export interface TranscriptMeta { id: string; asset_id: string; model_version: string; language: string | null; revision: number; diarized: boolean }
export interface TranscriptFull extends TranscriptMeta { segments: Segment[]; words: Word[] }
export interface Script { id: string; version: number; format: string; text: string; created_at: string }
export interface Alignment {
  id: string; transcript_id: string | null; script_start: number; script_end: number; word_start_idx: number | null;
  word_end_idx: number | null; adherence: number | null; kind: "matched" | "unspoken" | "off_script";
}
export interface Clip {
  id: string; asset_id: string; track_id: string; source_in_ms: number; source_out_ms: number;
  timeline_start_ms: number; duration_ms: number; mode: "main" | "b_roll" | "pip"; audio_policy: string;
}
export interface TimelineDoc { schema: number; tracks: { id: string; kind: string; order: number }[]; clips: Clip[]; duration_ms: number }
export interface TimelineRev { project_id: string; revision: number; parent_revision: number | null; created_by: string; document: TimelineDoc }
export interface RenderItem {
  job_id: string; profile: "preview" | "final"; state: Job["state"]; progress: number; timeline_revision: number | null;
  stale: boolean; result: Record<string, unknown> | null; error: { code: string; message: string } | null; created_at: string;
}
export interface Waveform { peaks_per_second: number; peaks: number[] }

export interface Rule {
  id: string; project_id: string | null; scope: string; kind: "note" | "ignore_erro_context" | "protect_phrase" | "extra_cue";
  text: string; params: { phrases?: string[] }; enabled: boolean; provenance: { source?: string } | null;
}
export interface SuggestedRule { kind: Rule["kind"]; text: string; params: { phrases: string[] }; provenance: Record<string, unknown> }
export interface Operation { type: string; [k: string]: unknown }
export interface Proposal {
  asset_id: string; filename: string; mode: "b_roll" | "pip"; source_start_ms: number; timeline_start_ms: number; duration_ms: number;
  score: number; level: string; matched_terms: string[]; segment_text: string; rationale: string; operation: Operation; source?: "tags" | "llm";
}
export interface Unmatched { asset_id: string; filename: string; reason: string; message: string }
export interface ProposalsResult { proposals: Proposal[]; unmatched: Unmatched[]; needs_timeline: boolean; llm?: { status: string; accepted?: number } }
export interface PlanStep { text: string; source?: string; recognized: boolean; summary: string; operations: Operation[]; decisions: { suggestion_id: string; decision: string }[]; errors: string[] }
export interface LlmStatus { provider: string; model: string | null; configured: boolean; external: boolean; message: string }
export interface LlmReport { status: string; provider?: string; model?: string; windows_used?: number; windows_total?: number; confirmed?: number; rejected?: number; adjusted?: number; new_findings?: number; dropped_invalid?: number; input_tokens?: number; output_tokens?: number; errors?: string[]; message?: string }
export interface Plan { prompt: string; provider: string; steps: PlanStep[]; operations: Operation[]; decisions: { suggestion_id: string; decision: string }[]; recognized: boolean }
