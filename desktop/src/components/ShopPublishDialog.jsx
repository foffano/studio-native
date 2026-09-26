import React, { useEffect, useState } from "react";
import { enqueueShop, getShopStatus, outputUrl } from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import ProductPicker from "./ProductPicker.jsx";
import AccountPicker from "./AccountPicker.jsx";

/**
 * Coloca vídeos na fila do TikTok Shop.
 *
 * A conta decide a loja: cada loja da Central do Vendedor tem as suas contas
 * vinculadas e o seu catálogo. Por isso o produto só pode ser escolhido entre
 * os da loja da conta marcada, e já vem do vínculo do vídeo naquela loja.
 * Trocar o produto aqui grava o novo vínculo.
 *
 * Sem produto, a automação para naquele vídeo e pede para você escolher no
 * navegador — e lembra a escolha.
 */

/** O produto já vinculado a cada vídeo, na loja dada. */
const vinculadosNa = (outputs, loja) =>
  Object.fromEntries(outputs.map((o) => [o.id, (o.shop_products || {})[loja]?.resolved || ""]));

export default function ShopPublishDialog({ outputs, onClose, onDone }) {
  const [status, setStatus] = useState(null);
  // "loja/@conta": o @ sozinho não basta, a mesma conta pode estar em duas lojas.
  const [escolha, setEscolha] = useState("");
  const [intervalo, setIntervalo] = useState(3);
  const [produtos, setProdutos] = useState({});
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  const [loja, conta] = escolha ? escolha.split("/") : ["", ""];

  useEffect(() => {
    getShopStatus()
      .then((s) => {
        setStatus(s);
        setIntervalo(s.queue?.interval_min || 3);
        const contas = (s.accounts || []).filter((c) => c.eligible !== false);
        const chave = (c) => `${c.shop}/${c.handle}`;
        // A última usada, senão a primeira (a oficial da primeira loja).
        const inicial = contas.some((c) => chave(c) === s.last_account)
          ? s.last_account
          : contas[0]
          ? chave(contas[0])
          : (s.shops || [])[0]
          ? `${s.shops[0].key}/`
          : "";
        setEscolha(inicial);
      })
      .catch((e) => setErro(e.message));
  }, []);

  // Trocar de loja troca o catálogo: os produtos vêm do vínculo daquela loja.
  useEffect(() => {
    if (loja) setProdutos(vinculadosNa(outputs, loja));
  }, [loja]);

  useEffect(() => {
    const aoTeclar = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onClose]);

  const lojas = status?.shops || [];
  const nomeDaLoja = (lojas.find((l) => l.key === loja) || {}).name || "";
  const semProduto = outputs.filter((o) => !produtos[o.id]).length;

  async function confirmar() {
    setEnviando(true);
    setErro("");
    try {
      const r = await enqueueShop({
        shop: loja,
        account: (conta || "").replace(/^@/, ""),
        interval_min: Number(intervalo) || 3,
        items: outputs.map((o) => ({ output_id: o.id, product: produtos[o.id] || "" })),
      });
      onDone && onDone(r);
      onClose();
    } catch (e) {
      setErro(e.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="modal-fundo" role="presentation" onClick={onClose}>
      <section
        className="modal shop-dialogo"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shop-dialogo-titulo"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal__topo">
          <h2 id="shop-dialogo-titulo">
            Publicar {outputs.length} {outputs.length === 1 ? "vídeo" : "vídeos"} no TikTok Shop
          </h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fechar">
            ×
          </button>
        </header>

        {status && !status.available && <div className="banner banner--error">{status.message}</div>}
        {status?.available && lojas.length === 0 && (
          <div className="banner banner--warn">
            Nenhuma loja conectada. Em TikTok Shop, toque em “Adicionar loja” e entre na
            conta TikTok Seller.
          </div>
        )}

        <div className="field">
          <span className="field__label">Conta que publica</span>
          {lojas.map((l) => {
            const contas = (status.accounts || []).filter((c) => c.shop === l.key);
            return (
              <div className="shop-dialogo__loja" key={l.key}>
                {lojas.length > 1 && <span className="shop-dialogo__nome-loja">{l.name}</span>}
                {contas.length > 0 ? (
                  <AccountPicker
                    contas={contas}
                    value={loja === l.key ? conta : ""}
                    onChange={(h) => setEscolha(`${l.key}/${h}`)}
                  />
                ) : (
                  <button
                    type="button"
                    className={"conta" + (loja === l.key ? " is-on" : "")}
                    onClick={() => setEscolha(`${l.key}/`)}
                  >
                    <span className="conta__texto">
                      <span className="conta__handle">A conta que o TikTok deixar marcada</span>
                      <span className="conta__meta">Contas desta loja ainda não baixadas</span>
                    </span>
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="field">
          <span className="field__label">
            Produto (carrinho laranja){nomeDaLoja && lojas.length > 1 ? ` · ${nomeDaLoja}` : ""}
          </span>
          {outputs.length > 1 && (
            <div className="shop-dialogo__todos">
              <ProductPicker
                shop={loja}
                value=""
                placeholder="Aplicar um produto a todos..."
                onChange={(id) => setProdutos(Object.fromEntries(outputs.map((o) => [o.id, id])))}
              />
            </div>
          )}
          <div className="shop-dialogo__lista">
            {outputs.map((o) => (
              <div className="shop-dialogo__item" key={o.id}>
                <div className="shop-dialogo__mini">
                  <LazyVideo src={outputUrl(o.file)} />
                </div>
                <div className="shop-dialogo__item-corpo">
                  <p className="shop-dialogo__frase">{o.phrase || o.caption || "(sem frase)"}</p>
                  <ProductPicker
                    compacto
                    shop={loja}
                    value={produtos[o.id]}
                    placeholder="Escolher na hora, no navegador"
                    onChange={(id) => setProdutos((atual) => ({ ...atual, [o.id]: id }))}
                  />
                </div>
              </div>
            ))}
          </div>
          <span className="field__hint">
            Já vem o produto vinculado a cada vídeo nesta loja (ou ao vídeo-fonte).
            Trocar aqui grava o novo vínculo.{" "}
            {semProduto > 0 &&
              `${semProduto} ${semProduto === 1 ? "vídeo está" : "vídeos estão"} sem produto: a automação vai parar e pedir para você escolher no navegador.`}
          </span>
        </div>

        <label className="field">
          <span className="field__label">Intervalo entre vídeos (minutos)</span>
          <input
            className="input"
            type="number"
            min="0.5"
            max="240"
            step="0.5"
            value={intervalo}
            onChange={(e) => setIntervalo(e.target.value)}
            style={{ maxWidth: 140 }}
          />
          <span className="field__hint">
            Um vídeo por vez, com esse intervalo (e uma variação aleatória) entre um e
            outro. Publicar tudo em rajada chama a atenção do anti-robô.
          </span>
        </label>

        {erro && <p className="shop-erro">{erro}</p>}

        <footer className="modal__rodape">
          <button className="btn btn--ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn--primary" disabled={enviando || !status || !loja} onClick={confirmar}>
            {enviando ? "Colocando na fila..." : "Colocar na fila"}
          </button>
        </footer>
      </section>
    </div>
  );
}
