"""Cliente LLM sobre HTTP (httpx), um adaptador por provedor.

Contrato: `complete_json(system, user, schema, name)` → `LLMResult(data, usage)`. A resposta é sempre JSON que obedece
ao `schema` (tool use na Anthropic, `json_schema` na OpenAI/OpenRouter, `format` no Ollama). Quem chama ainda valida e
desconfia: nada que o modelo devolve é executado, e o conteúdo da transcrição vai como dado, nunca como instrução.
Privacidade: com `llm_provider=none` nenhuma chamada de rede é feita. Chaves nunca aparecem em logs nem em erros."""
import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

log = logging.getLogger("kontrul.llm")
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o-mini"}
PROVIDERS = ("anthropic", "openai", "openrouter", "ollama")


class LLMError(Exception):
    """Falha do LLM (rede, autenticação, saída inválida…). A análise nunca depende dele para terminar."""


@dataclass
class LLMResult:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0
    raw_provider: str = ""


@dataclass
class _Cfg:
    provider: str
    model: str
    key: str
    base: str
    extra: dict = field(default_factory=dict)


def _cfg() -> _Cfg:
    p = settings.llm_provider.strip().lower()
    if p == "none":
        raise LLMError("LLM desativado (KONTRUL_LLM_PROVIDER=none)")
    if p not in PROVIDERS:
        raise LLMError(f"provedor desconhecido: {p!r} (use {', '.join(PROVIDERS)})")
    model = settings.llm_model or DEFAULT_MODEL.get(p, "")
    if not model:
        raise LLMError(f"defina KONTRUL_LLM_MODEL para o provedor {p}")
    key = {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key,
           "openrouter": settings.openrouter_api_key, "ollama": ""}[p]
    if p != "ollama" and not key:
        raise LLMError(f"chave de API ausente para {p} (veja .env.example)")
    base = settings.llm_base_url or {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1",
                                     "openrouter": "https://openrouter.ai/api/v1", "ollama": settings.ollama_host}[p]
    return _Cfg(p, model, key, base.rstrip("/"))


def status() -> dict:
    """Estado para a UI/API: nunca inclui chaves."""
    p = settings.llm_provider.strip().lower()
    out = {"provider": p, "model": None, "configured": False, "external": p in ("anthropic", "openai", "openrouter"),
           "message": "LLM desativado: a análise usa só regras (nada sai da sua máquina)."}
    if p == "none":
        out["external"] = False
        return out
    try:
        c = _cfg()
        out.update(model=c.model, configured=True, message=(
            f"LLM ativo: {c.provider} / {c.model}. O texto da transcrição é enviado a {c.base}." if out["external"]
            else f"LLM local ativo: {c.provider} / {c.model} em {c.base}. Nada sai da sua máquina."))
    except LLMError as e:
        out.update(message=str(e))
    return out


class LLMClient:
    def __init__(self, http: httpx.Client | None = None, sleep=time.sleep):
        self.cfg = _cfg()
        self.http = http or httpx.Client(timeout=settings.llm_timeout_s)
        self.sleep = sleep
        self._no_temperature = False
        self._schema_mode = "json_schema"  # openai/openrouter: json_schema → json_object → plain

    # ---- utilidades
    def _scrub(self, text: str) -> str:
        t = str(text)
        if self.cfg.key:
            t = t.replace(self.cfg.key, "***")
        return t[:400]

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        last = ""
        for attempt in range(4):
            try:
                r = self.http.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}"
                if self.cfg.provider == "ollama":
                    raise LLMError(f"não consegui falar com o Ollama em {self.cfg.base} ({last}). Ele está rodando e o modelo "
                                   f"{self.cfg.model!r} foi baixado (ollama pull)?") from e
            else:
                if r.status_code < 400:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise LLMError("resposta do provedor não é JSON") from e
                last = f"HTTP {r.status_code}: {self._scrub(r.text)}"
                if r.status_code not in RETRY_STATUS:
                    raise LLMError(last)
                ra = r.headers.get("retry-after")
                if ra and ra.isdigit() and attempt < 3:
                    self.sleep(min(int(ra), 20))
                    continue
            if attempt < 3:
                self.sleep(2 ** attempt)
        raise LLMError(f"provedor indisponível após novas tentativas ({last})")

    def _post_adaptive(self, url: str, headers: dict, body: dict, drop: tuple[str, ...]) -> dict:
        """Alguns modelos novos recusam `temperature`/`max_tokens`: na primeira 400 que cita o parâmetro, tenta sem ele."""
        try:
            return self._post(url, headers, body)
        except LLMError as e:
            msg = str(e).lower()
            bad = [k for k in drop if k in msg and k in body]
            if "http 400" in msg and bad:
                body = {k: v for k, v in body.items() if k not in bad}
                if "temperature" in bad:
                    self._no_temperature = True
                return self._post(url, headers, body)
            raise

    # ---- API pública
    def complete_json(self, system: str, user: str, schema: dict, name: str = "resposta", max_tokens: int | None = None) -> LLMResult:
        mt = max_tokens or settings.llm_max_tokens
        fn = {"anthropic": self._anthropic, "openai": self._openai, "openrouter": self._openai, "ollama": self._ollama}[self.cfg.provider]
        res = fn(system, user, schema, name, mt)
        res.raw_provider = f"{self.cfg.provider}/{self.cfg.model}"
        return res

    # ---- Anthropic: tool use forçado = JSON conforme o schema
    def _anthropic(self, system, user, schema, name, mt) -> LLMResult:
        body = {"model": self.cfg.model, "max_tokens": mt, "system": system,
                "messages": [{"role": "user", "content": user}],
                "tools": [{"name": name, "description": "Devolva a resposta neste formato.", "input_schema": schema}],
                "tool_choice": {"type": "tool", "name": name}}
        if not self._no_temperature:
            body["temperature"] = 0
        d = self._post_adaptive(f"{self.cfg.base}/v1/messages", {"x-api-key": self.cfg.key, "anthropic-version": "2023-06-01",
                                                                  "content-type": "application/json"}, body, ("temperature",))
        if d.get("stop_reason") == "max_tokens":
            raise LLMError("resposta truncada (max_tokens); reduza a janela ou aumente KONTRUL_LLM_MAX_TOKENS")
        block = next((b for b in d.get("content", []) if b.get("type") == "tool_use"), None)
        if not block or not isinstance(block.get("input"), dict):
            raise LLMError("a Anthropic não devolveu a ferramenta esperada")
        u = d.get("usage", {})
        return LLMResult(block["input"], u.get("input_tokens", 0), u.get("output_tokens", 0))

    # ---- OpenAI e OpenRouter (compatíveis): json_schema estrito, com degradação
    def _openai(self, system, user, schema, name, mt) -> LLMResult:
        headers = {"Authorization": f"Bearer {self.cfg.key}", "content-type": "application/json"}
        if self.cfg.provider == "openrouter":
            headers.update({"HTTP-Referer": "http://localhost", "X-Title": "Kontrul Editor"})
        url = f"{self.cfg.base}/chat/completions"
        modes = ["json_schema", "json_object", "plain"]
        for mode in modes[modes.index(self._schema_mode):]:  # recorda a degradação já descoberta para este modelo
            sysmsg = system if mode == "json_schema" else f"{system}\n\nResponda SOMENTE com JSON válido neste schema:\n{json.dumps(schema, ensure_ascii=False)}"
            body = {"model": self.cfg.model, "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                    ("max_completion_tokens" if self.cfg.provider == "openai" else "max_tokens"): mt}
            if not self._no_temperature:
                body["temperature"] = 0
            if mode == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
            elif mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            try:
                d = self._post_adaptive(url, headers, body, ("temperature", "max_completion_tokens", "max_tokens"))
            except LLMError as e:
                m = str(e).lower()
                if "http 400" in m and mode != "plain" and any(k in m for k in ("response_format", "json_schema", "structured", "schema")):
                    self._schema_mode = "json_object" if mode == "json_schema" else "plain"
                    log.info("modelo sem suporte a %s; degradando", mode)
                    continue
                raise
            ch = (d.get("choices") or [{}])[0]
            if ch.get("finish_reason") == "length":
                raise LLMError("resposta truncada (limite de tokens); reduza a janela ou aumente KONTRUL_LLM_MAX_TOKENS")
            msg = ch.get("message", {})
            if msg.get("refusal"):
                raise LLMError("o modelo recusou a tarefa")
            data = _parse_json(msg.get("content") or "")
            u = d.get("usage", {})
            return LLMResult(data, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        raise LLMError("o modelo não devolveu JSON utilizável")

    # ---- Ollama: `format` = JSON schema (saídas estruturadas)
    def _ollama(self, system, user, schema, name, mt) -> LLMResult:
        body = {"model": self.cfg.model, "stream": False, "format": schema,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0, "num_ctx": settings.ollama_num_ctx, "num_predict": mt}}
        d = self._post(f"{self.cfg.base}/api/chat", {"content-type": "application/json"}, body)
        if d.get("done_reason") == "length":
            raise LLMError("resposta truncada (num_predict); reduza a janela")
        return LLMResult(_parse_json((d.get("message") or {}).get("content", "")), d.get("prompt_eval_count", 0), d.get("eval_count", 0))


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):  # alguns modelos embrulham em cerca de código
        t = t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    try:
        v = json.loads(t)
    except ValueError:
        i, j = t.find("{"), t.rfind("}")
        try:
            v = json.loads(t[i:j + 1]) if i >= 0 < j else None
        except ValueError:
            v = None
    if not isinstance(v, dict):
        raise LLMError("a resposta do modelo não é um objeto JSON válido")
    return v


def get_client() -> LLMClient | None:
    """Cliente pronto ou None quando o LLM está desativado/mal configurado (a análise segue só com regras)."""
    if settings.llm_provider.strip().lower() == "none":
        return None
    try:
        return LLMClient()
    except LLMError as e:
        log.warning("LLM indisponível: %s", e)
        return None
