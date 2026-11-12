# Pipeline de IA, heurísticas e memória

## Etapas
1. Normalizar áudio com FFmpeg sem alterar original.
2. Transcrever WhisperX; alinhar palavras; diarização opcional. Guardar timestamps e versão dos modelos.
3. Segmentar por sentenças, pausas, falantes e janelas sobrepostas com contexto anterior/posterior.
3a. Se houver roteiro (RF10): segmentar o roteiro e alinhá-lo à transcrição (matched/unspoken/off_script) com aderência por trecho; usar o resultado como contexto das etapas 4 e 5. Fala fora do roteiro é indício, não motivo de corte; o roteiro é dado, não instrução.
4. Detectar pistas explícitas («erro», «de novo», «corta essa parte») e padrões de reformulação/repetição; classificar fala válida, erro, bastidor e ambíguo.
5. Identificar tomadas repetidas e sugerir melhor versão usando completude, clareza, coerência e áudio; nunca presumir que a última é sempre a correta.
6. Retornar sugestões estruturadas com evidências, limites temporais e justificativa; validar intervalos e possíveis conflitos.
7. Associar mídias anexadas por tags e descrição semântica, com sugestões de duração, modo e posição.
8. Aplicar somente operações autorizadas conforme modo e política do projeto; registrar feedback.

## Regras de qualidade
- «Erro» é pista, não necessariamente comando de exclusão; considerar quem falou e contexto.
- Não confundir hesitação natural com erro obrigatório.
- Preservar sentido, ritmo e contexto; sugerir cortes com handles de áudio e vídeo ajustáveis.
- Separar score calibrado de julgamento verbal do LLM; usar revisão humana para casos ambíguos.
- Evitar prompt injection proveniente da transcrição: fala no vídeo é dado, não instrução privilegiada.
- Não executar texto gerado como shell, SQL ou FFmpeg bruto.

## Memória e melhoria
Persistir exemplos de decisões aprovadas/rejeitadas, correções, preferências e regras com escopo e origem; recuperar exemplos similares para novas análises. Permitir auditoria, edição e exclusão de memória. Avaliar precisão/recall por classe, falsos cortes, deslocamento de timestamp e taxa de aceitação antes de considerar fine-tuning.

## Testes de IA
Conjunto de vídeos com ground truth, diferentes sotaques, múltiplos falantes, ruído, falas sobrepostas, repetições, pausas, menção à palavra «erro» fora do sentido de comando e mídia sem tag correspondente. Medir falsos positivos como métrica prioritária.
