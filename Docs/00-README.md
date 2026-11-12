# Editor de vídeo inteligente — pacote de especificação

## Objetivo
Construir editor de vídeo manual e assistido por IA, API-first/headless, reutilizável por agentes, com transcrição WhisperX, análise contextual, timeline não destrutiva, mídias adicionais, preview e render final.

## Ordem de leitura e implementação
1. `01-requisitos-funcionais.md`: comportamento e critérios de aceite.
2. `02-arquitetura-tecnica.md`: módulos, stack e decisões arquiteturais.
3. `03-modelo-de-dados.md`: entidades, versionamento e contratos.
4. `04-api-e-mcp.md`: operações públicas e ferramentas para agentes.
5. `05-pipeline-ia.md`: detecção, memória e segurança de decisões.
6. `06-interface-e-ux.md`: telas e interações.
7. `07-plano-de-implementacao.md`: fases, testes e entregáveis.
8. `08-prompt-agente.md`: instrução operacional para agente desenvolvedor.

## Premissas e decisões confirmadas
- Modo manual e modo assistido/automatizado coexistem.
- Mídias complementares são anexadas localmente; busca externa é responsabilidade de outra IA, fora do escopo inicial.
- Backend independente da interface, com REST e adaptador MCP.
- Preview opcional em baixa resolução e exportação final 1080p são ações independentes.
- Cortes e inserções são não destrutivos; projeto e histórico persistem.

## Pontos configuráveis (não presumir decisões do usuário)
- Resolução do preview (480p ou 720p), formatos de entrada, FPS e codecs finais.
- Política de aprovação de sugestões, autenticação e implantação.
- Idiomas, política de retenção e hardware disponível.

## Convenções
IDs UUID; tempos armazenados em milissegundos ou frações racionais com conversão explícita; APIs versionadas `/v1`; jobs idempotentes quando possível. Especificações são proposta de implementação, não descrição de sistema já existente.
