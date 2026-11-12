# ADR 0003 — Execução em Docker Compose (Fase 7)

Status: aceito.

## Serviços
| Serviço | Imagem | Função |
|---|---|---|
| `postgres` | postgres:16-alpine | dados (volume `pgdata`) |
| `redis` | redis:7-alpine | fila Dramatiq, `appendonly` (volume `redisdata`) |
| `migrate` | `kontrul/app` | `alembic upgrade head` uma vez; a `api` só sobe depois |
| `api` | `kontrul/app` | FastAPI + reaper de jobs; healthcheck em `/health/ready` |
| `worker` | `kontrul/app` | filas `ingest` e `analyze` |
| `worker-render` | `kontrul/app` | fila `render` (FFmpeg) |
| `worker-asr` | `kontrul/asr` | fila `transcribe` (WhisperX); GPU via `docker-compose.gpu.yml` |
| `web` | `kontrul/web` | nginx: serve o build do Vite e faz proxy de `/v1` |

Volumes: `data` (mídia, renders — compartilhado entre api/workers), `hfcache` (modelos do WhisperX, evita re-download).

## Decisões
- **Duas imagens Python**: `app` (leve, sem torch) e `asr` (torch/WhisperX). Base **Debian trixie** porque o render usa `-/filter_complex` (FFmpeg ≥ 7); `/health/ready` falha se o FFmpeg for < 7.
- **Token no nginx**: o `web` injeta `Authorization: Bearer $KONTRUL_API_TOKEN` no proxy de `/v1`; o navegador nunca recebe o token. Consequência: **quem alcança a porta do `web` tem acesso total**. Por isso o padrão é `127.0.0.1:8080`. Para acesso remoto (`KONTRUL_BIND=0.0.0.0`), coloque autenticação/TLS na frente (VPN, proxy reverso com login).
- API também em `127.0.0.1:8000` (só local) para o adaptador MCP, que usa o token do `.env`.
- `KONTRUL_ENV=production`: a API recusa subir com token padrão/curto. `make env` gera tokens aleatórios em `.env` (fora do git).
- **GPU**: `docker-compose.gpu.yml` reserva a GPU para o `worker-asr` e usa `large-v3`; `make up` aplica o override sozinho se detectar o runtime `nvidia`. **Sem o nvidia-container-toolkit** o worker roda em CPU/int8 com o modelo `small` (funciona, bem mais lento). Instalação (host, requer sudo): `nvidia-container-toolkit` + `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`.
- **GPU sem degradação silenciosa**: `scripts/gpu.sh` detecta runtime nvidia/CDI; o override define `KONTRUL_ASR_DEVICE=cuda`, que faz o ASR falhar com mensagem clara se o PyTorch não enxergar GPU (padrão `auto` mantém o fallback para CPU). `make gpu-check` testa dentro do contêiner; `KONTRUL_GPU=1|0` força o modo.
- Contêineres rodam como usuário não-root (uid 1000); `init: true` para reaping de processos.

## Operação
`make env && make up` · `make ps` · `make logs` · `make smoke` · `make down` (os volumes permanecem; `docker compose down -v` apaga os dados).
Backup: `pgdata` e `data` são os únicos estados. Atualizar: `git pull && make up` (as migrações rodam sozinhas).

## Limites conhecidos
- Single-tenant, token único.
- Imagem `asr` é grande (≈ 13 GB em disco; torch + bibliotecas CUDA). `app` ≈ 1 GB, `web` ≈ 74 MB.
- O caminho **com GPU em contêiner não foi testado** (o host não tem o nvidia-container-toolkit): só a validação do override (`docker compose config`). O caminho em CPU foi testado ponta a ponta.
- Render usa libx264 em CPU; NVENC está disponível no FFmpeg do host mas não é usado.
