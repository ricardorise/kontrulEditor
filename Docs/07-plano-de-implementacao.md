# Plano de implementação e testes

## Fase 0 — Auditoria do código existente
Inspecionar repositório, stack, módulos, licenças e workflows atuais. Reutilizar WhisperX/FFmpeg existentes quando corretos; registrar gaps. Não reescrever sem justificativa. Entregar ADRs e baseline de testes.

## Fase 1 — Fundação headless
Modelos de dados, migrações, storage, ingestão, FFprobe, fila de jobs, autenticação mínima, APIs e testes. Critério: projeto e asset criados via API sem UI.

## Fase 2 — Transcrição e análise
WhisperX, alinhamento, diarização opcional, regras + LLM estruturado, sugestões e revisão. Critério: marcações com timestamp/justificativa e validação contra ground truth.

## Fase 3 — Motor de timeline e render
Operações não destrutivas, revisões, compilador FFmpeg, áudio sincronizado, preview e final independentes. Critério: mesma revisão gera montagem equivalente em baixa resolução e 1080p; export final funciona sem preview.

## Fase 4 — UI de edição
Player, timeline, lista sincronizada, cores, edição manual, biblioteca, prompts, undo/redo e status. Critério: todas as ações UI utilizam APIs públicas.

## Fase 5 — Mídias auxiliares e MCP
Inserção por tags/semântica, B-roll/PiP, MCP adapter, automação ponta a ponta e memória de feedback. Critério: agente cria projeto, edita e exporta sem UI; usuário reabre na UI e continua.

## Fase 6 — Robustez
Testes de carga e GPU, VFR, diferentes codecs, áudio multicanal, segurança, observabilidade, recuperação, concorrência e documentação operacional.

## Testes essenciais
- Unitários: validação de intervalos, timebase, operações, conflito de revisões.
- Integração: upload->transcrição->sugestão->timeline->render.
- E2E: fluxo UI e fluxo headless com mesmo resultado semântico.
- Golden videos: frame/audio alignment, transições, B-roll, 1080p, proporção.
- Falhas: arquivo corrompido, worker morto, timeout, reenvio idempotente, sem GPU, cancelamento.
- Segurança: path traversal, prompt injection, upload malicioso, permissões entre projetos.

## Definição de pronto
Código testado, migrações, README de execução, docker-compose, OpenAPI, schemas MCP, exemplos de requests, evidência de testes, decisões arquiteturais e limitações documentadas.
