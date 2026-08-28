import React, { useEffect, useRef, useState } from "react";
import {
  getOutput,
  getPublication,
  getTikTokAccount,
  publishOutput,
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

export default function PublishToTikTok({ outputId }) {
  const [conta, setConta] = useState(null);
  const [pub, setPub] = useState(null);
  const [erro, setErro] = useState("");
  const [legenda, setLegenda] = useState("");
  const [copiado, setCopiado] = useState(false);
  const poll = useRef(null);

  useEffect(() => {
    getTikTokAccount()
      .then((r) => setConta(r.account || null))
      .catch(() => {});
    return () => poll.current && clearInterval(poll.current);
  }, []);

  function acompanhar(pubId) {
    if (poll.current) clearInterval(poll.current);
    poll.current = setInterval(async () => {
      try {
        const p = await getPublication(pubId);
        setPub(p);
        if (p.state === "publicado" || p.state === "erro") {
          clearInterval(poll.current);
          poll.current = null;
          if (p.state === "publicado") {
            // Buscamos a legenda agora, e não no clique, para pegar o que o
            // usuário salvou no editor — ele costuma ajustar antes de enviar.
            getOutput(outputId)
              .then((o) => setLegenda(textoDoPost(o)))
              .catch(() => {});
          }
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

  if (!conta) {
    return (
      <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
        Conecte a conta do TikTok em Ajustes para enviar seus vídeos.
      </p>
    );
  }

  const estado = pub?.state;
  const andamento = pub?.progresso;

  async function copiar() {
    try {
      await navigator.clipboard.writeText(legenda);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch (_) {
      setErro("Não foi possível copiar. Selecione o texto e copie à mão.");
    }
  }

  if (estado === "publicado") {
    return (
      <div style={{ marginTop: 8 }}>
        <p style={{ color: "#4ade80", margin: "0 0 4px" }}>
          Enviado para @{conta.nickname}
        </p>
        {/* "Rascunhos" seria a palavra errada aqui, e mandaria o usuário para o
            lugar errado: os rascunhos do perfil são locais do aparelho e um
            vídeo vindo da API nunca aparece lá. Ele chega como notificação na
            Caixa de entrada, e é por ela que o editor abre. Dizer isso também é
            exigência do TikTok para este fluxo. */}
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Abra o TikTok no celular, vá na aba <strong>Caixa de entrada</strong> e
          toque na notificação do vídeo para revisar, adicionar o produto e
          publicar. Ele não aparece em Rascunhos — esses são só do aparelho.
        </p>

        {legenda && (
          <div style={{ marginTop: 10 }}>
            {/* A legenda não vai junto, e não é limitação nossa: o endpoint de
                caixa de entrada aceita só `source_info`. Campo de título existe
                apenas no Direct Post, que publica direto no feed e exige
                video.publish. Então entregamos o texto pronto para colar. */}
            <p className="muted" style={{ fontSize: 13, margin: "0 0 6px" }}>
              A legenda não pode ser enviada junto — o TikTok não aceita texto
              neste caminho. Cole ao terminar o post:
            </p>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                background: "#0f1826",
                border: "1px solid #1e2a3d",
                borderRadius: 8,
                padding: "8px 10px",
                fontSize: 13,
                margin: "0 0 6px",
                fontFamily: "inherit",
              }}
            >
              {legenda}
            </pre>
            <button className="btn btn--ghost btn--xs" onClick={copiar}>
              {copiado ? "Copiado" : "Copiar legenda"}
            </button>
          </div>
        )}
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
        Enviar para o TikTok de @{conta.nickname}
      </button>
      {(erro || pub?.error) && (
        <p style={{ color: "#f87171", fontSize: 13, marginTop: 6 }}>
          {erro || pub.error}
        </p>
      )}
    </>
  );
}
