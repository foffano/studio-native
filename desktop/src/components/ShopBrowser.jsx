import React, { useEffect, useRef, useState } from "react";
import {
  answerShop,
  closeShopBrowser,
  getShopStatus,
  sendShopInput,
  setShopRecording,
  shopFrameUrl,
  shopRecordingUrl,
  shopSnapshot,
} from "../api.js";

/**
 * O navegador do TikTok Seller que roda no servidor, visto e controlado daqui.
 *
 * O servidor não tem tela: o Chromium desenha numa tela virtual, e esta janela
 * mostra uma foto dela a cada meio segundo. Clique, rolagem e teclado voltam
 * pelo /input e viram eventos de verdade na página. É por aqui que se faz o
 * login e que se resolve a verificação anti-robô quando o TikTok pede.
 *
 * Mesmo desenho do painel do eco-native.
 */
const TECLAS = [
  "Backspace", "Delete", "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown",
  "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown",
];

export default function ShopBrowser({ onClose }) {
  const [nonce, setNonce] = useState(0);
  const [pronto, setPronto] = useState(false);
  const [status, setStatus] = useState(null);
  const [erro, setErro] = useState("");
  const statusRef = useRef(null);
  const frameRef = useRef(null);
  const fila = useRef(Promise.resolve());
  const caminho = useRef([]);
  const roda = useRef(null);
  const arrasto = useRef(null);

  const largura = status?.browser?.width || 1280;
  const altura = status?.browser?.height || 800;

  useEffect(() => {
    let cancelado = false;
    let timer;
    async function atualizar() {
      try {
        const s = await getShopStatus();
        if (!cancelado) {
          statusRef.current = s;
          setStatus(s);
          setNonce((n) => n + 1);
        }
      } catch (e) {
        if (!cancelado) setErro(e.message);
      } finally {
        if (!cancelado) timer = window.setTimeout(atualizar, 550);
      }
    }
    atualizar();
    return () => {
      cancelado = true;
      window.clearTimeout(timer);
    };
  }, []);

  // Um pedido por vez: em paralelo eles chegam fora de ordem e embaralham o
  // texto digitado e o caminho do arrasto. Payload em função é montado na vez.
  function enviar(payload) {
    fila.current = fila.current.then(async () => {
      const corpo = typeof payload === "function" ? payload() : payload;
      if (!corpo) return;
      try {
        await sendShopInput({ page_id: statusRef.current?.browser?.active_page_id, ...corpo });
        setErro("");
      } catch (e) {
        setErro(e.message);
      }
    });
  }

  function enviarCaminho() {
    enviar(() => {
      const pontos = caminho.current.splice(0, 120);
      if (caminho.current.length) enviarCaminho();
      return pontos.length ? { type: "move", path: pontos } : null;
    });
  }

  function enviarRoda(dx, dy) {
    if (roda.current) {
      roda.current.x += dx;
      roda.current.y += dy;
      return;
    }
    roda.current = { x: dx, y: dy };
    enviar(() => {
      const r = roda.current;
      roda.current = null;
      if (!r) return null;
      const lim = (v) => Math.max(-5000, Math.min(5000, v));
      return { type: "wheel", delta_x: lim(r.x), delta_y: lim(r.y) };
    });
  }

  function ponto(ev) {
    // Mede a própria imagem desenhada: assim uma mudança de layout não
    // desloca o clique para longe do que a pessoa está vendo.
    const rect = (frameRef.current ?? ev.currentTarget).getBoundingClientRect();
    const escala = Math.min(rect.width / largura, rect.height / altura);
    const offX = (rect.width - largura * escala) / 2;
    const offY = (rect.height - altura * escala) / 2;
    return {
      x: Math.max(0, Math.min(largura, (ev.clientX - rect.left - offX) / escala)),
      y: Math.max(0, Math.min(altura, (ev.clientY - rect.top - offY) / escala)),
    };
  }

  function aoApertar(ev) {
    if (ev.button > 2) return;
    ev.currentTarget.focus();
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const botao = ev.button === 2 ? "right" : ev.button === 1 ? "middle" : "left";
    arrasto.current = { inicio: ponto(ev), botao, moveu: false, ultimo: ev.timeStamp };
  }

  function aoMover(ev) {
    const a = arrasto.current;
    if (!a) return;
    const p = ponto(ev);
    if (!a.moveu) {
      // Tremidinha ainda é clique; além disso é arrasto (quebra-cabeça de
      // deslizar da verificação).
      if (Math.hypot(p.x - a.inicio.x, p.y - a.inicio.y) < 4) return;
      a.moveu = true;
      enviar({ type: "down", button: a.botao, ...a.inicio });
    }
    const atraso = Math.max(0, Math.min(1000, Math.round(ev.timeStamp - a.ultimo)));
    a.ultimo = ev.timeStamp;
    if (caminho.current.push([p.x, p.y, atraso]) === 1) enviarCaminho();
  }

  function aoSoltar(ev) {
    const a = arrasto.current;
    arrasto.current = null;
    if (!a) return;
    enviar({ type: a.moveu ? "up" : "click", button: a.botao, ...ponto(ev) });
  }

  function aoTeclar(ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) {
      const mods = [ev.ctrlKey && "Control", ev.altKey && "Alt", ev.metaKey && "Meta"].filter(Boolean);
      enviar({ type: "key", key: [...mods, ev.key].join("+") });
    } else if (ev.key.length === 1) {
      enviar({ type: "text", text: ev.key });
    } else if (TECLAS.includes(ev.key)) {
      enviar({ type: "key", key: ev.key });
    } else {
      return;
    }
    ev.preventDefault();
  }

  async function responder(acao) {
    try {
      setStatus(await answerShop(acao));
    } catch (e) {
      setErro(e.message);
    }
  }

  async function concluir() {
    // Com fila andando, o navegador continua aberto: só a janela some.
    if (!status?.queue?.pending && !status?.queue?.current) {
      try {
        await closeShopBrowser();
      } catch (_) {
        /* fechar é melhor-esforço; o navegador também fecha sozinho ocioso */
      }
    }
    onClose();
  }

  const b = status?.browser || {};
  const atencao = status?.attention;
  const atual = status?.queue?.current;

  return (
    <div className="shopnav-fundo" role="presentation">
      <section className="shopnav" role="dialog" aria-modal="true" aria-label="Navegador do TikTok Seller">
        <header className="shopnav__barra">
          <div className="shopnav__titulo">
            <strong>
              TikTok Seller{b.shop_name ? ` · ${b.shop_name}` : ""} · navegador do servidor
            </strong>
            <span>
              {b.loading && <span className="spinner spinner--sm" aria-label="Carregando" />}{" "}
              {b.url || status?.message || "Abrindo o navegador..."}
            </span>
            {(b.pages || []).length > 1 && (
              <label className="shopnav__abas">
                Janela:{" "}
                <select
                  className="select"
                  value={b.active_page_id || ""}
                  onChange={(e) => enviar({ type: "select_page", page_id: e.target.value })}
                >
                  {b.pages.map((p, i) => (
                    <option key={p.id} value={p.id}>
                      {i + 1} · {p.url || "abrindo..."}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="shopnav__acoes">
            <button className="btn btn--xs btn--ghost" title="Voltar" onClick={() => enviar({ type: "navigate", action: "back" })}>
              ←
            </button>
            <button className="btn btn--xs btn--ghost" title="Recarregar" onClick={() => enviar({ type: "navigate", action: "reload" })}>
              ↻
            </button>
            <button className="btn btn--xs btn--ghost" title="Página de vídeos da Central" onClick={() => enviar({ type: "navigate", action: "home" })}>
              Início
            </button>
            {/* Gravar: você faz o fluxo à mão e o app guarda cada clique e a
                tela depois dele. É o material para ajustar a automação ao
                site real. */}
            {status?.recording?.on ? (
              <>
                <button className="btn btn--xs btn--ghost" onClick={() => shopSnapshot().catch((e) => setErro(e.message))}>
                  Capturar tela
                </button>
                <button className="btn btn--xs btn--danger" onClick={() => setShopRecording(false).then(setStatus).catch((e) => setErro(e.message))}>
                  ● Parar gravação ({status.recording.count})
                </button>
              </>
            ) : (
              <>
                <button className="btn btn--xs btn--ghost" onClick={() => setShopRecording(true).then(setStatus).catch((e) => setErro(e.message))}>
                  Gravar sessão
                </button>
                {status?.recording?.last && (
                  <a className="btn btn--xs btn--ghost" href={shopRecordingUrl()}>
                    Baixar gravação
                  </a>
                )}
              </>
            )}
            <button className="btn btn--xs btn--ghost" onClick={onClose}>
              Ocultar
            </button>
            <button className="btn btn--xs btn--primary" onClick={concluir}>
              Concluir
            </button>
          </div>
        </header>

        {atencao && (
          <div className="shopnav__atencao" role="alert">
            <span>{atencao.message}</span>
            <div className="shopnav__atencao-acoes">
              <button className="btn btn--xs btn--primary" onClick={() => responder("continuar")}>
                Continuar
              </button>
              <button className="btn btn--xs btn--ghost" onClick={() => responder("publicado")}>
                Já publicou
              </button>
              <button className="btn btn--xs btn--ghost" onClick={() => responder("pular")}>
                Pular vídeo
              </button>
            </div>
          </div>
        )}

        <div
          className="shopnav__tela"
          tabIndex={0}
          onPointerDown={aoApertar}
          onPointerMove={aoMover}
          onPointerUp={aoSoltar}
          onPointerCancel={() => (arrasto.current = null)}
          onContextMenu={(e) => e.preventDefault()}
          onWheel={(e) => enviarRoda(e.deltaX, e.deltaY)}
          onKeyDown={aoTeclar}
          onPaste={(e) => {
            e.preventDefault();
            enviar({ type: "text", text: e.clipboardData.getData("text") });
          }}
        >
          {!pronto && (
            <div className="shopnav__carregando">
              <span className="spinner" /> Aguardando a imagem do navegador...
            </div>
          )}
          {b.open && (
            <img
              ref={frameRef}
              src={shopFrameUrl(nonce)}
              alt="Tela do navegador do TikTok Seller"
              draggable={false}
              onLoad={() => setPronto(true)}
            />
          )}
        </div>

        <footer className="shopnav__rodape">
          {erro ||
            (atual
              ? `Publicando: ${atual.step}${atual.phrase ? " · " + atual.phrase.slice(0, 60) : ""}`
              : status?.message)}
          {" · "}Clique na imagem para usar o teclado.
        </footer>
      </section>
    </div>
  );
}
