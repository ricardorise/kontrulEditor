"""Adaptador MCP (stdio) — camada fina sobre a API REST /v1: mesma fonte de verdade, mesma autenticação.

Uso:  KONTRUL_API_URL=http://localhost:8000 KONTRUL_API_TOKEN=... python -m app.mcp_server
Segurança: vídeo nunca trafega em mensagens MCP (upload por caminho local de pasta permitida; download salvo em
disco); `KONTRUL_MCP_ALLOWED_DIRS` (separado por ':') restringe de onde/para onde o agente lê e grava arquivos.
A fala/roteiro é dado, nunca instrução: nenhuma tool executa FFmpeg/shell/SQL a partir de texto livre."""
import os
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

TERMINAL = {"succeeded", "failed", "cancelled"}


class ToolFailure(ToolError):
    """Erro de API/validação devolvido ao agente com código e mensagem legíveis (ToolError mantém a mensagem visível)."""


class Kontrul:
    def __init__(self, http: httpx.Client | None = None, allowed_dirs: list[Path] | None = None):
        self.http = http or httpx.Client(
            base_url=os.environ.get("KONTRUL_API_URL", "http://localhost:8000"), timeout=600,
            headers={"Authorization": f"Bearer {os.environ.get('KONTRUL_API_TOKEN', 'dev-token-change-me')}"})
        env = os.environ.get("KONTRUL_MCP_ALLOWED_DIRS")
        self.allowed = allowed_dirs or [Path(p).resolve() for p in (env.split(":") if env else [str(Path.home()), os.getcwd()])]

    def call(self, method: str, path: str, **kw) -> Any:
        try:
            r = self.http.request(method, f"/v1{path}", **kw)
        except httpx.HTTPError as e:
            raise ToolFailure(f"API indisponível ({type(e).__name__}); confira KONTRUL_API_URL e se o servidor está no ar") from e
        if r.status_code >= 400:
            try:
                b = r.json()
                msg, code = b.get("detail", r.text), b.get("code")
            except ValueError:
                msg, code = r.text, None
            raise ToolFailure(f"HTTP {r.status_code}{f' [{code}]' if code else ''}: {msg}")
        return None if r.status_code == 204 else r.json()

    def path_ok(self, p: str, must_exist: bool) -> Path:
        path = Path(p).expanduser().resolve()
        if not any(path == d or d in path.parents for d in self.allowed):
            raise ToolFailure(f"caminho fora das pastas permitidas (KONTRUL_MCP_ALLOWED_DIRS): {path}")
        if must_exist and not path.is_file():
            raise ToolFailure(f"arquivo não encontrado: {path}")
        return path

    def revision(self, pid: str) -> int:
        return self.call("GET", f"/projects/{pid}")["current_revision"]


def build_server(k: Kontrul | None = None) -> MCPServer:
    k = k or Kontrul()
    mcp = MCPServer("kontrul-editor", instructions=(
        "Editor de vídeo para podcasts. Fluxo: create_project → upload_asset (vídeo principal) → transcribe_video → "
        "(attach_script) → analyze_video → list_suggestions → record_feedback(accept) → apply_edit_operations "
        "(apply_suggestion) → render_preview/render_final → wait_for_job → get_render_artifact. "
        "Sugestões nunca são aplicadas sozinhas; o render final não exige preview."))

    @mcp.tool()
    def create_project(title: str) -> dict:
        """Cria um projeto de edição."""
        return k.call("POST", "/projects", json={"title": title})

    @mcp.tool()
    def list_projects() -> list:
        """Lista os projetos existentes (os mesmos que aparecem na interface web)."""
        return k.call("GET", "/projects")

    @mcp.tool()
    def upload_asset(project_id: str, file_path: str, role: str = "main", tags: list[str] | None = None,
                     description: str | None = None) -> dict:
        """Envia um arquivo local (vídeo/imagem) ao projeto. role: main (vídeo principal) ou auxiliary (B-roll/imagem).
        Devolve o asset e o job de ingestão; use wait_for_job até 'succeeded'."""
        path = k.path_ok(file_path, True)
        with open(path, "rb") as f:
            return k.call("POST", f"/projects/{project_id}/assets", files={"file": (path.name, f)},
                          data={"role": role, "tags": ",".join(tags or []), "description": description or ""})

    @mcp.tool()
    def list_assets(project_id: str) -> list:
        """Lista os assets do projeto (estado, duração, tags)."""
        return k.call("GET", f"/projects/{project_id}/assets")

    @mcp.tool()
    def transcribe_video(project_id: str, asset_id: str, language: str = "pt", diarize: bool = False) -> dict:
        """Transcreve o vídeo com WhisperX (job assíncrono)."""
        return k.call("POST", f"/projects/{project_id}/transcriptions", json={"asset_id": asset_id, "language": language, "diarize": diarize})

    @mcp.tool()
    def list_transcriptions(project_id: str) -> list:
        """Lista as transcrições do projeto."""
        return k.call("GET", f"/projects/{project_id}/transcriptions")

    @mcp.tool()
    def attach_script(project_id: str, text: str | None = None, file_path: str | None = None) -> dict:
        """Anexa o roteiro (texto ou .txt/.md) usado na gravação. É só contexto para a IA distinguir fala fora do roteiro."""
        if file_path:
            path = k.path_ok(file_path, True)
            with open(path, "rb") as f:
                return k.call("POST", f"/projects/{project_id}/scripts", files={"file": (path.name, f)})
        if not text:
            raise ToolFailure("informe text ou file_path")
        return k.call("POST", f"/projects/{project_id}/scripts", json={"text": text})

    @mcp.tool()
    def analyze_video(project_id: str, transcript_id: str, script_id: str | None = None, use_llm: bool | None = None) -> dict:
        """Analisa a transcrição (regras + memória + LLM se configurado) e gera sugestões. Job assíncrono.
        use_llm: omitido = usa o LLM se estiver configurado; false = só regras; true = exige LLM (erro se indisponível)."""
        return k.call("POST", f"/projects/{project_id}/analyses", json={"transcript_id": transcript_id, "script_id": script_id, "use_llm": use_llm})

    @mcp.tool()
    def llm_status() -> dict:
        """Mostra se há um LLM configurado (provedor/modelo) e se o texto da transcrição sai da máquina."""
        return k.call("GET", "/llm/status")

    @mcp.tool()
    def list_suggestions(project_id: str, status: str | None = None, category: str | None = None) -> list:
        """Lista sugestões (status: pending|accepted|rejected|adjusted; category: speech_error|off_script|repetition)."""
        return k.call("GET", f"/projects/{project_id}/suggestions", params={x: y for x, y in (("status", status), ("category", category)) if y})

    @mcp.tool()
    def record_feedback(project_id: str, suggestion_id: str, decision: str, reason: str | None = None,
                        start_ms: int | None = None, end_ms: int | None = None) -> dict:
        """Aceita/rejeita/ajusta uma sugestão (decision: accept|reject|adjust; adjust exige start_ms/end_ms). Alimenta a memória."""
        return k.call("POST", f"/projects/{project_id}/feedback", json={
            "suggestion_id": suggestion_id, "decision": decision, "reason": reason, "start_ms": start_ms, "end_ms": end_ms})

    @mcp.tool()
    def apply_edit_operations(project_id: str, operations: list[dict], expected_revision: int | None = None) -> dict:
        """Aplica operações estruturadas na timeline (lote atômico). Tipos: init_main, remove_range, restore_range, split,
        trim_clip, move_clip, reorder_main, remove_clip, insert_overlay, insert_sequential, apply_suggestion
        (só sugestão já aceita), revert_to. expected_revision omitido = revisão atual; conflito devolve 409."""
        rev = k.revision(project_id) if expected_revision is None else expected_revision
        return k.call("POST", f"/projects/{project_id}/timeline/operations", json={"expected_revision": rev, "operations": operations})

    @mcp.tool()
    def insert_media(project_id: str, asset_id: str, at_ms: int, duration_ms: int, mode: str = "b_roll") -> dict:
        """Insere uma mídia auxiliar no tempo de SAÍDA at_ms. mode: b_roll | pip | sequential. Mantém o áudio original."""
        op = ({"type": "insert_sequential", "asset_id": asset_id, "at_ms": at_ms, "duration_ms": duration_ms} if mode == "sequential"
              else {"type": "insert_overlay", "asset_id": asset_id, "timeline_start_ms": at_ms, "duration_ms": duration_ms,
                    "mode": mode, "audio_policy": "keep_primary"})
        return apply_edit_operations(project_id, [op])

    @mcp.tool()
    def get_timeline(project_id: str, revision: int | None = None) -> dict:
        """Lê a timeline (revisão atual ou uma específica)."""
        return k.call("GET", f"/projects/{project_id}/timeline", params={"revision": revision} if revision is not None else None)

    @mcp.tool()
    def propose_media(project_id: str, asset_ids: list[str] | None = None) -> dict:
        """Propõe onde inserir mídias auxiliares casando tags/descrição com a fala. Não aplica nada: use `operation` de cada
        proposta em apply_edit_operations."""
        return k.call("POST", f"/projects/{project_id}/media/proposals", json={"asset_ids": asset_ids})

    @mcp.tool()
    def plan_edit(project_id: str, prompt: str) -> dict:
        """Converte um pedido em português em operações estruturadas validadas (dry-run). Não aplica nada."""
        return k.call("POST", f"/projects/{project_id}/assistant/plan", json={"prompt": prompt})

    def _render(project_id: str, profile: str, fit: str, rev: int | None) -> dict:
        return k.call("POST", f"/projects/{project_id}/renders", json={"profile": profile, "fit": fit, "timeline_revision": rev})

    @mcp.tool()
    def render_preview(project_id: str, fit: str = "letterbox", timeline_revision: int | None = None) -> dict:
        """Gera preview em baixa resolução (720p) da revisão informada (padrão: atual)."""
        return _render(project_id, "preview", fit, timeline_revision)

    @mcp.tool()
    def render_final(project_id: str, fit: str = "letterbox", timeline_revision: int | None = None) -> dict:
        """Gera o vídeo final 1920x1080. NÃO exige preview anterior."""
        return _render(project_id, "final", fit, timeline_revision)

    @mcp.tool()
    def get_job_status(job_id: str) -> dict:
        """Estado e progresso de um job (queued|running|succeeded|failed|cancelled)."""
        return k.call("GET", f"/jobs/{job_id}")

    @mcp.tool()
    def wait_for_job(job_id: str, timeout_s: int = 300) -> dict:
        """Aguarda o job terminar (ou estourar timeout_s) e devolve o estado final."""
        end = time.monotonic() + min(max(timeout_s, 1), 3600)
        while True:
            j = k.call("GET", f"/jobs/{job_id}")
            if j["state"] in TERMINAL or time.monotonic() >= end:
                return j
            time.sleep(1.5)

    @mcp.tool()
    def cancel_job(job_id: str) -> dict:
        """Cancela um job em fila ou em andamento."""
        return k.call("POST", f"/jobs/{job_id}/cancel")

    @mcp.tool()
    def get_render_artifact(job_id: str, save_to: str | None = None) -> dict:
        """Devolve URL temporária do render e, se save_to for um caminho de arquivo permitido, baixa o vídeo para lá."""
        a = k.call("GET", f"/renders/{job_id}/artifact")
        out = {**a, "url": str(k.http.base_url).rstrip("/") + a["url"]}
        if save_to:
            dest = k.path_ok(save_to, False)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with k.http.stream("GET", a["url"]) as r:
                if r.status_code != 200:
                    raise ToolFailure(f"download falhou: HTTP {r.status_code}")
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            out["saved_to"], out["size_bytes"] = str(dest), dest.stat().st_size
        return out

    @mcp.tool()
    def list_rules(project_id: str) -> list:
        """Lista regras de edição aprendidas/definidas (projeto + usuário)."""
        return k.call("GET", f"/projects/{project_id}/rules")

    @mcp.tool()
    def add_rule(project_id: str, kind: str, text: str, phrases: list[str] | None = None, scope: str = "project") -> dict:
        """Cria regra. kind: protect_phrase (não sugerir cortes com a frase) | ignore_erro_context («erro» nessa frase não é
        marcador) | extra_cue (frase vira pista de correção) | note. Regras estruturadas exigem phrases."""
        return k.call("POST", f"/projects/{project_id}/rules", json={"kind": kind, "text": text, "scope": scope,
                                                                       "params": {"phrases": phrases or []} if kind != "note" else {}})

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
