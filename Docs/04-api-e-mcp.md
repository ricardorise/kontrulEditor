# Contratos REST e MCP

## REST v1 — proposta
- `POST /v1/projects`, `GET /v1/projects/{id}`, `PATCH /v1/projects/{id}`.
- `POST /v1/projects/{id}/assets` (upload multipart ou sessão de upload); `GET /v1/projects/{id}/assets`.
- `POST /v1/projects/{id}/transcriptions` -> job; `GET /v1/projects/{id}/transcriptions`.
- `POST /v1/projects/{id}/scripts` (texto ou arquivo), `GET /v1/projects/{id}/scripts`, `DELETE /v1/projects/{id}/scripts/{script_id}`; `GET .../scripts/{script_id}/alignment` e `PATCH` para correção manual do alinhamento.
- `POST /v1/projects/{id}/analyses` (aceita `script_id` opcional) -> job; `GET /v1/projects/{id}/suggestions`.
- `POST /v1/projects/{id}/suggestions/{suggestion_id}/decision` (accept/reject/adjust).
- `GET /v1/projects/{id}/timeline`; `POST /v1/projects/{id}/timeline/operations` com `expected_revision`.
- `POST /v1/projects/{id}/assistant/plan` (prompt -> propostas estruturadas, sem aplicar automaticamente por padrão).
- `POST /v1/projects/{id}/renders` com `profile: preview|final`, `timeline_revision` -> job.
- `GET /v1/jobs/{id}`; `POST /v1/jobs/{id}/cancel`; `GET /v1/projects/{id}/renders`.
- `GET /v1/renders/{id}/artifact` (URL autorizada temporária).
- `POST /v1/projects/{id}/feedback` e `GET /v1/projects/{id}/history`.

## Resposta padrão para jobs
```json
{"job_id":"uuid","state":"queued","project_id":"uuid","timeline_revision":7,"progress":0,"result":null,"error":null}
```
`POST /renders` com `profile=final` **não** exige preview anterior. O servidor faz snapshot e validações antes de enfileirar.

## MCP (adaptador sobre os mesmos application services)
Tools: `create_project`, `upload_asset` (ou registrar upload autorizado), `transcribe_video`, `attach_script`, `analyze_video` (com `script_id` opcional), `list_suggestions`, `apply_edit_operations`, `insert_media`, `get_timeline`, `render_preview`, `render_final`, `get_job_status`, `get_render_artifact`, `record_feedback`.

## Segurança e ergonomia
Autenticação/autorização por projeto e escopo de ferramenta; tokens com validade curta; validação de payload; limite de recursos; URLs de upload/download assinadas. Evitar passar bytes de vídeo por mensagens MCP; preferir referências de asset e upload autorizado. Webhooks opcionais `job.completed`/`job.failed`, com assinatura e deduplicação. Documentar OpenAPI e schemas de tools com exemplos e códigos de erro 400/401/403/404/409/422/429/5xx.
