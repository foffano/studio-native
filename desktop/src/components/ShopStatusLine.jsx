import React from "react";

/** Uma linha com o estado do vídeo no TikTok Shop, quando ele passou pela fila. */
const TEXTO = {
  fila: "na fila",
  enviando: "publicando agora...",
  publicado: "publicado",
  erro: "erro",
  cancelado: "cancelado",
};

export default function ShopStatusLine({ publications }) {
  const pub = (publications || []).find((p) => p.platform === "tiktok_shop");
  if (!pub) return null;
  return (
    <p className={"shop-linha shop-linha--" + pub.state} title={pub.error || ""}>
      TikTok Shop{pub.target ? ` @${pub.target}` : ""}: {TEXTO[pub.state] || pub.state}
    </p>
  );
}

/** A publicação pela API (caixa de entrada), sem as do TikTok Shop. */
export const publicacaoDaApi = (publications) =>
  (publications || []).find((p) => p.platform !== "tiktok_shop") || null;
