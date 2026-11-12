import type { ReactNode } from "react";

export interface HintDef { area: string; title: string; body: ReactNode }

const K = ({ children }: { children: ReactNode }) => <kbd>{children}</kbd>;

/** Fonte única das dicas: alimenta os balões 💡 e o Guia de recursos. A chave é o `id` usado em <Hint id="…" />. */
export const HINTS: Record<string, HintDef> = {
  import: { area: "Começar", title: "Importar vídeo", body: (<>
    <p>Envia o <b>vídeo principal</b> do podcast. O sistema cria um proxy leve (480p), a miniatura e a forma de onda.</p>
    <p>Aceita mp4, mkv, webm, HEVC, VFR, áudio 5.1… O <b>original nunca é alterado</b>: todo corte é só uma marcação na timeline.</p></>) },
  init: { area: "Começar", title: "Iniciar edição", body: (<>
    <p>Cria a <b>timeline</b> a partir do vídeo importado. É não destrutivo: cortes, mídias e ajustes viram revisões que você pode desfazer.</p>
    <p>Sem a timeline não dá para cortar, inserir mídia, renderizar nem usar o assistente por prompt.</p></>) },
  undo: { area: "Edição", title: "Desfazer e refazer", body: (<>
    <p><K>Ctrl</K>+<K>Z</K> desfaz, <K>Ctrl</K>+<K>Shift</K>+<K>Z</K> refaz.</p>
    <p>Cada edição é uma <b>revisão</b>; desfazer cria uma nova revisão a partir da anterior, então o histórico completo é preservado.</p></>) },
  render: { area: "Exportar", title: "Preview e Vídeo Final", body: (<>
    <p><b>Gerar Preview</b>: baixa resolução (720p), rápido, para conferir os cortes.</p>
    <p><b>Gerar Vídeo Final</b>: 1920×1080. <b>Não exige preview antes</b>; os dois são independentes.</p>
    <p>O ⚠ no botão avisa que o preview é de uma revisão antiga. Você escolhe a proporção: letterbox (barras) ou crop (preenche).</p></>) },
  jobs: { area: "Exportar", title: "Jobs e renders", body: (<>
    <p>Mostra o progresso de importação, transcrição, análise e render.</p>
    <p>Dá para <b>cancelar</b> o que está rodando e <b>tentar de novo</b> o que falhou (inclusive se o worker caiu). Os renders prontos têm “Abrir / baixar”.</p></>) },
  player: { area: "Player", title: "Três formas de assistir", body: (<>
    <p><b>Original</b>: o vídeo sem cortes (proxy 480p).</p>
    <p><b>Editado (ao vivo)</b>: pula os trechos cortados e mostra B-roll/PiP na hora, sem renderizar.</p>
    <p><b>Render gerado</b>: o arquivo de verdade, na qualidade final. Avisa se está desatualizado.</p>
    <p><K>Espaço</K> reproduz/pausa; <K>←</K> <K>→</K> andam um quadro (com <K>Shift</K>, 1 s).</p></>) },
  timeline: { area: "Timeline", title: "Como usar a timeline", body: (<>
    <p><b>Clique ou arraste na régua</b> para mover o cursor. <b>Ctrl + roda</b> dá zoom; a roda rola; <K>+</K>/<K>−</K> também.</p>
    <p><b>Clique num bloco colorido</b> para selecioná-lo e arraste as <b>bordas</b> para ajustar (com ímã nas palavras).</p>
    <p><b>Arraste uma mídia da Biblioteca</b> para cá para inserir B-roll/PiP.</p>
    <p>Cores: <b style={{ color: "#ff8a8a" }}>vermelho</b> erro de fala, <b style={{ color: "#f5c542" }}>amarelo hachurado</b> fora do roteiro, <b style={{ color: "#b79bff" }}>roxo</b> repetição, <b>hachurado cinza</b> trecho cortado.</p></>) },
  occ: { area: "Edição", title: "Ocorrências (sugestões da IA)", body: (<>
    <p><b>Aceitar / Rejeitar</b> alimentam a memória do projeto. <b>Ajustar</b> edita os tempos. <b>✂ Cortar</b> aceita e remove da timeline (reversível). <b>Restaurar</b> devolve o trecho.</p>
    <p><b>Duplo clique</b> (ou ▶ Ouvir) toca só o trecho. Atalhos: <K>A</K> aceita, <K>R</K> rejeita, <K>X</K> corta, <K>[</K> <K>]</K> navegam.</p>
    <p>Selos: confiança alta/média/baixa; <b>🤖 LLM</b> = o LLM participou; <b>LLM discorda</b> = contestada, revise com atenção. Nada é cortado sem você aceitar.</p></>) },
  transcript: { area: "Transcrição", title: "Transcrição sincronizada", body: (<>
    <p><b>Clique numa palavra</b> para ir àquele ponto do vídeo; a palavra atual fica destacada enquanto toca.</p>
    <p><b>Duplo clique</b> corrige o texto (o áudio original é preservado). O sublinhado colorido mostra os trechos que a IA marcou.</p></>) },
  script: { area: "Roteiro", title: "Roteiro da gravação (opcional)", body: (<>
    <p>Cole ou envie o roteiro (.txt/.md). A IA usa só como <b>contexto</b> para distinguir fala fora do roteiro e tomadas repetidas; ele <b>nunca substitui</b> o que foi falado.</p>
    <p>Depois de trocar o roteiro, clique em <b>Analisar com este roteiro</b>. O lado a lado mostra a aderência, e você pode corrigir o alinhamento.</p></>) },
  transcribe: { area: "IA", title: "Transcrever", body: (<>
    <p>Usa o <b>WhisperX</b> (palavra por palavra, com tempo). Escolha o idioma.</p>
    <p><b>Separar falantes</b> exige um <code>HF_TOKEN</code> do Hugging Face no servidor; sem ele a transcrição segue sem falantes. Sem GPU no Docker, roda em CPU (mais lento).</p></>) },
  analyze: { area: "IA", title: "Analisar", body: (<>
    <p>Combina <b>regras</b> (palavra «erro», pistas de correção, repetições, fala fora do roteiro), sua <b>memória</b> de decisões e, se ativo, o <b>LLM</b>.</p>
    <p>Refazer a análise preserva o que você já decidiu. Nada é cortado sem você aceitar.</p></>) },
  llm: { area: "IA", title: "LLM (opcional)", body: (<>
    <p>Desativado por padrão. Ative no <code>.env</code> com <code>KONTRUL_LLM_PROVIDER</code> = anthropic, openai, openrouter ou ollama (local) e a chave.</p>
    <p>Com API externa, o <b>texto da transcrição é enviado</b> ao provedor; com Ollama tudo fica na sua máquina. O card mostra qual está ativo.</p>
    <p>O LLM revisa as regras, acha o que elas perdem, interpreta pedidos livres e associa mídias por significado, com salvaguardas contra erro.</p></>) },
  assistant: { area: "IA", title: "Assistente por prompt", body: (<>
    <p>Peça em português; ele mostra um <b>plano</b> para você revisar e só aplica ao clicar. Exemplos:</p>
    <ul>
      <li>“insira o logo quando eu falar sobre headset”</li>
      <li>“coloque o logo no canto em 0:10 por 3 segundos”</li>
      <li>“insira o clipe em 30s de forma sequencial”</li>
      <li>“corte de 1:20 até 1:35”</li>
      <li>“aceite todas as sugestões de confiança alta” (ou “corte todas…”)</li>
    </ul>
    <p>Vários comandos: separe com <code>;</code> ou linhas. Com LLM, pedidos livres também funcionam. <b>Não faz:</b> render, transcrever, desfazer, dividir/mover clipes. Passos em vermelho foram recusados.</p></>) },
  rules: { area: "IA", title: "Memória e regras", body: (<>
    <p>Suas decisões viram exemplos. Ao rejeitar várias sugestões parecidas, a IA <b>propõe uma regra</b>.</p>
    <p>Tipos: <b>não sugerir corte</b> com uma frase; <b>«erro» nesta frase não é marcador</b>; <b>frase é pista de correção</b>. Dá para desligar ou apagar qualquer regra.</p></>) },
  library: { area: "Mídias", title: "Biblioteca de mídias", body: (<>
    <p>Imagens e vídeos extras. As <b>tags</b> (e a descrição) são o que a IA casa com a fala. Defina também prioridade, duração sugerida e uso (“pip”, “canto”, “logo”).</p>
    <p><b>✨ Sugerir posições</b> propõe onde inserir (nada é aplicado sozinho; com LLM entende sinônimos). Ou <b>arraste</b> a mídia para a timeline, ou use “Inserir no cursor”.</p>
    <p>Mídia sem tag não casa com nada. Busca externa de mídias não faz parte desta versão.</p></>) },
};

/** Ordem do Guia (grupos). */
export const GUIDE_ORDER: string[] = ["import", "init", "player", "timeline", "occ", "transcript", "script", "transcribe", "analyze", "llm", "assistant", "rules", "library", "undo", "render", "jobs"];

export const WORKFLOW: [string, string][] = [
  ["1. Importar", "Envie o vídeo do podcast (⬆ Importar vídeo)."],
  ["2. Iniciar edição", "Cria a timeline não destrutiva."],
  ["3. Transcrever", "Aba IA → WhisperX. Opcional: cole o roteiro na aba Roteiro."],
  ["4. Analisar", "Aba IA → Analisar. As sugestões aparecem em Ocorrências e na timeline."],
  ["5. Revisar", "Aceite, rejeite ou ajuste; ✂ Cortar aplica na timeline."],
  ["6. Mídias", "Biblioteca → tags → Sugerir posições, ou peça no assistente."],
  ["7. Exportar", "Gerar Preview para conferir; Gerar Vídeo Final (1080p) quando estiver bom."],
];
