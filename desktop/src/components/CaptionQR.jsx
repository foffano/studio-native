import React, { useEffect, useState } from "react";
import QRCode from "qrcode";

/**
 * A legenda como QR code, para atravessar do PC até o iPhone.
 *
 * Existe porque o TikTok não aceita legenda no envio para a caixa de entrada
 * (só `source_info`), e quem termina o post está no celular — onde a área de
 * transferência do Windows não chega. Apontar a câmera resolve sem servidor,
 * sem conta de nuvem e sem o texto sair desta máquina.
 *
 * O QR é gerado como data URL no próprio renderer. Nenhuma requisição sai.
 */
export default function CaptionQR({ texto }) {
  const [img, setImg] = useState("");
  const [aberto, setAberto] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (!aberto || !texto) return;
    let vivo = true;
    QRCode.toDataURL(texto, {
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
  }, [aberto, texto]);

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
            Aponte a câmera do iPhone. O texto aparece na tela — toque e segure
            para copiar, depois cole no TikTok.
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
