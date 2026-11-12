# Modelo de dados e invariantes

## Entidades
- `Project(id, owner_id, title, status, current_revision, created_at)`.
- `Asset(id, project_id, kind, uri, sha256, duration_ms, width, height, fps_num, fps_den, audio_info, tags[], description, created_at)`.
- `Transcript(id, project_id, asset_id, model_version, language, revision)`.
- `Word(id, transcript_id, speaker_id?, start_ms, end_ms, text, confidence?)`.
- `Speaker(id, project_id, label)`.
- `Script(id, project_id, asset_id?, version, format, text, created_at)` e `ScriptAlignment(id, script_id, transcript_id, script_span, word_range?, adherence?, kind)`, com `kind` em matched/unspoken/off_script. Roteiro opcional, versionado e nunca altera a transcrição.
- `Suggestion(id, project_id, source_range, category, rationale, evidence, confidence?, status, model_version, script_id?)`.
- `TimelineRevision(id, project_id, revision, parent_revision?, document_json, created_by, created_at)`.
- `Track(id, kind, order)` e `Clip(id, asset_id, source_in_ms, source_out_ms, timeline_start_ms, duration_ms, track_id, transforms, audio_policy)` embutidos no documento versionado.
- `EditOperation(id, project_id, base_revision, result_revision, type, payload, actor, timestamp)`.
- `RenderJob(id, project_id, timeline_revision, profile, state, progress, artifact_uri?, error_code?)`.
- `Feedback(id, suggestion_id, decision, reason?, corrected_range?, actor)`.
- `EditingRule(id, scope, text, enabled, provenance)`.

## Invariantes
`source_in >= 0`, `source_out > source_in`, source_out <= duração do asset; clips e transições válidos; IDs estáveis; revisões imutáveis; operações idempotentes; jamais sobrescrever mídia original. Intervalos semânticos [início, fim) para evitar ambiguidades.

## Exemplo de proposta estruturada
```json
{
  "project_id": "uuid",
  "base_revision": 4,
  "suggestions": [
    {"type": "remove_range", "asset_id": "uuid", "start_ms": 12400, "end_ms": 16800, "category": "speech_error", "reason": "Falante sinaliza regravação", "confidence": null},
    {"type": "insert_overlay", "asset_id": "uuid-media", "timeline_start_ms": 36000, "duration_ms": 5000, "mode": "b_roll", "audio_policy": "keep_primary"}
  ]
}
```
`confidence: null` significa ausência de score calibrado, não zero. Payload precisa de validação de schema e contexto antes de aplicar.
