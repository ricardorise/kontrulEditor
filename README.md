# KontrulEditor

Editor de vídeo inteligente, API-first. Especificação em `Docs/`, decisões em `docs/adr/`.

## Executar com Docker Compose (uso normal)
```bash
make env     # gera .env com tokens fortes (uma vez)
make up      # build + migrações + todos os serviços (aplica GPU sozinho se houver nvidia-container-toolkit)
```
Abra **http://localhost:8080** no Chrome. `make ps` · `make logs` · `make smoke` · `make down`.
Sem GPU no Docker o transcritor roda em CPU (modelo `small`); com o toolkit instalado usa `large-v3` na GPU. Detalhes em `docs/adr/0003-docker-compose.md`.

## Desenvolvimento (conda)
```bash
conda activate kontrulEditor      # ou: conda env create -f environment.yml
cp .env.example .env
make infra       # Postgres + Redis (docker)
make migrate     # Alembic
make api         # http://localhost:8000/docs
make worker      # Dramatiq: ingest + analyze (outro terminal)
make worker-asr  # Dramatiq: transcrição WhisperX na GPU (outro terminal)
make worker-render  # Dramatiq: render FFmpeg (outro terminal)
make web         # frontend em http://localhost:5173 (abra no Chrome)
make test
```
Autenticação: `Authorization: Bearer $KONTRUL_API_TOKEN`.

## Status
- Fase 0 (fundação) e Fase 1 (núcleo headless: projetos, upload/ingestão, jobs): concluídas.
- Fase 2 (transcrição e análise): concluída com as limitações abaixo.
  - WhisperX `large-v3` na GPU, tempo por palavra, texto preservado («erro» não é normalizado).
  - Roteiro opcional (RF10): texto/.txt/.md, versionado, alinhado em ordem à fala (matched / unspoken / off_script).
  - Análise por regras: marcador «erro» (início da tentativa = onde o recomeço repete a frase), pistas de correção, repetição de tomadas, fala fora do roteiro. Sempre sugestão pendente; nada é cortado sozinho.
  - Sugestões: aceitar / rejeitar / ajustar, com `Feedback` registrado.
- Fase 3 (timeline e render): concluída.
  - Timeline não destrutiva com revisões imutáveis, operações em lote atômicas e `expected_revision` (409 em conflito). Operações: `init_main`, `remove_range`, `restore_range`, `split`, `trim_clip`, `move_clip`, `reorder_main`, `remove_clip`, `insert_overlay` (b_roll/pip), `insert_sequential`, `apply_suggestion` (só sugestão aceita/ajustada), `revert_to` (undo).
  - Tempo de origem e de saída guardados separadamente, com mapeamento entre os dois; trilha principal contígua (ripple) e overlays acompanham os cortes.
  - `POST /v1/projects/{id}/renders` com `profile: preview|final` (720p / 1920x1080), `fit: letterbox|crop`. O final **não** exige preview; cada render usa o snapshot da revisão; preview de revisão antiga aparece com `stale: true` sem bloquear nada.
  - Download por URL assinada e temporária (`GET /v1/renders/{id}/artifact` → `/v1/dl/{token}`).
- Fase 4 (interface web): concluída. React + TypeScript + Vite + TanStack Query, consumindo a mesma API pública.
  - Player com proxy (Original / Editado ao vivo, que pula os cortes / Render gerado), overlays B-roll e PiP no ao vivo.
  - Timeline em Canvas: régua, marcações ERRO (vermelho) / FORA (amarelo hachurado) / REPETIÇÃO, trechos cortados, forma de onda, trilhas de overlay, zoom, arrastar bordas com snap, drop de mídia.
  - Ocorrências sincronizadas com a timeline (aceitar, rejeitar, ajustar, cortar, restaurar, ouvir trecho), transcrição clicável e editável, roteiro lado a lado, biblioteca com tags, painel IA, jobs/renders, desfazer/refazer e atalhos (`?`).
  - Acessibilidade: rótulos em texto e padrões além da cor, foco visível, teclado, layout responsivo.
- Fase 5 (mídias, MCP e memória): concluída, sem LLM (ver limitações).
  - Mídias (RF05): prioridade, uso pretendido e duração sugerida por mídia; `POST /media/proposals` casa tags/descrição com a fala e propõe ponto, duração, modo (B-roll/PiP) e justificativa, sem aplicar nada; mídia sem correspondência ou já inserida é listada à parte.
  - Assistente (RF06): `POST /assistant/plan` converte pedidos em português em operações estruturadas validadas por dry-run (nunca FFmpeg/shell); o cliente revisa e aplica pela mesma API de operações.
  - Memória (RF06): feedback vira exemplos auditáveis (`/memory`); sugestões novas são anotadas com decisões parecidas e têm o nível ajustado; rejeições repetidas geram **propostas de regra**; regras (projeto ou globais) podem ser criadas, desligadas e apagadas e passam a valer na análise.
  - MCP: `python -m app.mcp_server` (23 tools, ver abaixo).
- Fase 6 (robustez): concluída (ver `docs/adr/0002-robustez-e-operacao.md`).
  - Recuperação: heartbeat + reaper (`worker_lost`) + `retry`; FFmpeg não fica órfão se o worker morrer; watchdog de render.
  - Segurança: formatos/protocolos do FFmpeg restritos, nomes e tamanhos de upload, isolamento entre projetos, cotas 429, token forte em produção.
  - Concorrência e carga: lock otimista testado com threads; deadlock de pool corrigido (200 clientes sem erro).
  - Mídia: matriz de VFR/HEVC 10 bits/VP9/MKV/5.1/mono/retrato/SAR/rotação; correção de SAR.
  - Observabilidade: logs JSON, `X-Request-ID`, `/v1/metrics`, `/health/ready`; fallback para CPU sinalizado.
- Fase 7 (Docker Compose): ver abaixo e `docs/adr/0003-docker-compose.md`.

## LLM (opcional)
Desativado por padrão (só regras; nada sai da máquina). Para ativar, defina no `.env`:
```
KONTRUL_LLM_PROVIDER=anthropic          # anthropic | openai | openrouter | ollama
KONTRUL_ANTHROPIC_API_KEY=...           # ou KONTRUL_OPENAI_API_KEY / KONTRUL_OPENROUTER_API_KEY; ollama não usa chave
KONTRUL_LLM_MODEL=                      # obrigatório em openrouter/ollama (ex.: llama3.1:8b)
```
e rode `make up`. Com API externa o **texto da transcrição é enviado ao provedor**; com `ollama` tudo fica local. O LLM revisa as sugestões das regras, encontra o que elas não pegam, interpreta pedidos livres e associa mídias por significado, sempre com salvaguardas (ADR 0004). Nunca cole chaves no chat: edite o `.env`.

## Conectar um agente (MCP)
Camada fina sobre a mesma API REST; o que o agente faz aparece na interface e vice-versa.
```json
{ "mcpServers": { "kontrul-editor": {
    "command": "/caminho/do/conda/envs/kontrulEditor/bin/python",
    "args": ["-m", "app.mcp_server"], "cwd": "/caminho/do/projeto/KontrulEditor/backend",
    "env": { "KONTRUL_API_URL": "http://localhost:8000", "KONTRUL_API_TOKEN": "dev-token-change-me",
             "KONTRUL_MCP_ALLOWED_DIRS": "/caminho/dos/seus/videos:/tmp" } } } }
```
Fluxo: `create_project` → `upload_asset` → `transcribe_video` → `attach_script` (opcional) → `analyze_video` → `list_suggestions` → `record_feedback(accept)` → `apply_edit_operations` → `propose_media`/`plan_edit` → `render_final` → `wait_for_job` → `get_render_artifact(save_to=…)`.

## Limitações conhecidas
- Fase 5: o assistente e a associação de mídias são **por regras/palavras** (sem LLM nem embeddings): entendem uma lista fechada de comandos e casam termos, não significado. O contrato foi feito para um provedor semântico entrar depois. A memória ajusta nível de confiança e propõe regras; não treina modelo.
- MCP: transporte stdio (local). Sem autenticação por usuário além do token estático.
- UI: o assistente por prompt está desabilitado (precisa de LLM); a timeline mostra o eixo de **origem** (overlays são posicionados por mapeamento do tempo de saída); overlays de vídeo aparecem como miniatura estática no player ao vivo (o vídeo entra no render); sem loop A/B nem legendas.
- Diarização implementada mas **não testada** (precisa de `HF_TOKEN` e aceite dos termos do pyannote).
- Roteiro em `.docx` ainda não suportado (só texto, `.txt`, `.md`).
- Sem LLM: a classificação é só por regras; `confidence` é sempre `null` e o nível vai em `evidence.level`.
- Alinhamento do roteiro por correspondência de palavras (não semântica).
- Render: só `audio_policy=keep_primary` nos overlays (sem mixagem do áudio do B-roll); sem transições/crossfade nem legendas ainda; codec libx264 em CPU (NVENC disponível, não usado).
- Overlays ficam ancorados ao tempo de saída: cortes antes deles os deslocam, mas `reorder_main` não os move.
- Relatório de cortes (RF09) ainda não exposto; o histórico de operações está em `GET /v1/projects/{id}/history`.
