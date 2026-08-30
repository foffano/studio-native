import React, { useEffect, useState } from "react";
import LazyVideo from "./LazyVideo.jsx";
import PublishToTikTok from "./PublishToTikTok.jsx";
import { getOutputs, libraryVideoUrl, outputUrl } from "../api.js";

/**
 * O que saiu de um vídeo-fonte.
 *
 * Abre ao lado da Biblioteca, e não numa aba separada, porque a pergunta que
 * ele responde é comparativa: "o que já fiz com este vídeo?". Trocar de tela
 * para responder isso obrigaria a lembrar de qual fonte se estava falando.
 */
export default function SourcePanel({ item, onFechar, onProduzir }) {
  const [saidas, setSaidas] = useState(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (!item) return;
    let vivo = true;
    setSaidas(null);
    setErro("");
    getOutputs({ library_id: item.id, limit: 200 })
      .then((r) => vivo && setSaidas(r.items || []))
      .catch((e) => vivo && setErro(e.message));
    return () => {
      vivo = false;
    };
  }, [item?.id]);

  if (!item) return null;

  return (
    <aside className="painel" aria-label={`Produzidos a partir de ${item.name}`}>
      <div className="painel__topo">
        <div className="painel__id">
          <div className="painel__thumb">
            {item.file && <LazyVideo src={libraryVideoUrl(item.file)} />}
          </div>
          <div className="painel__titulo">
            <h2 title={item.name}>{item.name}</h2>
            <p className="muted">
              {saidas === null
                ? "carregando..."
                : saidas.length === 0
                ? "nada produzido ainda"
                : `${saidas.length} ${saidas.length === 1 ? "vídeo produzido" : "vídeos produzidos"}`}
            </p>
          </div>
        </div>
        <button className="icon-btn" onClick={onFechar} title="Fechar" aria-label="Fechar">
          ×
        </button>
      </div>

      <button
        className="btn btn--primary btn--block"
        disabled={item.status !== "ready"}
        onClick={onProduzir}
      >
        Produzir mais um vídeo
      </button>

      {erro && <p className="painel__erro">{erro}</p>}

      <div className="painel__lista">
        {saidas === null && <p className="muted">Carregando...</p>}

        {saidas !== null && saidas.length === 0 && (
          <p className="muted painel__vazio">
            Nada produzido a partir deste vídeo ainda. O botão acima começa.
          </p>
        )}

        {(saidas || []).map((o) => (
          <article className="saida" key={o.id}>
            <div className="saida__media">
              <LazyVideo src={outputUrl(o.file)} controls />
            </div>
            <div className="saida__corpo">
              <p className="saida__frase">{o.phrase || "(sem frase)"}</p>
              {o.caption && (
                <p className="saida__legenda" title={o.caption}>
                  {o.caption}
                </p>
              )}
              {(o.hashtags || []).length > 0 && (
                <div className="chips">
                  {o.hashtags.map((t) => (
                    <span className="chip" key={t}>#{t}</span>
                  ))}
                </div>
              )}
              <p className="saida__meta">
                {o.created_at ? new Date(o.created_at).toLocaleDateString("pt-BR") : ""}
                {o.duration ? ` · ${Math.round(o.duration)}s` : ""}
                {o.audio_mode ? " · com narração" : ""}
              </p>
              <PublishToTikTok
                outputId={o.id}
                publicacaoInicial={(o.publications || [])[0] || null}
              />
            </div>
          </article>
        ))}
      </div>
    </aside>
  );
}
