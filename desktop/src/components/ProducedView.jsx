import React, { useEffect, useMemo, useState } from "react";
import { getOutputs, outputUrl, refreshPublications } from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import PublishToTikTok from "./PublishToTikTok.jsx";

/**
 * "Produzidos" — o acervo de saídas, vindo do catálogo do backend.
 *
 * Antes desta tela, um vídeo gerado só existia em dois lugares que não
 * conversavam: o histórico no localStorage do React e os arquivos em disco. O
 * backend não tinha onde mostrar o que ele mesmo produziu, e por isso nada
 * respondia "o que já publiquei". Aqui a fonte é uma só: GET /api/outputs.
 */

const FILTROS = [
  { id: "todos", rotulo: "Todos" },
  { id: "publicados", rotulo: "Publicados" },
  { id: "aguardando", rotulo: "Esperando no TikTok" },
  { id: "pendentes", rotulo: "Não enviados" },
];

export default function ProducedView() {
  const [itens, setItens] = useState([]);
  const [metricas, setMetricas] = useState(null);
  const [filtro, setFiltro] = useState("todos");
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  const carregar = async () => {
    try {
      // O desfecho de um envio depende de uma acao fora do app -- o usuario
      // concluindo o post dentro do TikTok. Reconsultamos ao abrir a tela,
      // senao o registro ficaria em "aguardando" para sempre.
      await refreshPublications().catch(() => {});
      const r = await getOutputs({ limit: 200 });
      setItens(r.items || []);
      setMetricas(r.metrics || null);
      setErro("");
    } catch (e) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return itens.filter((o) => {
      if (filtro === "publicados" && !o.published) return false;
      if (filtro === "aguardando" && !o.awaiting) return false;
      if (filtro === "pendentes" && (o.published || o.awaiting)) return false;
      if (!termo) return true;
      return [o.phrase, o.caption, o.theme, o.source_name, ...(o.hashtags || [])]
        .join(" ")
        .toLowerCase()
        .includes(termo);
    });
  }, [itens, filtro, busca]);

  if (carregando) return <p className="muted">Carregando o acervo...</p>;

  return (
    <>
      {metricas && (
        <div className="metrics-row">
          <div className="metric-card metric-card--accent">
            <div className="metric-card__val">{metricas.total_produced}</div>
            <div className="metric-card__lbl">Produzidos</div>
            {metricas.produced_7d > 0 && (
              <div className="metric-card__sub">
                {metricas.produced_7d} nos últimos 7 dias
              </div>
            )}
          </div>
          <div className="metric-card metric-card--accent">
            <div className="metric-card__val">{metricas.total_published}</div>
            <div className="metric-card__lbl">Publicados</div>
            {metricas.published_7d > 0 && (
              <div className="metric-card__sub">
                {metricas.published_7d} nos últimos 7 dias
              </div>
            )}
          </div>
          {metricas.awaiting > 0 && (
            <div className="metric-card">
              <div className="metric-card__val">{metricas.awaiting}</div>
              <div className="metric-card__lbl">Esperando no TikTok</div>
            </div>
          )}
          <div className="metric-card">
            <div className="metric-card__val">{metricas.not_published}</div>
            <div className="metric-card__lbl">Sem publicar</div>
          </div>
          {metricas.pending > 0 && (
            <div className="metric-card">
              <div className="metric-card__val">{metricas.pending}</div>
              <div className="metric-card__lbl">Na fila</div>
            </div>
          )}
          {metricas.failed > 0 && (
            <div className="metric-card">
              <div className="metric-card__val">{metricas.failed}</div>
              <div className="metric-card__lbl">Com erro</div>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {FILTROS.map((f) => (
            <button
              key={f.id}
              className={"btn btn--xs " + (filtro === f.id ? "btn--primary" : "btn--ghost")}
              onClick={() => setFiltro(f.id)}
            >
              {f.rotulo}
            </button>
          ))}
          <input
            className="input"
            placeholder="Buscar por frase, legenda, tema ou hashtag"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            style={{ flex: 1, minWidth: 220 }}
          />
        </div>
      </div>

      {erro && <p style={{ color: "#f87171" }}>{erro}</p>}

      {visiveis.length === 0 ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>
            {itens.length === 0
              ? "Nada produzido ainda. Gere um vídeo para ele aparecer aqui."
              : "Nenhum vídeo corresponde a esse filtro."}
          </p>
        </div>
      ) : (
        <div className="results">
          {visiveis.map((o) => (
            <CartaoProduzido key={o.id} output={o} />
          ))}
        </div>
      )}
    </>
  );
}

function CartaoProduzido({ output }) {
  const [quebrado, setQuebrado] = useState(false);
  const url = outputUrl(output.file);

  return (
    <div className="rcard">
      {quebrado ? (
        <div className="rcard__unavail">
          Arquivo removido do disco. O registro continua no catálogo.
        </div>
      ) : (
        <div className="rcard__media">
          <LazyVideo src={url} controls onError={() => setQuebrado(true)} />
        </div>
      )}
      <div className="rcard__body">
        <p className="rcard__phrase">{output.phrase || "(sem frase)"}</p>

        {output.caption && (
          <p className="muted" style={{ fontSize: "var(--text-sm)", margin: "0 0 6px" }}>
            {output.caption}
          </p>
        )}

        {(output.hashtags || []).length > 0 && (
          <div className="chips" style={{ marginBottom: 8 }}>
            {output.hashtags.map((t) => (
              <span className="chip" key={t}>#{t}</span>
            ))}
          </div>
        )}

        <PublishToTikTok
          outputId={output.id}
          publicacaoInicial={(output.publications || [])[0] || null}
        />
      </div>
    </div>
  );
}
