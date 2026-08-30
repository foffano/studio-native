import React, { useEffect, useState } from "react";
import QRCode from "qrcode";
import { BACKEND, isElectron } from "../api.js";

/**
 * Onde o app está sendo servido.
 *
 * Existe porque o endereço não é adivinhável: o Electron pede uma porta ao
 * sistema, e no app instalado não havia como descobrir qual sem um `netstat`.
 *
 * A versão anterior deste cartão empilhava endereço, botão, comando de túnel,
 * aviso de segurança e QR num bloco só — cada peça útil, todas competindo. Aqui
 * fica o que se usa sempre (endereço e QR); o que se faz uma vez a cada muitos
 * meses desce para uma seção que abre quando pedida.
 */
export default function BrowserAccess() {
  const [qr, setQr] = useState("");
  const [copiado, setCopiado] = useState(false);

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
      width: 150,
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
      /* o endereço está visível para copiar à mão */
    }
  }

  return (
    <div className="card">
      <h3 className="card__title">Endereço deste app</h3>

      <div className="acesso">
        <div className="acesso__principal">
          <code className="acesso__url">{url}</code>
          <button className="btn btn--ghost btn--xs" onClick={copiar}>
            {copiado ? "Copiado" : "Copiar endereço"}
          </button>
          <p className="card__hint acesso__nota">
            Vale enquanto o Studio Native estiver rodando. Só existe dentro deste
            computador.
          </p>
        </div>

        {qr && (
          <img
            className="acesso__qr"
            src={qr}
            alt="QR code com o endereço do app"
            width={150}
            height={150}
          />
        )}
      </div>

      {/* Configurar um túnel é coisa de uma vez; não precisa estar aberto todo
          dia ocupando a tela. O aviso de segurança mora aqui dentro de
          propósito: ele importa exatamente no momento em que alguém vem ler
          como expor o app. */}
      <details className="revelar">
        <summary className="revelar__titulo">
          Usar de fora deste computador
        </summary>
        <div className="revelar__corpo">
          <p className="card__hint">
            O endereço acima não alcança o celular — ele só existe aqui. Suba um
            túnel e use a URL que ele devolver:
          </p>
          <code className="acesso__url">cloudflared tunnel --url {url}</code>
          <p className="card__hint" style={{ marginTop: "var(--space-3)" }}>
            <strong>Antes de deixar um túnel de pé:</strong> o app pede senha,
            mas o endereço público aparece nos registros de Certificate
            Transparency minutos depois de criado, e bots os varrem. Proteger o
            hostname com Cloudflare Access barra o tráfego antes de ele chegar
            nesta máquina.
          </p>
        </div>
      </details>

      {isElectron && (
        <p className="card__hint" style={{ marginTop: "var(--space-3)" }}>
          O QR serve para abrir em outro navegador deste mesmo PC.
        </p>
      )}
    </div>
  );
}
