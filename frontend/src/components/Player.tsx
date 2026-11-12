import { useEffect, useImperativeHandle, useRef, useState, type RefObject } from "react";
import { useAssetUrl } from "../hooks";
import { Hint } from "./Hint";
import { fmtTime, nextKept, overlayClips, sourceToOutput } from "../timelineMath";
import type { Asset, TimelineDoc } from "../types";

export interface PlayerApi {
  seek: (ms: number) => void; toggle: () => void; playRange: (s: number, e: number) => void; step: (frames: number) => void; isPlaying: () => boolean;
}
export type PlayMode = "original" | "edited" | "render";

interface Props {
  pid: string; main: Asset; doc: TimelineDoc | null; mode: PlayMode; renderUrl: string | null; renderStale: boolean;
  onMode: (m: PlayMode) => void; onTime: (ms: number) => void; apiRef: RefObject<PlayerApi | null>; assets: Asset[];
}

export function Player({ pid, main, doc, mode, renderUrl, renderStale, onMode, onTime, apiRef, assets }: Props) {
  const vid = useRef<HTMLVideoElement>(null);
  const rangeEnd = useRef<number | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const url = useAssetUrl(pid, main.id, "proxy");
  const fps = main.fps_num && main.fps_den ? main.fps_num / main.fps_den : 25;
  const docRef = useRef(doc); docRef.current = doc;
  const modeRef = useRef(mode); modeRef.current = mode;

  useImperativeHandle(apiRef, () => ({
    seek: (ms) => { if (vid.current) vid.current.currentTime = Math.max(0, ms) / 1000; setT(ms); },
    toggle: () => { const v = vid.current; if (!v) return; rangeEnd.current = null; v.paused ? void v.play() : v.pause(); },
    playRange: (s, e) => { const v = vid.current; if (!v) return; rangeEnd.current = e; v.currentTime = s / 1000; void v.play(); },
    step: (n) => { const v = vid.current; if (!v) return; v.pause(); v.currentTime = Math.max(0, v.currentTime + n / fps); },
    isPlaying: () => !!vid.current && !vid.current.paused,
  }), [fps]);

  // Laço de reprodução: pula cortes no modo "editado" e para no fim de um trecho ouvido.
  useEffect(() => {
    let last = 0;
    const tick = () => {
      const now = performance.now();
      const v = vid.current;
      if (v) {
        const ms = v.currentTime * 1000;
        const d = docRef.current;
        if (!v.paused) {
          if (rangeEnd.current !== null && ms >= rangeEnd.current) { v.pause(); rangeEnd.current = null; }
          else if (modeRef.current === "edited" && d) {
            const nk = nextKept(d, main.id, ms);
            if (!nk.inKept) {
              if (nk.jumpTo !== null) v.currentTime = nk.jumpTo / 1000;
              else { v.pause(); }
            }
          }
        }
        if (now - last > 66) { last = now; setT(ms); onTime(ms); setPlaying(!v.paused); }
      }
    };
    // setInterval (e não rAF): rAF é throttled/pausado fora de foco e o salto de corte perderia precisão.
    const id = window.setInterval(tick, 25);
    return () => window.clearInterval(id);
  }, [main.id, onTime]);

  const outT = doc ? sourceToOutput(doc, main.id, t) : null;
  const active = mode === "edited" && doc && outT !== null
    ? overlayClips(doc).filter((c) => c.timeline_start_ms <= outT && outT < c.timeline_start_ms + c.duration_ms) : [];

  return (
    <section className="player" aria-label="Player">
      <div className="player-tabs" role="tablist" aria-label="Fonte do player">
        {([["original", "Original"], ["edited", "Editado (ao vivo)"], ["render", "Render gerado"]] as const).map(([m, label]) => (
          <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "tab on" : "tab"} onClick={() => onMode(m)}
            disabled={m === "edited" && !doc || m === "render" && !renderUrl}>{label}</button>
        ))}
        <Hint id="player" />
        <span className="hint">proxy 480p · o render usa a qualidade final</span>
      </div>
      {mode === "render" && renderStale && <div className="banner warn" role="alert">Este render é de uma revisão anterior da timeline (desatualizado).</div>}
      <div className="stage">
        {mode === "render" && renderUrl
          ? <video key="r" src={renderUrl} controls className="video" aria-label="Render gerado" />
          : url.data
            ? <video key={main.id} ref={vid} src={url.data} className="video" preload="auto" playsInline aria-label="Vídeo principal (proxy)" onClick={() => (vid.current?.paused ? void vid.current?.play() : vid.current?.pause())} />
            : <div className="empty">{url.isError ? "Proxy indisponível para este vídeo." : "Carregando vídeo…"}</div>}
        {mode !== "render" && active.map((c) => <OverlayView key={c.id} pid={pid} clip={c} asset={assets.find((a) => a.id === c.asset_id)} />)}
      </div>
      {mode !== "render" && (
        <div className="controls">
          <button onClick={() => apiRef.current?.toggle()} aria-label={playing ? "Pausar" : "Reproduzir"} className="btn primary">{playing ? "❚❚ Pausar" : "▶ Reproduzir"}</button>
          <button className="btn" onClick={() => apiRef.current?.step(-1)} aria-label="Quadro anterior">⏮ −1f</button>
          <button className="btn" onClick={() => apiRef.current?.step(1)} aria-label="Próximo quadro">+1f ⏭</button>
          <span className="time" aria-live="off">origem {fmtTime(t)}{doc && <> · saída {outT === null ? "— (cortado)" : fmtTime(outT)}</>}</span>
        </div>
      )}
    </section>
  );
}

function OverlayView({ pid, clip, asset }: { pid: string; clip: { mode: string }; asset?: Asset }) {
  const isImage = asset?.kind === "image";
  const u = useAssetUrl(pid, asset?.id, isImage ? "original" : "thumbnail", !!asset);
  if (!u.data) return null;
  return (
    <div className={`overlay ${clip.mode}`} title={`${clip.mode === "pip" ? "Picture-in-picture" : "B-roll"}: ${asset?.filename}${isImage ? "" : " (prévia estática; o vídeo entra no render)"}`}>
      <img src={u.data} alt={`Mídia inserida: ${asset?.filename}`} />
      <span className="overlay-tag">{clip.mode === "pip" ? "PiP" : "B-roll"}</span>
    </div>
  );
}
