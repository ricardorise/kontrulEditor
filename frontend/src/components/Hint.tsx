import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { HINTS } from "../hintsContent";

const KEY_ON = "kontrul_hints", KEY_SEEN = "kontrul_hints_seen";
const read = <T,>(k: string, d: T): T => { try { const v = localStorage.getItem(k); return v === null ? d : (JSON.parse(v) as T); } catch { return d; } };
const write = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento: segue sem persistir */ } };

interface Ctx { enabled: boolean; setEnabled: (v: boolean) => void; seen: Set<string>; markSeen: (id: string) => void; resetSeen: () => void }
const HintsCtx = createContext<Ctx>({ enabled: true, setEnabled: () => undefined, seen: new Set(), markSeen: () => undefined, resetSeen: () => undefined });
export const useHints = () => useContext(HintsCtx);

export function HintsProvider({ children }: { children: ReactNode }) {
  const [enabled, setOn] = useState<boolean>(() => read(KEY_ON, true));
  const [seen, setSeen] = useState<Set<string>>(() => new Set(read<string[]>(KEY_SEEN, [])));
  const setEnabled = useCallback((v: boolean) => { setOn(v); write(KEY_ON, v); }, []);
  const markSeen = useCallback((id: string) => setSeen((s) => { if (s.has(id)) return s; const n = new Set(s).add(id); write(KEY_SEEN, [...n]); return n; }), []);
  const resetSeen = useCallback(() => { setSeen(new Set()); write(KEY_SEEN, []); }, []);
  return <HintsCtx.Provider value={{ enabled, setEnabled, seen, markSeen, resetSeen }}>{children}</HintsCtx.Provider>;
}

/** Balão 💡 de ajuda contextual. Pulsa até ser aberto pela primeira vez; o conteúdo vem de HINTS[id]. */
export function Hint({ id, className = "" }: { id: string; className?: string }) {
  const { enabled, seen, markSeen } = useHints();
  const def = HINTS[id];
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const uid = `hint-${id}`;

  useLayoutEffect(() => {
    if (!open || !btn.current || !pop.current) return;
    const r = btn.current.getBoundingClientRect(), h = pop.current.offsetHeight, w = pop.current.offsetWidth;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    const below = r.bottom + 8 + h <= window.innerHeight - 8;
    setPos({ left, top: below ? r.bottom + 8 : Math.max(8, r.top - h - 8) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDown = (e: MouseEvent) => { if (!pop.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { close(); btn.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);  // posição é fixa: fecha ao rolar
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true); };
  }, [open]);

  if (!enabled || !def) return null;
  return (
    <>
      <button ref={btn} type="button" className={`hint-dot ${seen.has(id) ? "" : "pulse"} ${className}`} aria-label={`Dica: ${def.title}`}
        aria-expanded={open} aria-controls={open ? uid : undefined} title={`Dica: ${def.title}`}
        onClick={(e) => { e.stopPropagation(); setPos(null); setOpen((o) => !o); markSeen(id); }}>?</button>
      {open && createPortal(
        <div ref={pop} id={uid} role="dialog" aria-label={def.title} className="hint-pop" style={pos ? { top: pos.top, left: pos.left } : { visibility: "hidden", top: 0, left: 0 }}>
          <div className="hint-head"><strong>💡 {def.title}</strong><button type="button" className="hint-x" aria-label="Fechar dica" onClick={() => { setOpen(false); btn.current?.focus(); }}>×</button></div>
          <div className="hint-body">{def.body}</div>
        </div>, document.body)}
    </>
  );
}
