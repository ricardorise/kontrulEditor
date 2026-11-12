import { useEffect, useMemo, useRef, useState } from "react";
import { fmtTime } from "../timelineMath";
import type { Suggestion, TranscriptFull } from "../types";
import { Hint } from "./Hint";
import { CAT } from "./Timeline";

interface Props {
  t: TranscriptFull | undefined; loading: boolean; playhead: number; suggestions: Suggestion[];
  onSeek: (ms: number) => void; onEditWord: (idx: number, text: string) => void;
}

export function TranscriptPanel({ t, loading, playhead, suggestions, onSeek, onEditWord }: Props) {
  const [edit, setEdit] = useState<number | null>(null);
  const cur = useRef<HTMLSpanElement | null>(null);
  const curIdx = useMemo(() => {
    if (!t) return -1;
    let lo = 0, hi = t.words.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (t.words[m].start_ms <= playhead) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }, [t, playhead]);
  useEffect(() => { cur.current?.scrollIntoView({ block: "nearest" }); }, [curIdx]);

  if (loading) return <div className="empty">Carregando transcrição…</div>;
  if (!t) return <div className="empty">Transcrição indisponível. Use “Transcrever” na aba IA (WhisperX, GPU).<Hint id="transcribe" /></div>;
  const catAt = (ms: number) => suggestions.find((s) => s.status !== "rejected" && ms >= s.start_ms && ms < s.end_ms)?.category;
  return (
    <div className="transcript" aria-label="Transcrição sincronizada">
      <p className="muted small">{t.model_version} · {t.language} · {t.words.length} palavras · clique numa palavra para ir ao ponto; duplo clique para corrigir o texto (o original é preservado).<Hint id="transcript" /></p>
      {t.segments.map((s, i) => (
        <p key={i} className="seg">
          <button className="seg-time" onClick={() => onSeek(s.start_ms)}>{fmtTime(s.start_ms, 0)}</button>
          {t.words.slice(s.w0, s.w1).map((w) => {
            const c = catAt(w.start_ms);
            return edit === w.idx ? (
              <input key={w.idx} autoFocus defaultValue={w.text} className="word-edit" aria-label="Corrigir palavra"
                onBlur={(e) => { setEdit(null); if (e.target.value.trim() && e.target.value !== w.text) onEditWord(w.idx, e.target.value.trim()); }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEdit(null); }} />
            ) : (
              <span key={w.idx} ref={w.idx === curIdx ? cur : undefined} role="button" tabIndex={-1}
                className={`word${w.idx === curIdx ? " now" : ""}${c ? ` m-${c}` : ""}`} title={c ? CAT[c].label : undefined}
                onClick={() => onSeek(w.start_ms)} onDoubleClick={() => setEdit(w.idx)}>{w.text} </span>
            );
          })}
        </p>
      ))}
    </div>
  );
}
