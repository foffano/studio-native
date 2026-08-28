import React, { useEffect, useState } from "react";
import QRCode from "qrcode";

/**
 * QR code para levar a legenda ao celular.
 *
 * Existe porque o TikTok não aceita legenda no envio para a caixa de entrada
 * (só `source_info`), e quem termina o post está no celular — onde a área de
 * transferência do Windows não chega.
 *
 * **O QR aponta para uma página, não carrega o texto.** Um QR com o texto dentro
 * faz a câmera exibir a legenda como texto solto: para copiar, é preciso segurar
 * o dedo e ajustar a seleção, justamente com o TikTok aberto na outra mão. Com a
 * página, há um botão.
 *
 * Isso exige que o celular alcance o app — servido pelo Flask, direto na rede
 * local ou por um túnel. Fora do navegador (Electron carregado de file://) não
 * há origem que o telefone possa abrir, e aí o QR volta a carregar o texto: pior
 * de usar, mas melhor que nada.
 */
export default function CaptionQR({ texto, outputId }) {
  const [img, setImg] = useState("");
  const [aberto, setAberto] = useState(false);
  const [erro, setErro] = useState("");

  // Origem que o celular consegue abrir. Em file:// (Electron) não existe.
  const origem =
    typeof window !== "undefined" &&
    window.location &&
    window.location.protocol.startsWith("http")
      ? window.location.origin
      : "";
  const alvo =
    origem && outputId ? `${origem}/?legenda=${encodeURIComponent(outputId)}` : texto;

  useEffect(() => {
    if (!aberto || !alvo) return;
    let vivo = true;
    QRCode.toDataURL(alvo, {
      errorCorrectionLevel: "L", // menos redundância = menos módulos = mais legível
      margin: 2,
      width: 260,
      color: { dark: "#0e1726", light: "#ffffff" },
    })
      .then((url) => vivo && setImg(url))
      .catch((e) => vivo && setErro(e.message));
    return () => {
      vivo = false;
    };
  }, [aberto, alvo]);

  if (!texto) return null;

  if (!aberto) {
    return (
      <button className="btn btn--ghost btn--xs" onClick={() => setAberto(true)}>
        Ler no celular
      </button>
    );
  }

  return (
    <div style={{ marginTop: 8 }}>
      {erro ? (
        <p style={{ color: "#f87171", fontSize: 13 }}>
          Não foi possível gerar o QR: {erro}
        </p>
      ) : img ? (
        <>
          {/* Fundo branco fixo: a câmera precisa de contraste, e no tema escuro
              um QR sobre fundo escuro simplesmente não é lido. */}
          <img
            src={img}
            alt="QR code com a legenda"
            width={260}
            height={260}
            style={{ background: "#fff", borderRadius: 8, display: "block" }}
          />
          <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
            {origem && outputId
              ? "Aponte a câmera do celular. Abre uma página com botão de copiar."
              : "Aponte a câmera do celular. O texto aparece na tela — toque e segure para copiar."}
          </p>
        </>
      ) : (
        <p className="muted" style={{ fontSize: 13 }}>Gerando...</p>
      )}
      <button
        className="btn btn--ghost btn--xs"
        style={{ marginTop: 6 }}
        onClick={() => setAberto(false)}
      >
        Fechar
      </button>
    </div>
  );
}
