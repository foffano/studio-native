import React, { useEffect, useRef, useState } from "react";
import LazyVideo from "./LazyVideo.jsx";
import PublishToTikTok from "./PublishToTikTok.jsx";
import { IconStar, IconTrash, IconPlus } from "./Icons.jsx";
import { getOutputs, libraryThumbnailUrl, libraryVideoUrl, outputUrl } from "../api.js";

function fmtDur(sec) {
  if (!sec) return "";
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}:${String(s % 60).padStart(2, "0")}` : `${s}s`;
}

/**
 * Tudo sobre um vídeo-fonte: o que ele é, o que já saiu dele, e o que dá para
 * fazer com ele.
 *
 * Abre ao lado da Biblioteca, e não numa aba separada, porque a pergunta que
 * ele responde é comparativa: "o que já fiz com este vídeo?". Trocar de tela
 * para responder isso obrigaria a lembrar de qual fonte se estava falando.
 *
 * Desde que o card virou só o quadro do vídeo, este painel é o **único** lugar
 * com os controles. Isso não é só arrumação: o seletor de pasta aqui dentro é
 * a alternativa que a WCAG 2.2 exige para o arrastar — sem ele, quem não usa
 * mouse não teria como organizar nada.
 */
export default function SourcePanel({
  item,
  pastas = [],
  naLixeira = false,
  tagDraft = "",
  onTagDraft,
  onAddTag,
  onRemoveTag,
  onFavoritar,
  onMoverPara,
  onRestaurar,
  onExcluir,
  onFechar,
  onProduzir,
}) {
  const [saidas, setSaidas] = useState(null);
  const [erro, setErro] = useState("");
  const caixa = useRef(null);

  // No celular este painel cobre a tela inteira, e o botao de fechar e a unica
  // saida. Esc fecha tambem -- no desktop porque e o esperado de um painel, no
  // celular porque um teclado externo continua sendo teclado.
  useEffect(() => {
    if (!item) return undefined;
    const aoTeclar = (e) => {
      if (e.key === "Escape") onFechar && onFechar();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [item?.id, onFechar]);

  // Leva o foco para o painel ao abrir. Sem isso, quem navega por teclado ou
  // leitor de tela continuaria na grade: o painel apareceria por cima sem que
  // nada indicasse que a tela mudou. Foca a caixa, e nao um botao dentro dela
  // -- assim a leitura comeca pelo titulo em vez de por um controle solto.
  useEffect(() => {
    if (item && caixa.current) caixa.current.focus({ preventScroll: true });
  }, [item?.id]);

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

  const detalhes = [
    fmtDur(item.duration_sec),
    item.size_bytes ? `${(item.size_bytes / (1024 * 1024)).toFixed(1)} MB` : "",
    item.created_at ? new Date(item.created_at).toLocaleDateString("pt-BR") : "",
  ].filter(Boolean);

  return (
    <aside
      className="painel"
      aria-label={`Detalhes de ${item.name}`}
      ref={caixa}
      tabIndex={-1}
    >
      <div className="painel__topo">
        <div className="painel__id">
          <div className="painel__thumb">
            {item.file && (
              <LazyVideo
                src={libraryVideoUrl(item.file)}
                poster={libraryThumbnailUrl(item.id)}
              />
            )}
          </div>
          <div className="painel__titulo">
            <h2 title={item.name}>{item.name}</h2>
            <p className="muted">{detalhes.join(" · ")}</p>
          </div>
        </div>
        <button className="icon-btn" onClick={onFechar} title="Fechar" aria-label="Fechar">
          ×
        </button>
      </div>

      {naLixeira ? (
        <div className="painel__acoes">
          <button className="btn btn--primary btn--block" onClick={onRestaurar}>
            Restaurar
          </button>
          <button className="btn btn--danger btn--block" onClick={onExcluir}>
            Apagar em definitivo
          </button>
        </div>
      ) : (
        <>
          <button
            className="btn btn--primary btn--block"
            disabled={item.status !== "ready"}
            onClick={onProduzir}
          >
            Produzir vídeo a partir deste
          </button>

          <div className="painel__barra">
            <button
              className={"icon-btn" + (item.favorito ? " icon-btn--on" : "")}
              onClick={onFavoritar}
              aria-pressed={!!item.favorito}
              title={item.favorito ? "Tirar dos favoritos" : "Marcar como favorito"}
            >
              <IconStar width={16} height={16} fill={item.favorito ? "currentColor" : "none"} />
            </button>

            {/* A alternativa de um clique ao arrastar. Some junto com o
                arrastar quando o vídeo está na lixeira. */}
            <label className="painel__pasta">
              <span className="sr-only">Pasta</span>
              <select
                className="input input--sm"
                value={item.folder_id || ""}
                onChange={(e) => onMoverPara(e.target.value)}
              >
                <option value="">Sem pasta</option>
                {pastas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>

            <button className="icon-btn icon-btn--perigo" onClick={onExcluir} title="Mover para a lixeira">
              <IconTrash width={16} height={16} />
            </button>
          </div>

          <div className="painel__tags">
            <div className="chips">
              {(item.tags || []).map((t) => (
                <button
                  className="chip chip--x"
                  key={t}
                  onClick={() => onRemoveTag(t)}
                  title={`Remover a tag ${t}`}
                >
                  {t} <span aria-hidden="true">×</span>
                </button>
              ))}
            </div>
            <form
              className="painel__tagform"
              onSubmit={(e) => {
                e.preventDefault();
                onAddTag();
              }}
            >
              <input
                className="input input--sm"
                placeholder="Nova tag"
                value={tagDraft}
                onChange={(e) => onTagDraft(e.target.value)}
              />
              <button className="icon-btn" title="Adicionar tag" disabled={!tagDraft.trim()}>
                <IconPlus width={14} height={14} />
              </button>
            </form>
          </div>
        </>
      )}

      {erro && <p className="painel__erro">{erro}</p>}

      <h3 className="painel__secao">
        {saidas === null
          ? "Produzidos"
          : saidas.length === 0
          ? "Produzidos"
          : `Produzidos · ${saidas.length}`}
      </h3>

      <div className="painel__lista">
        {saidas === null && <p className="muted">Carregando...</p>}

        {saidas !== null && saidas.length === 0 && (
          <p className="muted painel__vazio">
            Nada produzido a partir deste vídeo ainda.
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
