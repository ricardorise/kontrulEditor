# Requisitos funcionais

## RF01 — Projeto e ingestão
Criar/abrir projetos; enviar vídeo principal e mídias auxiliares (vídeos/imagens); validar MIME, codecs, duração, orientação e metadados via FFprobe; preservar originais; gerar proxies e thumbnails. Persistir estados de processamento e erros.

## RF02 — Transcrição
Extrair áudio, transcrever com WhisperX, alinhar palavras e timestamps, opcionalmente diarizar falantes. Exibir texto sincronizado e permitir correções manuais sem alterar o arquivo original. Registrar idioma e confiança quando disponível.

## RF03 — Classificação contextual
Identificar: (a) erro de fala/tomada inválida, vermelho; (b) conversa de bastidor/fora do roteiro, amarelo; (c) repetição/regravação; (d) trecho válido. Usar a palavra explícita «erro» como pista, não como ordem cega de corte. Para cada sugestão guardar início, fim, categoria, justificativa, evidências, confiança calibrada ou nível qualitativo, estado e origem. Evitar cortar palavras isoladas sem contexto; incluir margens ajustáveis e ouvir limites.

## RF04 — Timeline e edição
Player sincronizado com timeline multitrilha; vídeo principal, sobreposições/B-roll, áudio, legendas. Exibir marcações coloridas e lista de ocorrências; clique na lista destaca intervalo na timeline e move playhead; clicar na timeline seleciona ocorrência. Selecionar, ajustar, aceitar, rejeitar, excluir trecho, restaurar, dividir, mover e reordenar. Zoom, waveform, snapping, loop A/B, undo/redo e histórico versionado. Exclusão é decisão não destrutiva.

## RF05 — Mídias complementares
Upload de imagem/vídeo com tags, descrição, duração sugerida, prioridade e uso pretendido. Inserção manual por drag-and-drop e por prompt. IA associa semântica da transcrição às tags; propõe ponto de entrada, duração, trilha, transição e modo (B-roll com narração original, picture-in-picture ou inserção sequencial). Usuário revisa e ajusta. Não buscar mídia externa no MVP; permitir integração futura por contrato.

## RF06 — Assistente e aprendizagem
Campo de prompt para instruções sobre projeto e regras de edição. IA propõe operações estruturadas, nunca comandos FFmpeg arbitrários. Aceites/rejeições e correções alimentam regras e exemplos recuperáveis por projeto/usuário, com proveniência e possibilidade de remover regra; não prometer treinamento online automático do modelo.

## RF07 — Renderizações independentes
Botão `Gerar Preview`: render de baixa resolução (perfil configurável, sugestão 720p). Botão `Gerar Vídeo Final`: exportação direta em 1920x1080, sem obrigar preview ou aprovação anterior. Ambos disponíveis via API/MCP. Cada render usa snapshot imutável de versão da timeline, mesma lógica de edição, perfis diferentes. Se timeline mudar, sinalizar preview anterior desatualizado; não bloquear exportação direta. Preservar proporção com política configurável (letterbox/crop) e FPS apropriado.

## RF08 — Execução headless
Agente externo cria projeto, anexa mídias, analisa, edita, gera preview, consulta status, solicita exportação final e baixa artefatos sem UI. Projeto iniciado via API pode ser aberto/editado na interface e retomado via agente.

## RF09 — Processamento e auditoria
Jobs assíncronos com estados queued/running/succeeded/failed/cancelled, progresso, logs sanitizados, retry e cancelamento seguro; histórico de operações, autor, origem e versão. Exportar relatório de cortes e mídias inseridas.

## RF10 — Roteiro de gravação (opcional)
O usuário pode fornecer o roteiro usado na gravação (texto colado, `.txt`/`.md` ou `.docx`, associado ao projeto ou a um vídeo específico) para a IA usar como contexto na distinção dos pontos de avaliação para cortes e edição. O roteiro é opcional: sem ele, o fluxo funciona normalmente.
- Alinhamento: a IA alinha o roteiro à transcrição (trechos falados que correspondem ao roteiro, trechos do roteiro não falados, falas fora do roteiro). O alinhamento é exibido e pode ser corrigido manualmente.
- Uso na classificação: fala aderente ao roteiro favorece «trecho válido»; fala fora do roteiro é indício de bastidor/improviso; falas repetidas do mesmo trecho do roteiro indicam candidatas a repetição/regravação, e a IA compara as tomadas usando o roteiro como referência de completude. É pista, não verdade absoluta: o falante pode improvisar ou alterar o texto legitimamente, e trecho fora do roteiro não é cortado automaticamente.
- Sugestões geradas com apoio do roteiro registram a evidência (trecho do roteiro e nível de aderência) na justificativa.
- O roteiro pode ser substituído ou removido; a nova versão gera nova análise sem apagar o histórico. Versões do roteiro são persistidas.
- O conteúdo do roteiro é dado, não instrução para a IA, e segue as mesmas regras de retenção e acesso do projeto.
- Disponível via UI, REST e MCP.

## Critérios de aceite transversais
- Original nunca é sobrescrito.
- Sugestões não aprovadas não são removidas automaticamente em modo manual.
- Cortes respeitam limites válidos, ordem temporal e áudio sincronizado.
- UI e API operam sobre a mesma fonte de verdade.
- Preview e final de uma mesma versão têm cortes e sobreposições equivalentes, salvo diferenças de qualidade.
- Falha em análise ou render não corrompe projeto.
