import React, { useEffect, useMemo, useState } from "react";
import {
  addShop,
  answerShop,
  cancelShopItem,
  closeShopBrowser,
  getOutputs,
  getShopQueue,
  openShopBrowser,
  outputUrl,
  pauseShop,
  removeShop,
  retryShopItem,
  syncShopProducts,
} from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import { carregarProdutos, Miniatura } from "./ProductPicker.jsx";
import { AvatarConta } from "./AccountPicker.jsx";
import ShopPublishDialog from "./ShopPublishDialog.jsx";

/**
 * TikTok Shop: publicar vídeos com o carrinho laranja pela Central do
 * Vendedor, sem ninguém clicando.
 *
 * Três blocos, na ordem em que se usa: a conta (entrar uma vez, a sessão fica
 * salva no servidor), a fila (o que está saindo agora e o que vem depois) e a
 * escolha dos vídeos.
 */

const ROTULO = {
  fila: "Na fila",
  enviando: "Publicando",
  publicado: "Publicado",
  erro: "Erro",
  cancelado: "Cancelado",
};

function contagem(alvo) {
  const s = Math.max(0, Math.round(alvo - Date.now() / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
}

export default function ShopView({ onAbrirNavegador }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState("");
  const [escolhendo, setEscolhendo] = useState(false);
  const [, setTique] = useState(0);

  const carregar = async () => {
    try {
      setDados(await getShopQueue());
      setErro("");
    } catch (e) {
      setErro(e.message);
    }
  };

  useEffect(() => {
    carregar();
    const t = setInterval(carregar, 3000);
    // Só para a contagem regressiva andar entre uma consulta e outra.
    const r = setInterval(() => setTique((n) => n + 1), 1000);
    return () => {
      clearInterval(t);
      clearInterval(r);
    };
  }, []);

  const acao = async (fn) => {
    try {
      await fn();
      await carregar();
    } catch (e) {
      setErro(e.message);
    }
  };

  const abrirLoja = (loja) =>
    acao(async () => {
      await openShopBrowser(loja);
      onAbrirNavegador();
    });

  const novaLoja = () =>
    acao(async () => {
      await addShop();
      onAbrirNavegador();
    });

  const tirarLoja = (loja) => {
    if (!window.confirm(
      `Remover “${loja.name}”? O login salvo, os produtos baixados e os vínculos de produto desta loja são apagados. O histórico de publicações fica.`
    )) return;
    acao(() => removeShop(loja.key));
  };

  if (!dados) return <p className="muted">{erro || "Carregando..."}</p>;

  const s = dados.status;
  const q = s.queue || {};
  const itens = [...(dados.items || [])].reverse();
  const ativos = itens.filter((p) => p.state === "fila" || p.state === "enviando");
  const finalizados = itens.filter((p) => p.state !== "fila" && p.state !== "enviando");

  return (
    <>
      {erro && <div className="banner banner--error">{erro}</div>}

      {s.attention && (
        <div className="shop-atencao" role="alert">
          <div>
            <strong>A publicação precisa de você</strong>
            <p>{s.attention.message}</p>
          </div>
          <div className="shop-atencao__acoes">
            <button className="btn btn--xs btn--primary" onClick={onAbrirNavegador}>
              Ver navegador
            </button>
            <button className="btn btn--xs btn--ghost" onClick={() => acao(() => answerShop("continuar"))}>
              Continuar
            </button>
            <button className="btn btn--xs btn--ghost" onClick={() => acao(() => answerShop("pular"))}>
              Pular vídeo
            </button>
          </div>
        </div>
      )}

      <div className="card">
        <div className="shop-fila__topo">
          <div>
            <h3 className="card__title">Lojas TikTok Seller</h3>
            <p className="card__hint" style={{ margin: 0 }}>
              Cada loja guarda o seu login no servidor, com as suas contas e o seu
              catálogo. Você entra uma vez em cada; a publicação troca de loja sozinha.
              Se o TikTok pedir uma verificação de robô, ela aparece no navegador.
            </p>
          </div>
          {s.available && (
            <button className="btn btn--ghost" onClick={novaLoja} disabled={s.browser?.starting}>
              Adicionar loja
            </button>
          )}
        </div>
        {!s.available && <p className="shop-erro">{s.message}</p>}
        {(s.shops || []).length === 0 && s.available && (
          <div className="shop-botoes" style={{ marginTop: 12 }}>
            <button className="btn btn--primary" onClick={novaLoja}>
              Entrar na conta TikTok Seller
            </button>
          </div>
        )}
        <div className="shop-lojas">
          {(s.shops || []).map((l) => (
            <CartaoLoja
              key={l.key}
              loja={l}
              navegador={s.browser}
              publicando={!!q.current}
              onAbrir={() => (l.open ? onAbrirNavegador() : abrirLoja(l.key))}
              onFechar={() => acao(closeShopBrowser)}
              onSincronizar={() => acao(() => syncShopProducts(l.key))}
              onRemover={() => tirarLoja(l)}
            />
          ))}
        </div>
      </div>

      {(s.shops || []).length > 0 && <CatalogoDeProdutos lojas={s.shops} />}

      <div className="card">
        <div className="shop-fila__topo">
          <div>
            <h3 className="card__title">Fila de publicação</h3>
            <p className="card__hint" style={{ margin: 0 }}>
              {q.current
                ? `Publicando agora: ${q.current.step}.`
                : q.paused && q.pending
                ? `Pausada, com ${q.pending} ${q.pending === 1 ? "vídeo" : "vídeos"} esperando.`
                : q.pending && q.next_at
                ? `Próximo vídeo em ${contagem(q.next_at)} (intervalo de ${q.interval_min} min).`
                : q.pending
                ? `${q.pending} ${q.pending === 1 ? "vídeo" : "vídeos"} na fila.`
                : "Nada na fila."}
            </p>
          </div>
          <div className="shop-botoes">
            <button className="btn btn--primary" onClick={() => setEscolhendo(true)}>
              Escolher vídeos
            </button>
            {q.pending > 0 &&
              (q.paused ? (
                <button className="btn btn--ghost" onClick={() => acao(() => pauseShop(false))}>
                  Retomar
                </button>
              ) : (
                <button className="btn btn--ghost" onClick={() => acao(() => pauseShop(true))}>
                  Pausar
                </button>
              ))}
          </div>
        </div>

        {ativos.length > 0 && (
          <ul className="shop-lista">
            {ativos.map((p) => (
              <ItemFila key={p.id} pub={p} atual={q.current} onAcao={acao} />
            ))}
          </ul>
        )}
      </div>

      {finalizados.length > 0 && (
        <div className="card">
          <h3 className="card__title">Histórico</h3>
          <ul className="shop-lista">
            {finalizados.slice(0, 60).map((p) => (
              <ItemFila key={p.id} pub={p} onAcao={acao} />
            ))}
          </ul>
        </div>
      )}

      {escolhendo && (
        <EscolherVideos
          ocupados={new Set(ativos.map((p) => p.output_id))}
          onClose={() => setEscolhendo(false)}
          onDone={carregar}
        />
      )}
    </>
  );
}

/** Uma loja: login, contas, catálogo e o que dá para fazer com ela. */
function CartaoLoja({ loja, navegador, publicando, onAbrir, onFechar, onSincronizar, onRemover }) {
  const sync = loja.sync;
  const abrindo = navegador?.starting && navegador?.shop === loja.key;
  const pedeLogin = loja.open && navegador?.needs_login;
  const quando = (iso) =>
    new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  return (
    <div className={"shop-loja" + (loja.open ? " shop-loja--aberta" : "")}>
      <div className="shop-loja__topo">
        <span
          className={
            "shop-sessao__ponto" +
            (loja.open && !pedeLogin ? " shop-sessao__ponto--ok" : loja.configured ? " shop-sessao__ponto--salva" : "")
          }
          aria-hidden="true"
        />
        <strong className="shop-loja__nome">{loja.named ? loja.name : "Loja nova"}</strong>
        {loja.code && <span className="muted shop-loja__codigo">{loja.code}</span>}
      </div>
      <p className="shop-loja__estado">
        {pedeLogin
          ? "Entre na conta TikTok Seller desta loja no navegador."
          : sync?.running
          ? `Baixando produtos... ${sync.count || 0}`
          : sync?.error
          ? sync.error
          : loja.synced_at
          ? `${loja.products} produtos · atualizado em ${quando(loja.synced_at)}`
          : loja.configured
          ? "Login salvo. Produtos ainda não baixados."
          : "Ainda sem login."}
      </p>
      {loja.accounts.length > 0 && (
        <div className="shop-contas">
          {loja.accounts.map((c) => (
            <span className="shop-contas__item" key={c.handle}>
              <AvatarConta conta={c} tamanho={22} />@{c.handle}
              {c.role === 1 ? " · Oficial" : c.role === 2 ? " · Marketing" : ""}
            </span>
          ))}
        </div>
      )}
      <div className="shop-botoes" style={{ marginTop: 10 }}>
        <button className="btn btn--xs btn--primary" onClick={onAbrir} disabled={abrindo}>
          {abrindo ? "Abrindo..." : loja.open ? "Ver navegador" : loja.configured ? "Abrir navegador" : "Entrar na conta"}
        </button>
        {loja.configured && (
          <button className="btn btn--xs btn--ghost" onClick={onSincronizar} disabled={sync?.running}>
            Atualizar produtos
          </button>
        )}
        {loja.open && !publicando && (
          <button className="btn btn--xs btn--ghost" onClick={onFechar}>
            Fechar navegador
          </button>
        )}
        <button className="btn btn--xs btn--ghost shop-loja__remover" onClick={onRemover}>
          Remover
        </button>
      </div>
    </div>
  );
}

/** O catálogo baixado da Central: é dele que sai o produto de cada vídeo. */
function CatalogoDeProdutos({ lojas }) {
  const [produtos, setProdutos] = useState(null);
  const [loja, setLoja] = useState("");
  const [busca, setBusca] = useState("");
  const [erro, setErro] = useState("");
  // Recarrega quando alguma loja termina de sincronizar.
  const marca = lojas.map((l) => l.synced_at).join("|");

  useEffect(() => {
    carregarProdutos(true).then(setProdutos).catch((e) => setErro(e.message));
  }, [marca]);

  const nomes = Object.fromEntries(lojas.map((l) => [l.key, l.name]));
  const visiveis = (produtos || []).filter((p) => {
    const t = busca.trim().toLowerCase();
    if (loja && p.shop !== loja) return false;
    return !t || p.name.toLowerCase().includes(t) || p.id.includes(t);
  });

  if (!(produtos || []).length) return null;

  return (
    <div className="card">
      <h3 className="card__title">Produtos</h3>
      <p className="card__hint" style={{ margin: 0 }}>
        {(produtos || []).length} produtos baixados. Vincule cada vídeo-fonte a um
        produto de cada loja no painel dele.
      </p>
      {erro && <p className="shop-erro">{erro}</p>}
      <div className="shop-escolha__filtros" style={{ marginTop: 12 }}>
        <input
          className="input"
          placeholder="Buscar produto por nome ou ID"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />
        {lojas.length > 1 && (
          <select className="select" style={{ width: "auto" }} value={loja} onChange={(e) => setLoja(e.target.value)}>
            <option value="">Todas as lojas</option>
            {lojas.map((l) => (
              <option key={l.key} value={l.key}>
                {l.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="shop-produtos">
        {visiveis.map((p) => (
          <div className="shop-produto" key={p.id}>
            <Miniatura id={p.id} tamanho={44} />
            <div>
              <p className="shop-produto__nome" title={p.name}>{p.name}</p>
              <p className="shop-produto__meta">
                {p.id}
                {p.price ? ` · ${p.price}` : ""}
                {lojas.length > 1 && !loja ? ` · ${nomes[p.shop] || ""}` : ""}
                {p.links ? ` · ${p.links} ${p.links === 1 ? "vínculo" : "vínculos"}` : ""}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ItemFila({ pub, atual, onAcao }) {
  const o = pub.output || {};
  const produto = (pub.product_ids || [])[0];
  const agora = atual && atual.pub_id === pub.id;
  return (
    <li className={"shop-item shop-item--" + pub.state}>
      <div className="shop-item__mini">{o.file && <LazyVideo src={outputUrl(o.file)} />}</div>
      <div className="shop-item__corpo">
        <p className="shop-item__frase">{o.phrase || o.caption || "(vídeo removido)"}</p>
        <p className="shop-item__meta">
          <span className={"shop-selo shop-selo--" + pub.state}>{ROTULO[pub.state] || pub.state}</span>
          {pub.shop_name ? ` ${pub.shop_name} ·` : ""}
          {pub.target ? ` @${pub.target}` : " conta padrão"}
          {" · "}
          {produto ? `produto ${produto}` : "produto: escolher na hora"}
          {pub.published_at &&
            ` · ${new Date(pub.published_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}`}
        </p>
        {agora && <p className="shop-item__passo">{atual.step}...</p>}
        {pub.error && pub.state !== "publicado" && <p className="shop-item__erro">{pub.error}</p>}
      </div>
      <div className="shop-item__acoes">
        {pub.state === "fila" && (
          <button className="btn btn--xs btn--ghost" onClick={() => onAcao(() => cancelShopItem(pub.id))}>
            Cancelar
          </button>
        )}
        {(pub.state === "erro" || pub.state === "cancelado") && (
          <button className="btn btn--xs btn--ghost" onClick={() => onAcao(() => retryShopItem(pub.id))}>
            Tentar de novo
          </button>
        )}
      </div>
    </li>
  );
}

/** Escolha dos vídeos produzidos que ainda não saíram. */
function EscolherVideos({ ocupados, onClose, onDone }) {
  const [itens, setItens] = useState(null);
  const [marcados, setMarcados] = useState(() => new Set());
  const [busca, setBusca] = useState("");
  const [mostrarPublicados, setMostrarPublicados] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    getOutputs({ limit: 200 })
      .then((r) => setItens(r.items || []))
      .catch((e) => setErro(e.message));
  }, []);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return (itens || []).filter((o) => {
      if (ocupados.has(o.id)) return false;
      if (!mostrarPublicados && o.published) return false;
      if (!termo) return true;
      return [o.phrase, o.caption, o.theme, o.source_name, ...(o.hashtags || [])]
        .join(" ")
        .toLowerCase()
        .includes(termo);
    });
  }, [itens, busca, mostrarPublicados]);

  const alternar = (id) =>
    setMarcados((atual) => {
      const n = new Set(atual);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const escolhidos = (itens || []).filter((o) => marcados.has(o.id));

  if (confirmando) {
    return (
      <ShopPublishDialog
        outputs={escolhidos}
        onClose={onClose}
        onDone={onDone}
      />
    );
  }

  return (
    <div className="modal-fundo" role="presentation" onClick={onClose}>
      <section
        className="modal shop-escolha"
        role="dialog"
        aria-modal="true"
        aria-label="Escolher vídeos para o TikTok Shop"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal__topo">
          <h2>Escolher vídeos</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fechar">
            ×
          </button>
        </header>
        <div className="shop-escolha__filtros">
          <input
            className="input"
            placeholder="Buscar por frase, legenda, tema ou hashtag"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
          <label className="shop-escolha__check">
            <input
              type="checkbox"
              checked={mostrarPublicados}
              onChange={(e) => setMostrarPublicados(e.target.checked)}
            />
            Mostrar já publicados
          </label>
          <button
            className="btn btn--xs btn--ghost"
            onClick={() =>
              setMarcados((atual) => {
                const todos = visiveis.every((o) => atual.has(o.id));
                const n = new Set(atual);
                visiveis.forEach((o) => (todos ? n.delete(o.id) : n.add(o.id)));
                return n;
              })
            }
          >
            {visiveis.length && visiveis.every((o) => marcados.has(o.id)) ? "Limpar" : "Marcar todos"}
          </button>
        </div>
        {erro && <p className="shop-erro">{erro}</p>}
        <div className="shop-escolha__grade">
          {itens === null && <p className="muted">Carregando...</p>}
          {itens !== null && visiveis.length === 0 && (
            <p className="muted">Nenhum vídeo para publicar com esse filtro.</p>
          )}
          {visiveis.map((o) => (
            <label key={o.id} className={"shop-escolha__card" + (marcados.has(o.id) ? " is-on" : "")}>
              <input type="checkbox" checked={marcados.has(o.id)} onChange={() => alternar(o.id)} />
              <div className="shop-escolha__video">
                <LazyVideo src={outputUrl(o.file)} />
              </div>
              <span className="shop-escolha__frase">{o.phrase || o.caption || "(sem frase)"}</span>
              {o.source_name && <span className="shop-escolha__fonte">{o.source_name}</span>}
            </label>
          ))}
        </div>
        <footer className="modal__rodape">
          <span className="muted">{marcados.size} selecionados</span>
          <button className="btn btn--ghost" onClick={onClose}>
            Cancelar
          </button>
          <button
            className="btn btn--primary"
            disabled={marcados.size === 0}
            onClick={() => setConfirmando(true)}
          >
            Continuar
          </button>
        </footer>
      </section>
    </div>
  );
}
