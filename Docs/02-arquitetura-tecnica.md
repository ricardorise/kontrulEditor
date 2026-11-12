# Arquitetura técnica

## Estilo
Monólito modular API-first/headless com workers separados para CPU/GPU; contratos internos explícitos para extração futura. Frontend não contém regras de edição. Operações de domínio são iguais para UI, REST e MCP.

## Stack recomendada (sujeita a validação no repositório existente)
- Frontend: React, TypeScript, Vite, TanStack Query; timeline customizada em Canvas/SVG ou biblioteca compatível avaliada por protótipo; player HTML5 com proxies.
- Backend: Python, FastAPI, Pydantic, SQLAlchemy/Alembic.
- Persistência: PostgreSQL; Redis para fila/cache; armazenamento local abstraído ou S3 compatível (MinIO).
- Workers: Celery/RQ/Dramatiq (escolher um após POC), filas separadas `transcribe`, `analyze`, `render`.
- Mídia: FFmpeg/FFprobe, WhisperX (versões fixadas e dependências CUDA verificadas); diarização opcional sujeita a configuração e permissões de modelos.
- LLM: provider adapter com saída JSON validada por schema, suporte a modelo local/remoto.
- Observabilidade: logs estruturados, métricas, traces, correlação por project_id/job_id.

## Módulos
`projects`: projetos e permissões.
`assets`: ingestão, metadados, tags, thumbnails, proxies.
`transcription`: ASR, alinhamento, falantes, revisões.
`analysis`: regras, classificação, sugestões, explicações.
`timeline`: operações e snapshots versionados, validações.
`media-placement`: correspondência semântica e posicionamento.
`render`: compilar timeline em filtergraph/concat seguro, preview/final.
`jobs`: fila, estados, retries, cancelamento.
`learning`: feedback e memória de exemplos.
`api`: REST e OpenAPI.
`mcp-adapter`: ferramentas finas sobre serviços de aplicação.

## Fluxo
Ingestão -> probe/proxy -> transcrição -> análise -> sugestões -> revisão/operações -> snapshot timeline -> render preview ou final -> artefato.

## Princípios críticos
- Separar plano de edição (EDL/timeline JSON) da execução FFmpeg.
- Evitar shell interpolation; construir argumentos FFmpeg com lista de parâmetros e sanitizar caminhos.
- Idempotency-Key para operações custosas e render; optimistic locking com `expected_revision` para evitar perda de edição concorrente.
- Guardar source time e output time separadamente; cuts geram mapeamento entre coordenadas.
- Usar timebase racional/fps e áudio sample rate para precisão; testar VFR, keyframes, crossfades e concatenação.
- Limites de tamanho, quotas, timeout, autenticação, URLs assinadas e isolamento de jobs.
- Políticas de retenção e consentimento para transcrição/voz; controle de acesso aos projetos.

## Deploy inicial
Docker Compose: api, web, postgres, redis, worker-asr, worker-render, storage opcional. GPU por worker quando disponível; execução CPU degradada com indicação de desempenho. Escalabilidade horizontal posterior.
