# ADR 0001 — Decisões iniciais

Status: aceito (padrões assumidos; revisáveis).

- **Dev em conda, entrega em Docker Compose.** API, workers e Vite rodam no host (env `kontrulEditor`); Postgres/Redis via `docker-compose.dev.yml`. A entrega final é o `docker-compose.yml` completo.
- **Fila: Dramatiq + Redis**, com filas separadas `transcribe`, `analyze`, `render`.
- **Persistência:** PostgreSQL + SQLAlchemy 2 (síncrono) + Alembic. Arquivos em disco local (`KONTRUL_DATA_DIR`) atrás de uma interface de storage.
- **Auth mínima:** token estático (`KONTRUL_API_TOKEN`) no MVP.
- **Transcrição:** WhisperX `large-v3`, idioma `pt`; diarização desligada por padrão (exige `HF_TOKEN`).
- **LLM:** adaptador com saída JSON validada; análise começa só com regras determinísticas e o LLM é plugado depois.
- **GPU em Docker** depende de `nvidia-container-toolkit` no host (ausente hoje); sem ele o worker de ASR roda em CPU.
- **Pendente:** relação com as skills `kontrul-editor-*`.
