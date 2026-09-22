import React, { useEffect, useMemo, useState } from "react";
import {
  deleteOutput,
  downloadOutput,
  downloadOutputsZip,
  getOutputs,
  marcarPublicado,
  outputUrl,
  refreshPublications,
} from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import PublishToTikTok from "./PublishToTikTok.jsx";
import { IconCheck, IconDownload, IconTrash } from "./Icons.jsx";

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

export default function ProducedView({ secao = "todos", folderId = null }) {
  const [itens, setItens] = useState([]);
  const [metricas, setMetricas] = useState(null);
  // O filtro vem da barra lateral, mas continua ajustavel aqui: a barra escolhe
  // por onde voce entrou, os botoes deixam refinar sem sair da tela.
  const [filtro, setFiltro] = useState(secao);

  useEffect(() => {
    setFiltro(secao);
  }, [secao]);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  // Selecao por id (Set): sobrevive a mudanca de filtro e de busca, para
  // selecionar em duas buscas diferentes e baixar tudo de uma vez.
  const [selecao, setSelecao] = useState(() => new Set());
  const [ocupado, setOcupado] = useState("");

  const buscar = async () => {
    // `folderId` vazio e um filtro legitimo ("sem pasta"), entao o teste e
    // contra null -- nao contra falsidade.
    const r = await getOutputs(
      folderId !== null ? { limit: 200, folder_id: folderId } : { limit: 200 }
    );
    setItens(r.items || []);
    setMetricas(r.metrics || null);
    setErro("");
  };

  const carregar = async () => {
    // O acervo aparece primeiro. A reconsulta ao TikTok vem depois, em segundo
    // plano: ela fala com a rede e leva segundos, e antes bloqueava a lista --
    // a tela ficava ~4s em branco antes de mostrar qualquer coisa.
    //
    // Ela precisa acontecer porque o desfecho de um envio depende de uma acao
    // fora do app: o usuario concluindo o post dentro do TikTok. Sem
    // reconsultar, o registro ficaria em "aguardando" para sempre.
    try {
      await buscar();
    } catch (e) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }

    refreshPublications()
      .then((r) => (r?.atualizadas ? buscar() : null))
      .catch(() => {});
  };

  useEffect(() => {
    carregar();
  }, [folderId]);

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

  const alternarSelecao = (id) =>
    setSelecao((atual) => {
      const proxima = new Set(atual);
      proxima.has(id) ? proxima.delete(id) : proxima.add(id);
      return proxima;
    });

  const selecionados = visiveis.filter((o) => selecao.has(o.id));
  const todosVisiveisMarcados =
    visiveis.length > 0 && visiveis.every((o) => selecao.has(o.id));

  const baixarSelecionados = async () => {
    setOcupado("baixando");
    try {
      if (selecionados.length === 1) downloadOutput(selecionados[0].file);
      else await downloadOutputsZip(selecionados.map((o) => o.id));
      setErro("");
    } catch (e) {
      setErro(e.message);
    } finally {
      setOcupado("");
    }
  };

  const marcarSelecionados = async (publicado) => {
    setOcupado("marcando");
    try {
      for (const o of selecionados) await marcarPublicado(o.id, publicado);
      await buscar();
      setSelecao(new Set());
    } catch (e) {
      setErro(e.message);
    } finally {
      setOcupado("");
    }
  };

  const apagarSelecionados = async () => {
    const n = selecionados.length;
    // Apagar remove o arquivo do disco: sem volta, entao pergunta antes.
    if (!window.confirm(
      n === 1
        ? "Apagar este vídeo? O arquivo sai do disco e não dá para desfazer."
        : `Apagar ${n} vídeos? Os arquivos saem do disco e não dá para desfazer.`
    )) return;
    setOcupado("apagando");
    try {
      for (const o of selecionados) await deleteOutput(o.id);
      await buscar();
      setSelecao(new Set());
    } catch (e) {
      setErro(e.message);
    } finally {
      setOcupado("");
    }
  };

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
          {visiveis.length > 0 && (
            <button
              className="btn btn--xs btn--ghost"
              onClick={() =>
                setSelecao((atual) => {
                  const proxima = new Set(atual);
                  visiveis.forEach((o) =>
                    todosVisiveisMarcados ? proxima.delete(o.id) : proxima.add(o.id)
                  );
                  return proxima;
                })
              }
            >
              {todosVisiveisMarcados ? "Limpar seleção" : "Selecionar todos"}
            </button>
          )}
        </div>
      </div>

      {selecionados.length > 0 && (
        <div className="card selection-bar">
          <strong>
            {selecionados.length}{" "}
            {selecionados.length === 1 ? "selecionado" : "selecionados"}
          </strong>
          <div className="selection-bar__acoes">
            <button
              className="btn btn--xs btn--primary"
              disabled={!!ocupado}
              onClick={baixarSelecionados}
            >
              <IconDownload width={14} height={14} />
              {ocupado === "baixando"
                ? "Preparando..."
                : selecionados.length === 1
                ? "Baixar"
                : "Baixar (zip)"}
            </button>
            <button
              className="btn btn--xs btn--ghost"
              disabled={!!ocupado}
              onClick={() => marcarSelecionados(true)}
            >
              <IconCheck width={14} height={14} />
              Marcar publicado
            </button>
            {selecionados.some((o) => o.published_manually) && (
              <button
                className="btn btn--xs btn--ghost"
                disabled={!!ocupado}
                onClick={() => marcarSelecionados(false)}
              >
                Desmarcar
              </button>
            )}
            <button
              className="btn btn--xs btn--danger"
              disabled={!!ocupado}
              onClick={apagarSelecionados}
            >
              <IconTrash width={14} height={14} />
              Apagar
            </button>
            <button
              className="btn btn--xs btn--ghost"
              onClick={() => setSelecao(new Set())}
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

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
            <CartaoProduzido
              key={o.id}
              output={o}
              selecionado={selecao.has(o.id)}
              onSelecionar={() => alternarSelecao(o.id)}
              onMudou={buscar}
              onErro={setErro}
            />
          ))}
        </div>
      )}
    </>
  );
}

function CartaoProduzido({ output, selecionado, onSelecionar, onMudou, onErro }) {
  const [quebrado, setQuebrado] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const url = outputUrl(output.file);

  const acao = async (fn) => {
    setOcupado(true);
    try {
      await fn();
      await onMudou();
    } catch (e) {
      onErro(e.message);
    } finally {
      setOcupado(false);
    }
  };

  const apagar = () => {
    if (!window.confirm("Apagar este vídeo? O arquivo sai do disco e não dá para desfazer."))
      return;
    acao(() => deleteOutput(output.id));
  };

  return (
    <div className={"rcard" + (selecionado ? " rcard--selecionado" : "")}>
      <label className="rcard__selecao">
        <input type="checkbox" checked={selecionado} onChange={onSelecionar} />
        <span>Selecionar</span>
      </label>
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
          <p className="rcard__legenda" title={output.caption}>
            {output.caption}
          </p>
        )}

        {(output.hashtags || []).length > 0 && (
          /* Tres hashtags e o resto como contagem: cinco chips quebravam em
             duas linhas e cada card ficava de uma altura diferente. */
          <div className="chips" style={{ marginBottom: "var(--space-2)" }}>
            {output.hashtags.slice(0, 3).map((t) => (
              <span className="chip" key={t}>#{t}</span>
            ))}
            {output.hashtags.length > 3 && (
              <span className="chip" title={output.hashtags.map((t) => "#" + t).join(" ")}>
                +{output.hashtags.length - 3}
              </span>
            )}
          </div>
        )}

        {output.published_manually && (
          <p className="rcard__marcado">
            <IconCheck width={13} height={13} /> Marcado como publicado
          </p>
        )}

        <div className="rcard__acoes">
          <button
            className="btn btn--xs btn--ghost"
            onClick={() => downloadOutput(output.file)}
            disabled={quebrado}
            title="Baixar o vídeo"
          >
            <IconDownload width={14} height={14} />
            Baixar
          </button>
          <button
            className="btn btn--xs btn--ghost"
            disabled={ocupado}
            onClick={() =>
              acao(() => marcarPublicado(output.id, !output.published_manually))
            }
          >
            <IconCheck width={14} height={14} />
            {output.published_manually ? "Desmarcar" : "Já publiquei"}
          </button>
          <button
            className="btn btn--xs btn--danger"
            disabled={ocupado}
            onClick={apagar}
            title="Apagar do catálogo e do disco"
          >
            <IconTrash width={14} height={14} />
          </button>
        </div>

        <PublishToTikTok
          outputId={output.id}
          publicacaoInicial={(output.publications || [])[0] || null}
        />
      </div>
    </div>
  );
}
