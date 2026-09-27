import React, { useEffect, useState } from "react";
import { importShopLogin } from "../api.js";

/**
 * Traz o login de um Chrome já logado na Central do Vendedor.
 *
 * Existe porque o servidor fica num datacenter fora do Brasil, e a tela de
 * login do TikTok bloqueia esse IP ("acessando com muita frequência"). No
 * computador, com a internet de casa, o login passa; os cookies dessa sessão
 * levam o login para o navegador do servidor sem passar pela tela.
 */
export default function ImportLoginDialog({ loja, onClose, onDone }) {
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  async function importar() {
    setEnviando(true);
    setErro("");
    try {
      await importShopLogin(loja.key, texto);
      onDone && onDone();
      onClose();
    } catch (e) {
      setErro(e.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="modal-fundo" role="presentation" onClick={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="importar-titulo" onClick={(e) => e.stopPropagation()}>
        <header className="modal__topo">
          <h2 id="importar-titulo">Importar login · {loja.named ? loja.name : "loja nova"}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fechar">×</button>
        </header>
        <ol className="importar-passos">
          <li>
            No Chrome do seu computador, instale a extensão{" "}
            <a href="https://chromewebstore.google.com/search/Cookie-Editor" target="_blank" rel="noreferrer">
              Cookie-Editor
            </a>
            .
          </li>
          <li>
            Abra{" "}
            <a href="https://seller-br.tiktok.com/" target="_blank" rel="noreferrer">
              seller-br.tiktok.com
            </a>{" "}
            e entre na conta desta loja, até ver a Central do Vendedor.
          </li>
          <li>
            Nessa aba, clique no ícone do Cookie-Editor › <strong>Export</strong> ›{" "}
            <strong>JSON</strong>. Os cookies vão para a área de transferência.
          </li>
          <li>Cole abaixo e toque em Importar.</li>
        </ol>
        <textarea
          className="textarea importar-campo"
          placeholder='[{"name": "sessionid", "value": "...", "domain": ".tiktok.com", ...}]'
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          spellCheck={false}
        />
        <p className="field__hint">
          Também aceita o cookies.txt da extensão “Get cookies.txt LOCALLY”. Os cookies
          são o login: não mande para ninguém. Depois de importar, não use “Sair” no
          Chrome do computador — isso encerra a sessão para o servidor também; basta
          fechar a aba.
        </p>
        {erro && <p className="shop-erro">{erro}</p>}
        <footer className="modal__rodape">
          <button className="btn btn--ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn--primary" disabled={enviando || !texto.trim()} onClick={importar}>
            {enviando ? "Importando..." : "Importar"}
          </button>
        </footer>
      </section>
    </div>
  );
}
