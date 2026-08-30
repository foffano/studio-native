import React, { useEffect, useState } from "react";
import { getOutput } from "../api.js";

/**
 * Página de uma legenda só, feita para o celular.
 *
 * É o destino do QR code. Antes, o QR carregava o texto dentro dele: a câmera
 * mostrava a legenda e era preciso segurar o dedo para selecionar e copiar —
 * desajeitado justamente no momento em que a pessoa está com o TikTok aberto na
 * outra mão. Aqui existe um botão.
 *
 * Vive em `/?legenda=<id>` e não em `/legenda/<id>` porque o build usa caminhos
 * relativos, herdados do tempo do Electron: numa rota aninhada, os assets não
 * carregariam.
 */
export default function CaptionPage({ outputId }) {
  const [output, setOutput] = useState(null);
  const [erro, setErro] = useState("");
  const [copiado, setCopiado] = useState(false);

  useEffect(() => {
    getOutput(outputId)
      .then(setOutput)
      .catch((e) => setErro(e.message));
  }, [outputId]);

  const texto = output
    ? [
        (output.caption || "").trim(),
        (output.hashtags || []).map((t) => `#${t}`).join(" "),
      ]
        .filter(Boolean)
        .join("\n\n")
    : "";

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2500);
    } catch (_) {
      // Safari no iOS recusa a área de transferência fora de um gesto direto,
      // e em http:// sem TLS ela nem existe. Selecionar o texto continua
      // funcionando, então dizemos isso em vez de falhar em silêncio.
      setErro("Seu navegador bloqueou a cópia. Segure o texto acima para copiar.");
    }
  }

  return (
    <div className="caption-page">
      <h1 className="caption-page__title">Legenda do post</h1>

      {erro && <p className="caption-page__erro">{erro}</p>}

      {!output && !erro && <p className="muted">Carregando...</p>}

      {output && (
        <>
          {output.phrase && (
            <p className="caption-page__frase">{output.phrase}</p>
          )}

          <pre className="caption-page__texto">{texto}</pre>

          <button
            className={"caption-page__btn" + (copiado ? " is-ok" : "")}
            onClick={copiar}
          >
            {copiado ? "Copiado!" : "Copiar legenda"}
          </button>

          <p className="caption-page__ajuda">
            Agora abra o TikTok, toque na notificação do vídeo na Caixa de
            entrada e cole a legenda.
          </p>
        </>
      )}
    </div>
  );
}
