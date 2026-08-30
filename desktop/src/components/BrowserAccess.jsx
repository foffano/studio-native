import React, { useEffect, useState } from "react";
import QRCode from "qrcode";
import { BACKEND, isElectron } from "../api.js";

/**
 * Mostra em que endereço o app está sendo servido, para abrir no navegador ou
 * no celular.
 *
 * Existe porque o endereço não é adivinhável: o Electron pede uma porta ao
 * sistema, e no app instalado o usuário não tem como descobrir qual foi sem
 * abrir um `netstat`. O modo navegador ficava inacessível para quem usa o app
 * instalado — que é a maioria.
 *
 * O QR é gerado localmente, como data URL. Nada sai da máquina.
 */
export default function BrowserAccess() {
  const [qr, setQr] = useState("");
  const [copiado, setCopiado] = useState(false);

  // No Electron a URL vem da ponte do preload. Servido pelo Flask, o endereço
  // é a própria origem da página.
  const url =
    BACKEND ||
    (typeof window !== "undefined" && window.location.protocol.startsWith("http")
      ? window.location.origin
      : "");

  useEffect(() => {
    if (!url) return;
    let vivo = true;
    QRCode.toDataURL(url, {
      errorCorrectionLevel: "L",
      margin: 2,
      width: 190,
      color: { dark: "#0e1726", light: "#ffffff" },
    })
      .then((d) => vivo && setQr(d))
      .catch(() => {});
    return () => {
      vivo = false;
    };
  }, [url]);

  if (!url) return null;

  async function copiar() {
    try {
      await navigator.clipboard.writeText(url);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch (_) {
      /* sem área de transferência: o endereço está visível para copiar à mão */
    }
  }

  return (
    <div className="card">
      <h3 className="card__title">Abrir no navegador</h3>
      <p className="card__hint">
        O mesmo app roda no navegador, neste endereço. Enquanto o Studio Native
        estiver aberto, ele responde.
      </p>

      <div
        style={{
          display: "flex",
          gap: 18,
          alignItems: "flex-start",
          flexWrap: "wrap",
          marginTop: 12,
        }}
      >
        <div style={{ flex: 1, minWidth: 240 }}>
          <code
            style={{
              display: "block",
              background: "#0f1826",
              border: "1px solid #1e2a3d",
              borderRadius: 8,
              padding: "10px 12px",
              fontSize: "var(--text-md)",
              wordBreak: "break-all",
              marginBottom: 8,
            }}
          >
            {url}
          </code>
          <button className="btn btn--ghost btn--xs" onClick={copiar}>
            {copiado ? "Copiado" : "Copiar endereço"}
          </button>

          <p className="card__hint" style={{ marginTop: 14, marginBottom: 0 }}>
            Para abrir <strong>pelo celular</strong>, este endereço não basta —
            ele só existe dentro deste computador. Suba um túnel e use a URL que
            ele devolver:
          </p>
          <code
            style={{
              display: "block",
              background: "#0f1826",
              border: "1px solid #1e2a3d",
              borderRadius: 8,
              padding: "8px 10px",
              fontSize: "var(--text-sm)",
              marginTop: 6,
              wordBreak: "break-all",
            }}
          >
            cloudflared tunnel --url {url}
          </code>
          {/* O mesmo alerta do README e da doc: exposto por tunel, sem
              autenticacao, quem tiver a URL tem o app inteiro. */}
          <p className="card__hint" style={{ marginTop: 8, marginBottom: 0 }}>
            ⚠️ O app não pede senha. Atrás de um túnel, quem tiver a URL pode
            gerar vídeos com seus créditos e publicar na sua conta — proteja com
            Cloudflare Access, ou derrube o túnel ao terminar.
          </p>
        </div>

        {qr && (
          <div style={{ textAlign: "center" }}>
            {/* Fundo branco fixo: no tema escuro a câmera não lê o código. */}
            <img
              src={qr}
              alt="QR code com o endereço do app"
              width={190}
              height={190}
              style={{ background: "#fff", borderRadius: 8, display: "block" }}
            />
            <p className="muted" style={{ fontSize: "var(--text-xs)", margin: "6px 0 0" }}>
              {isElectron ? "para outro navegador deste PC" : "aponte a câmera"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
