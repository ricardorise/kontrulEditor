"""Servidor LLM de DEMONSTRAÇÃO (não é um modelo): fala o protocolo do Ollama (/api/chat) e o da OpenAI
(/v1/chat/completions) e responde de forma plausível lendo o prompt. Serve para exercitar o stack inteiro (variáveis,
worker, fila, UI, validação de índices) sem enviar dados a serviço externo. NÃO mede a qualidade de um LLM real.

Uso:  python scripts/fake_llm_server.py [--port 11434] [--host 0.0.0.0]
      KONTRUL_LLM_PROVIDER=ollama KONTRUL_LLM_MODEL=fake KONTRUL_OLLAMA_HOST=http://localhost:11434"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASTIDOR = ("água", "copo", "celular", "câmera", "microfone", "café", "banheiro")
SINONIMOS = {"celular": ["smartphone", "telefone", "aparelho"], "logo": ["marca", "empresa"], "headset": ["óculos", "visor", "quest", "meta"],
             "janelas": ["multitarefa", "dock", "telas"], "meta": ["horizon", "quest"]}


def seg_lines(user: str):
    for ln in user.split("\n"):
        m = re.match(r"S(\d+)(?: .*?)?: (\[\d+\].*)$", ln)  # "S0 00:01.0 …: [0]…" (análise) ou "S0: [0]…" (mídias)
        if m:
            idxs = [int(x) for x in re.findall(r"\[(\d+)\]", m.group(2))]
            text = re.sub(r"\[\d+\]", "", m.group(2)).strip()
            yield int(m.group(1)), idxs, text, "(CONTEXTO" in ln


def analise(user: str) -> dict:
    reviews = [{"candidate_id": m.group(1), "verdict": "confirm", "level": "alta", "reason": "O trecho é uma tentativa descartada seguida de refação.",
                "start_word": None, "end_word": None, "quote": None} for m in re.finditer(r"- id=(c\d+) ", user)]
    findings = []
    for _, idxs, text, ctx in seg_lines(user):
        if not ctx and any(b in text.lower() for b in BASTIDOR) and len(idxs) >= 3:
            findings.append({"category": "off_script", "level": "media", "reason": "Conversa de bastidor sem relação com o tema do episódio.",
                             "start_word": idxs[0], "end_word": idxs[-1], "quote": " ".join(text.split()[:5]), "keep_start": None, "keep_end": None})
    return {"reviews": reviews, "findings": findings}


def associacao(user: str) -> dict:
    try:
        midias = json.loads(re.search(r"<midias>\n(.*?)\n</midias>", user, re.S).group(1))
    except Exception:
        return {"matches": []}
    words = {}
    for _, idxs, text, ctx in seg_lines(user):
        if not ctx:
            for k, w in zip(idxs, text.split()):
                words.setdefault(re.sub(r"\W", "", w.lower()), k)
    out = []
    for m in midias:
        for tag in m.get("tags") or []:
            for cand in SINONIMOS.get(tag.lower(), []):
                if cand in words:
                    out.append({"asset_id": m["id"], "anchor_word": words[cand], "relevance": "alta", "reason": f"A fala menciona «{cand}», sinônimo/assunto de «{tag}»."})
                    break
            else:
                continue
            break
    return {"matches": out}


def assistente(user: str) -> dict:
    return {"steps": [{"summary": "Pedido amplo demais", "intent": "unsupported", "asset_id": None, "phrase": None, "at_ms": None, "start_ms": None,
                       "end_ms": None, "duration_ms": None, "mode": None, "level": None, "apply": None,
                       "reason_unsupported": "Não consigo transformar este pedido em uma edição concreta; diga o trecho ou a mídia."}]}


def responder(system: str, user: str) -> dict:
    if system.startswith("Você revisa transcrições"):
        return analise(user)
    if system.startswith("Você escolhe em que momento"):
        return associacao(user)
    return assistente(user)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        msgs = body.get("messages", [])
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        data = json.dumps(responder(system, user), ensure_ascii=False)
        if self.path.endswith("/api/chat"):
            out = {"model": body.get("model"), "message": {"role": "assistant", "content": data}, "done": True, "done_reason": "stop",
                   "prompt_eval_count": len(user) // 4, "eval_count": len(data) // 4}
        elif self.path.endswith("/chat/completions"):
            out = {"choices": [{"message": {"role": "assistant", "content": data}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": len(data) // 4}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=11434)
    a = ap.parse_args()
    print(f"LLM de demonstração em http://{a.host}:{a.port} (Ollama /api/chat e OpenAI /v1/chat/completions)", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
