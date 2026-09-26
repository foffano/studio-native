import React, { useEffect, useMemo, useRef, useState } from "react";
import { getShopProducts, linkShopProduct, shopThumbUrl } from "../api.js";

/**
 * Escolha de um produto do catálogo do TikTok Shop (baixado da Central do
 * Vendedor). Mostra foto, nome e ID — o nome sozinho engana quando a loja tem
 * vários "Suporte Porta Foto..." parecidos.
 */

// Uma busca por sessão de tela, compartilhada por todos os seletores abertos:
// numa lista de 40 vídeos, cada um pedindo o catálogo seria um desperdício.
// Vem o catálogo de todas as lojas; cada seletor filtra a sua.
let cache = null;
function carregarCatalogo(forcar = false) {
  if (!cache || forcar) {
    cache = getShopProducts()
      .then((r) => ({ items: r.items || [], shops: r.shops || [] }))
      .catch((e) => {
        cache = null;
        throw e;
      });
  }
  return cache;
}
export const carregarProdutos = (forcar = false) => carregarCatalogo(forcar).then((c) => c.items);
export const carregarLojas = (forcar = false) => carregarCatalogo(forcar).then((c) => c.shops);

export function Miniatura({ id, tamanho = 36 }) {
  const [falhou, setFalhou] = useState(false);
  useEffect(() => setFalhou(false), [id]);
  const estilo = { width: tamanho, height: tamanho };
  if (!id || falhou) return <span className="produto-mini produto-mini--vazia" style={estilo} aria-hidden="true" />;
  return (
    <img
      className="produto-mini"
      style={estilo}
      src={shopThumbUrl(id)}
      alt=""
      loading="lazy"
      onError={() => setFalhou(true)}
    />
  );
}

export default function ProductPicker({ value, onChange, shop, herdado = "", placeholder = "Escolher produto", compacto = false }) {
  const [produtos, setProdutos] = useState(null);
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const [erro, setErro] = useState("");
  const caixa = useRef(null);

  useEffect(() => {
    carregarProdutos().then(setProdutos).catch((e) => setErro(e.message));
  }, []);

  useEffect(() => {
    if (!aberto) return undefined;
    const fora = (e) => caixa.current && !caixa.current.contains(e.target) && setAberto(false);
    const esc = (e) => e.key === "Escape" && setAberto(false);
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [aberto]);

  const efetivo = value || herdado;
  const atual = (produtos || []).find((p) => p.id === efetivo);
  const daLoja = useMemo(
    () => (produtos || []).filter((p) => !shop || p.shop === shop),
    [produtos, shop]
  );
  const visiveis = useMemo(() => {
    const t = busca.trim().toLowerCase();
    return daLoja.filter((p) => !t || p.name.toLowerCase().includes(t) || p.id.includes(t));
  }, [daLoja, busca]);

  const escolher = (id) => {
    onChange(id);
    setAberto(false);
    setBusca("");
  };

  return (
    <div className={"produto-picker" + (compacto ? " produto-picker--compacto" : "")} ref={caixa}>
      <button type="button" className="produto-picker__atual" onClick={() => setAberto((v) => !v)}>
        <Miniatura id={efetivo} tamanho={compacto ? 28 : 36} />
        <span className="produto-picker__texto">
          {efetivo ? (
            <>
              <span className="produto-picker__nome">{atual?.name || "Produto " + efetivo}</span>
              <span className="produto-picker__id">
                {efetivo}
                {!value && herdado ? " · do vídeo-fonte" : ""}
              </span>
            </>
          ) : (
            <span className="produto-picker__nome muted">{placeholder}</span>
          )}
        </span>
        <span aria-hidden="true">▾</span>
      </button>

      {aberto && (
        <div className="produto-picker__lista" role="listbox">
          <input
            className="input input--sm"
            autoFocus
            placeholder="Buscar por nome ou ID"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
          {erro && <p className="shop-erro">{erro}</p>}
          {produtos && daLoja.length === 0 && (
            <p className="muted produto-picker__vazio">
              Nenhum produto baixado ainda. Em TikTok Shop, toque em “Atualizar produtos”.
            </p>
          )}
          <div className="produto-picker__opcoes">
            {(value || (!herdado && efetivo)) && (
              <button type="button" className="produto-picker__opcao" onClick={() => escolher("")}>
                <span className="produto-mini produto-mini--vazia" />
                <span className="produto-picker__texto">
                  <span className="produto-picker__nome">
                    {herdado ? "Usar o do vídeo-fonte" : "Sem produto"}
                  </span>
                </span>
              </button>
            )}
            {visiveis.slice(0, 80).map((p) => (
              <button
                type="button"
                role="option"
                aria-selected={p.id === efetivo}
                key={p.id}
                className={"produto-picker__opcao" + (p.id === efetivo ? " is-on" : "")}
                onClick={() => escolher(p.id)}
              >
                <Miniatura id={p.id} />
                <span className="produto-picker__texto">
                  <span className="produto-picker__nome">{p.name}</span>
                  <span className="produto-picker__id">
                    {p.id}
                    {p.price ? ` · ${p.price}` : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * O produto de um vídeo em cada loja, editável ali mesmo. `kind="library"`
 * vincula o vídeo-fonte (vale para tudo que sair dele); `kind="output"`
 * vincula só este produzido, por cima do que veio da fonte.
 *
 * `vinculos` = {loja: {own, resolved}} (produzido) ou {loja: id} (fonte).
 * Com uma loja só, é um seletor; com várias, um por loja.
 */
export function ProdutoDoVideo({ kind, refId, vinculos = {}, rotulo = "Produto no TikTok Shop", onMudou }) {
  const [lojas, setLojas] = useState(null);
  useEffect(() => {
    carregarLojas().then(setLojas).catch(() => setLojas([]));
  }, []);
  if (!lojas || lojas.length === 0) return null;
  return (
    <div className="produto-do-video">
      <span className="produto-do-video__rotulo">{rotulo}</span>
      {lojas.map((l) => {
        const v = vinculos[l.key];
        const proprio = typeof v === "string" ? v : v?.own || "";
        const herdado = typeof v === "string" ? "" : v?.own ? "" : v?.resolved || "";
        return (
          <VinculoNaLoja
            key={l.key}
            kind={kind}
            refId={refId}
            loja={l}
            mostrarLoja={lojas.length > 1}
            proprio={proprio}
            herdado={herdado}
            onMudou={onMudou}
          />
        );
      })}
    </div>
  );
}

function VinculoNaLoja({ kind, refId, loja, mostrarLoja, proprio, herdado, onMudou }) {
  const [valor, setValor] = useState(proprio);
  const [erro, setErro] = useState("");
  useEffect(() => setValor(proprio), [proprio, refId]);

  const mudar = async (id) => {
    const anterior = valor;
    setValor(id);
    setErro("");
    try {
      await linkShopProduct(kind, refId, loja.key, id);
      onMudou && onMudou(id);
    } catch (e) {
      setValor(anterior);
      setErro(e.message);
    }
  };

  return (
    <div className="produto-do-video__loja">
      {mostrarLoja && <span className="produto-do-video__nome-loja">{loja.name}</span>}
      <ProductPicker
        shop={loja.key}
        value={valor}
        herdado={herdado}
        onChange={mudar}
        compacto
        placeholder="Sem produto vinculado"
      />
      {erro && <p className="shop-erro">{erro}</p>}
    </div>
  );
}
