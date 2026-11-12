# Interface e experiência

## Layout desktop
Topo: projeto, importação, estado dos jobs, ações `Gerar Preview` e `Gerar Vídeo Final` independentes.
Centro: player de vídeo, controles de reprodução, resolução proxy, comparação original/editado.
Abaixo: timeline multitrilha com ruler, waveform, zoom, playhead, seleção, snapping; vermelho para erros, amarelo para bastidor/fora de contexto; mídia complementar em trilhas próprias.
Painel inferior/lateral: lista de ocorrências com cor, timestamp, transcrição, justificativa, status, ações aceitar/rejeitar/ajustar/excluir e filtros; selecionar item realça intervalo correspondente na timeline.
Painel de IA: prompt contextual, propostas, justificativas, feedback e regras aprendidas.
Roteiro: campo para colar texto ou enviar arquivo (opcional); visão lado a lado roteiro/transcrição com aderência destacada, trechos não falados e falas fora do roteiro; correção manual do alinhamento; clicar num trecho do roteiro leva ao ponto na timeline.
Biblioteca: grid/lista de imagens e vídeos anexados, tags editáveis, busca, preview e drag-and-drop.

## Interações
- Clique em ocorrência: scroll/zoom para intervalo e highlight; duplo clique reproduz trecho.
- Arrastar bordas de seleção: ajusta início/fim com snap opcional; preview de áudio/vídeo.
- Cortes: operações reversíveis, undo/redo e histórico de versões.
- Inserção de B-roll: escolha de camada, duração, modo de composição e áudio original.
- Botões de render: modal simples com perfil e revisão atual; render final disponível mesmo sem preview.
- Mostrar aviso se preview é de revisão anterior; não bloquear render final.
- Status de jobs com progresso, falhas recuperáveis e link para artefatos quando disponíveis.

## Acessibilidade
Atalhos de teclado, foco visível, labels textuais além das cores, contraste adequado, controle por teclado, responsividade básica. Cores não devem ser a única forma de distinguir categorias.

## Estados vazios e erros
Sem vídeo; upload em andamento; transcrição indisponível; IA sem sugestões; mídia sem correspondência; render em fila; erro de codec; job cancelado. Cada estado deve explicar próxima ação.
