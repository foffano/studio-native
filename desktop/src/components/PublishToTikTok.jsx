import React, { useEffect, useRef, useState } from "react";
import CaptionQR from "./CaptionQR.jsx";
import {
  getOutput,
  getPublication,
  getTikTokAccount,
  publishOutput,
  refreshPublication,
} from "../api.js";

const POLL_MS = 2000;

// O envio acontece no backend, numa fila com um worker só. A tela acompanha
// perguntando pelo registro da publicação — mesmo padrão do login.
const ROTULOS = {
  fila: "Na fila...",
  enviando: "Enviando para o TikTok...",
  processando: "TikTok processando...",
};

/** Legenda + hashtags como um texto só, do jeito que vai no post. */
function textoDoPost(output) {
  const legenda = (output?.caption || "").trim();
  const tags = (output?.hashtags || []).map((t) => `#${t}`).join(" ");
  return [legenda, tags].filter(Boolean).join("\n\n");
}

export default function PublishToTikTok({ outputId, publicacaoInicial = null }) {
  const [conta, setConta] = useState(null);
  // Sem isto, um vídeo enviado numa sessão anterior voltaria a mostrar o botão
  // "Enviar", como se nunca tivesse saído daqui.
  const [pub, setPub] = useState(publicacaoInicial);
  const [erro, setErro] = useState("");
  const [legenda, setLegenda] = useState("");
  const [copiado, setCopiado] = useState(false);
  const [conferindo, setConferindo] = useState(false);
  const poll = useRef(null);

  useEffect(() => {
    getTikTokAccount()
      .then((r) => setConta(r.account || null))
      .catch(() => {});
    if (publicacaoInicial && publicacaoInicial.state !== "erro") carregarLegenda();
    return () => poll.current && clearInterval(poll.current);
  }, []);

  const carregarLegenda = () =>
    getOutput(outputId)
      .then((o) => setLegenda(textoDoPost(o)))
      .catch(() => {});

  function acompanhar(pubId) {
    if (poll.current) clearInterval(poll.current);
    poll.current = setInterval(async () => {
      try {
        const p = await getPublication(pubId);
        setPub(p);
        if (["aguardando", "publicado", "erro"].includes(p.state)) {
          clearInterval(poll.current);
          poll.current = null;
          if (p.state !== "erro") carregarLegenda();
        }
      } catch (e) {
        clearInterval(poll.current);
        poll.current = null;
        setErro(e.message);
      }
    }, POLL_MS);
  }

  async function enviar() {
    setErro("");
    try {
      const p = await publishOutput(outputId);
      setPub(p);
      acompanhar(p.id);
    } catch (e) {
      setErro(e.message);
    }
  }

  /** Pergunta ao TikTok se você já concluiu o post do lado de lá. */
  async function conferir() {
    if (!pub) return;
    setConferindo(true);
    setErro("");
    try {
      setPub(await refreshPublication(pub.id));
    } catch (e) {
      setErro(e.message);
    } finally {
      setConferindo(false);
    }
  }

  async function copiar() {
    try {
      await navigator.clipboard.writeText(legenda);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch (_) {
      setErro("Não foi possível copiar. Selecione o texto e copie à mão.");
    }
  }

  if (!conta) {
    return (
      <p className="muted" style={{ fontSize: "var(--text-sm)", marginTop: 8 }}>
        Conecte a conta do TikTok em Ajustes para enviar seus vídeos.
      </p>
    );
  }

  const estado = pub?.state;
  const andamento = pub?.progresso;

  // A legenda é a mesma nos dois estados finais, então mora numa função só.
  // Numa grade de dezenas de cards, a legenda inteira mais o QR faziam cada
  // item passar de mil pixels. O conteudo continua aqui -- so nao aberto por
  // padrao, porque ele so importa no momento de terminar o post no celular.
  const blocoLegenda = legenda && (
    <details className="revelar" style={{ marginTop: "var(--space-2)" }}>
      <summary className="revelar__titulo">Legenda para colar</summary>
      <div className="revelar__corpo">
      {/* A legenda não vai junto, e não é limitação nossa: o endpoint de caixa
          de entrada aceita só `source_info`. Campo de título existe apenas no
          Direct Post, que publica direto no feed. */}
      <p className="muted" style={{ fontSize: "var(--text-sm)", margin: "0 0 6px" }}>
        O TikTok não aceita texto neste caminho. Cole ao terminar o post:
      </p>
      <pre
        style={{
          whiteSpace: "pre-wrap",
          background: "#0f1826",
          border: "1px solid #1e2a3d",
          borderRadius: 8,
          padding: "8px 10px",
          fontSize: "var(--text-sm)",
          margin: "0 0 6px",
          fontFamily: "inherit",
        }}
      >
        {legenda}
      </pre>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn--ghost btn--xs" onClick={copiar}>
          {copiado ? "Copiado" : "Copiar legenda"}
        </button>
        <CaptionQR texto={legenda} outputId={outputId} />
      </div>
      </div>
    </details>
  );

  // Entregue na caixa de entrada, esperando você terminar dentro do TikTok.
  if (estado === "aguardando") {
    return (
      <div style={{ marginTop: 8 }}>
        <p style={{ color: "#facc15", margin: "0 0 4px" }}>
          Esperando você no TikTok de @{conta.nickname}
        </p>
        <p className="muted" style={{ fontSize: "var(--text-sm)", margin: "0 0 8px" }}>
          Toque na notificação na <strong>Caixa de entrada</strong> do TikTok
          para publicar. Não aparece em Rascunhos.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            className="btn btn--ghost btn--xs"
            disabled={conferindo}
            onClick={conferir}
          >
            {conferindo ? "Conferindo..." : "Já publiquei, conferir"}
          </button>
          {/* Reenviar existe porque a notificação pode não chegar: já
              aconteceu de o TikTok confirmar o envio e nada aparecer na caixa
              de entrada. O aviso de duplicata é honesto — se as duas chegarem,
              o usuário vai ver duas. */}
          <button
            className="btn btn--ghost btn--xs"
            onClick={() => {
              if (
                window.confirm(
                  "Enviar este vídeo de novo? Se a notificação anterior chegar, " +
                    "você verá o mesmo vídeo duas vezes na Caixa de entrada."
                )
              ) {
                enviar();
              }
            }}
          >
            Enviar de novo
          </button>
        </div>
        {erro && (
          <p style={{ color: "#f87171", fontSize: "var(--text-sm)", marginTop: 6 }}>{erro}</p>
        )}
        {blocoLegenda}
      </div>
    );
  }

  // Publicado de verdade: o TikTok só devolve PUBLISH_COMPLETE depois que você
  // concluiu o post do lado de lá.
  if (estado === "publicado") {
    return (
      <div style={{ marginTop: 8 }}>
        <p style={{ color: "#4ade80", margin: "0 0 4px" }}>
          Publicado em @{conta.nickname}
        </p>
        <button className="btn btn--ghost btn--xs" onClick={enviar}>
          Enviar de novo
        </button>
      </div>
    );
  }

  if (estado && estado !== "erro") {
    return (
      <p className="muted" style={{ marginTop: 8 }}>
        {ROTULOS[estado] || "Enviando..."}
        {andamento?.total > 1 &&
          ` (${andamento.enviados}/${andamento.total} partes)`}
      </p>
    );
  }

  return (
    <>
      <button className="btn btn--ghost btn--block" onClick={enviar}>
        {estado === "erro" ? "Tentar de novo" : `Enviar para o TikTok de @${conta.nickname}`}
      </button>
      {(erro || pub?.error) && (
        <p style={{ color: "#f87171", fontSize: "var(--text-sm)", marginTop: 6 }}>
          {erro || pub.error}
        </p>
      )}
    </>
  );
}
