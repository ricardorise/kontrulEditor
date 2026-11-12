# Prompt de execução para agente desenvolvedor

Você é um engenheiro de software sênior responsável por implementar incrementalmente o editor de vídeo inteligente descrito neste pacote. Leia todos os documentos em ordem a partir de `00-README.md` antes de alterar código.

## Instruções obrigatórias
1. Inspecione primeiro o repositório existente; identifique tecnologias, funcionalidades atuais, contratos e testes. Não assuma projeto vazio.
2. Produza um diagnóstico breve, arquitetura-alvo, decisões pendentes e plano de entregas em fases, com dependências.
3. Separe domínio de edição, orquestração, adaptadores WhisperX/FFmpeg/LLM, API, MCP e frontend. Backend deve funcionar sem interface.
4. Implemente em incrementos testáveis, sem trocar stack existente desnecessariamente. Faça migrações e testes junto com cada módulo.
5. Priorize o fluxo vertical: upload -> transcrição -> detecção -> sugestão -> timeline -> preview/final.
6. Não execute cortes irreversíveis; preserve originais e armazene revisões da timeline.
7. Garanta dois comandos independentes: preview de baixa resolução e export final 1080p, sem dependência obrigatória de preview.
8. Exponha serviços por REST/OpenAPI e ferramentas MCP com validação, autenticação e acompanhamento de jobs.
9. Use propostas de edição estruturadas e validadas; nunca execute comandos gerados livremente por LLM.
10. Faça a UI consumir a mesma API dos agentes, com timeline multitrilha, marcações vermelhas/amarelas, lista sincronizada, edição manual e biblioteca de mídias por tags.
11. Não implemente busca externa de mídias no MVP; apenas pontos de integração para outra IA.
12. Documente o que foi implementado, testes executados, resultados, limitações e próximos passos. Nunca declare concluído algo sem verificar.

## Primeiro entregável esperado
Relatório de auditoria do repositório + backlog técnico priorizado + diagrama modular + riscos/decisões abertas. Em seguida, iniciar Fase 1 com testes. Pergunte somente quando uma decisão bloqueadora não puder ser inferida dos documentos ou do repositório.

## Referências
`01-requisitos-funcionais.md`, `02-arquitetura-tecnica.md`, `03-modelo-de-dados.md`, `04-api-e-mcp.md`, `05-pipeline-ia.md`, `06-interface-e-ux.md`, `07-plano-de-implementacao.md`.
