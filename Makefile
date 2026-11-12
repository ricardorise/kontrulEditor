ENV ?= kontrulEditor
CONDA_RUN = conda run --no-capture-output -n $(ENV)

.PHONY: gpu-check env up down logs build ps smoke infra infra-down migrate api worker worker-asr worker-render web test
infra:        ## Postgres + Redis (docker)
	docker compose -f docker-compose.dev.yml up -d --wait
infra-down:
	docker compose -f docker-compose.dev.yml down
migrate:
	cd backend && $(CONDA_RUN) alembic upgrade head
api:
	cd backend && $(CONDA_RUN) uvicorn app.main:app --reload --port 8000
worker:       ## ingest + analyze
	cd backend && $(CONDA_RUN) dramatiq app.workers.tasks --queues ingest analyze --processes 1 --threads 2
worker-asr:   ## transcrição WhisperX (GPU, 1 job por vez)
	cd backend && $(CONDA_RUN) dramatiq app.workers.tasks --queues transcribe --processes 1 --threads 1
worker-render: ## render FFmpeg
	cd backend && $(CONDA_RUN) dramatiq app.workers.tasks --queues render --processes 1 --threads 1
web:          ## frontend (Vite) em http://localhost:5173
	cd frontend && PATH=$$HOME/.openagents/nodejs/bin:$$PATH npm run dev
test:
	cd backend && $(CONDA_RUN) pytest -q

# ---- Docker Compose (execução completa) -------------------------------------------------------------
# GPU: detectada automaticamente (scripts/gpu.sh). Force com KONTRUL_GPU=1 (exige GPU) ou KONTRUL_GPU=0 (CPU).
GPU_MODE := $(or $(filter 1 0,$(KONTRUL_GPU)),$(if $(filter yes,$(shell scripts/gpu.sh)),1,0))
GPU_FILE := $(if $(filter 1,$(GPU_MODE)),-f docker-compose.gpu.yml)
COMPOSE  := docker compose -f docker-compose.yml $(GPU_FILE)

env:          ## gera .env com tokens fortes (não sobrescreve)
	@test -f .env || { printf 'KONTRUL_API_TOKEN=%s\nPOSTGRES_PASSWORD=%s\nKONTRUL_BIND=127.0.0.1\nKONTRUL_WEB_PORT=8080\n' \
	  "$$(openssl rand -hex 24)" "$$(openssl rand -hex 16)" > .env && chmod 600 .env && echo ".env criado"; }
build: env
	$(COMPOSE) build
up: env       ## sobe tudo (build + migrações + serviços) e espera ficar saudável
	@scripts/gpu.sh --explain
	@echo "Modo GPU do worker-asr: $(if $(filter 1,$(GPU_MODE)),LIGADO (large-v3 em CUDA),desligado (CPU, modelo small))"
	$(COMPOSE) up -d --build --wait
	@echo "Abra http://localhost:$${KONTRUL_WEB_PORT:-8080}"
down:
	$(COMPOSE) down
logs:
	$(COMPOSE) logs -f --tail=100
ps:
	$(COMPOSE) ps
gpu-check:    ## confirma que o worker-asr enxerga a GPU (CUDA) dentro do contêiner
	$(COMPOSE) run --rm --no-deps worker-asr python -c "import torch,sys; ok=torch.cuda.is_available(); print('CUDA disponível:', ok, '|', torch.cuda.get_device_name(0) if ok else '-'); sys.exit(0 if ok else 1)"
smoke:        ## teste ponta a ponta contra o compose em execução
	conda run --no-capture-output -n $(ENV) python scripts/smoke_compose.py
