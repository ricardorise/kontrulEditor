# ADR 0002 — Robustez e operação (Fase 6)

Status: aceito.

## Recuperação de jobs
- Workers fazem **heartbeat** (`jobs.updated_at`) a cada `KONTRUL_HEARTBEAT_S` (15 s) enquanto trabalham, mesmo sem progresso visível.
- A API roda um **reaper** (30 s): job `running` sem heartbeat há `KONTRUL_JOB_STALE_S` (180 s) vira `failed` com `error.code = worker_lost`.
- `POST /v1/jobs/{id}/retry` cria um novo job com os mesmos parâmetros (falhos/cancelados). Mensagens reentregues pelo broker para um job já terminal são ignoradas (idempotência).
- Filhos do FFmpeg usam `PR_SET_PDEATHSIG`: `kill -9` no worker **não deixa FFmpeg órfão** (verificado: 1 → 0 processos). Render tem *watchdog* de tempo (`KONTRUL_RENDER_TIMEOUT_S`).
- Limite conhecido: jobs `queued` perdidos se o Redis for esvaziado não são recuperados (precisam de retry manual).

## Segurança
- **Uploads**: o ffprobe/ffmpeg rodam com `-protocol_whitelist file,pipe` e só aceitam formatos de uma lista (`hls`, `dash`, `concat`, `sdp`, `rtsp`… são recusados): um upload não faz o servidor abrir rede nem ler arquivos locais (testado com HLS/ffconcat/SDP, incluindo servidor de escuta e arquivo-isca).
- Nomes de arquivo sanitizados (sem `/`, `\`, NUL, bidi); limite de tamanho com 413 e remoção do parcial; roteiro ≤ 2 MB.
- Isolamento entre projetos testado em assets, sugestões, roteiros, regras, transcrições, propostas e operações de timeline. **Modelo de acesso atual: um token único (single-tenant)**; `GET /jobs/{id}` e `/renders/{id}` não são escopados por projeto.
- Texto da fala/roteiro/prompt é dado: nenhum caminho do código executa shell/SQL/FFmpeg a partir dele; o assistente só emite operações validadas.
- `KONTRUL_ENV=production` recusa subir com token padrão ou < 24 caracteres (o token também assina as URLs de download).
- Cotas por projeto (429 + `Retry-After`): renders (3) e transcrições (2) simultâneos.
- Auditoria de dependências: `npm audit` e `pip check` limpos. `pip-audit`: 18 avisos em `torch 2.8.0` e `transformers 4.57.6` (puxados pelo WhisperX, que fixa as versões). Mitigação: só carregamos modelos de fontes confiáveis (Hugging Face/WhisperX), nunca arquivos enviados por usuários, e o ASR não é exposto como serviço de rede. Revisar ao atualizar o WhisperX.

## Concorrência e desempenho
- Edição concorrente: `expected_revision` + `SELECT … FOR UPDATE`; com 8 clientes na mesma revisão, exatamente 1 vence e 7 recebem 409; com retry, 10 edições concorrentes não perdem nenhuma.
- **Defeito corrigido**: pool de conexões (15) menor que as threads do servidor (40) travava a API com 100 clientes. Agora `pool_size=30 + overflow=30`, timeout 10 s e 503 rápido (`overloaded`). Medido contra o servidor real (1 processo): 100 clientes → 471 req/s, p95 258 ms; 200 clientes → 455 req/s, p95 515 ms, 0 erros.
- Análise de ~22 mil palavras (≈1 h de fala): regras < 5 s; alinhamento com roteiro de 22 mil palavras < 20 s (testes).

## Mídia
Matriz testada ponta a ponta (ingestão → corte → render): VFR, HEVC 10 bits, VP9/Opus (webm), MPEG-4/MP3 (mkv), 5.1 (downmix estéreo com sinal), mono, sem áudio, retrato (letterbox e crop), anamórfico (SAR) e rotação por metadado; arquivos vazios/lixo/truncados falham limpo; áudio-only como principal falha no render com mensagem clara. **Defeito corrigido**: SAR ≠ 1 ignorado no render.

## Observabilidade
Logs JSON com `request_id`, `job_id`, `project_id`; `X-Request-ID`; `GET /v1/metrics` (formato Prometheus: jobs por tipo/estado, requisições por *template* de rota); `GET /health/ready` (banco, Redis, FFmpeg, storage, GPU informativo; 503 se degradado). Sem GPU o ASR cai para CPU/int8 (mais lento), registra aviso e marca `model_version` com `(cpu)`.

## Variáveis
`KONTRUL_ENV`, `KONTRUL_JOB_STALE_S`, `KONTRUL_HEARTBEAT_S`, `KONTRUL_RENDER_TIMEOUT_S`, `KONTRUL_MAX_ACTIVE_RENDER_JOBS`, `KONTRUL_MAX_ACTIVE_ASR_JOBS`, `KONTRUL_DB_POOL_SIZE`, `KONTRUL_DB_MAX_OVERFLOW`, `KONTRUL_DB_POOL_TIMEOUT_S`.
