import React, { useEffect, useRef, useState } from "react";
import {
  cancelTikTokConnect,
  disconnectTikTok,
  getTikTokAccount,
  getTikTokConnectStatus,
  openAuthorizeUrl,
  startTikTokConnect,
} from "../api.js";

// O usuário sai do app para autorizar no navegador e volta quando termina.
// Como não há evento nenhum avisando disso, a tela pergunta ao backend de dois
// em dois segundos — o mesmo padrão que o generationManager já usa para jobs.
const POLL_MS = 2000;

export default function TikTokAccount() {
  const [accounts, setAccounts] = useState([]);
  const [cifraDoSistema, setCifraDoSistema] = useState(true);
  const [fase, setFase] = useState("carregando"); // carregando | pronto | aguardando
  const [erro, setErro] = useState("");
  const [restante, setRestante] = useState(0);
  const poll = useRef(null);

  const pararPoll = () => {
    if (poll.current) {
      clearInterval(poll.current);
      poll.current = null;
    }
  };

  const carregar = async () => {
    try {
      const r = await getTikTokAccount();
      setAccounts(r.accounts || (r.account ? [r.account] : []));
      setCifraDoSistema(r.cifra_do_sistema !== false);
      setFase("pronto");
    } catch (e) {
      setErro(e.message);
      setFase("pronto");
    }
  };

  useEffect(() => {
    carregar();
    // Um login pode ter ficado pendente de uma visita anterior a esta tela.
    // Sem isto, sair de Ajustes e voltar perderia o fluxo em andamento.
    getTikTokConnectStatus()
      .then((s) => {
        if (s.state === "aguardando") {
          setFase("aguardando");
          iniciarPoll();
        }
      })
      .catch(() => {});
    return pararPoll;
  }, []);

  function iniciarPoll() {
    pararPoll();
    poll.current = setInterval(async () => {
      try {
        const s = await getTikTokConnectStatus();
        setRestante(s.expira_em || 0);
        if (s.state === "conectado") {
          pararPoll();
          await carregar();
          setErro("");
        } else if (s.state === "erro") {
          pararPoll();
          setFase("pronto");
          setErro(s.error || "O login não foi concluído.");
        } else if (s.state === "ocioso") {
          pararPoll();
          setFase("pronto");
        }
      } catch (e) {
        pararPoll();
        setFase("pronto");
        setErro(e.message);
      }
    }, POLL_MS);
  }

  async function conectar() {
    setErro("");
    setFase("aguardando");
    try {
      const r = await startTikTokConnect();
      setRestante(r.expira_em || 0);
      await openAuthorizeUrl(r.url);
      iniciarPoll();
    } catch (e) {
      // Se abrir o navegador falhou, o listener na 43117 ficaria de pé
      // esperando alguém que nunca vem. Derrubamos junto.
      cancelTikTokConnect().catch(() => {});
      setFase("pronto");
      setErro(e.message);
    }
  }

  async function cancelar() {
    pararPoll();
    try {
      await cancelTikTokConnect();
    } catch (_) {
      /* cancelar é melhor-esforço */
    }
    setFase("pronto");
  }

  async function desconectar(account) {
    const nome = account?.nickname ? `@${account.nickname}` : "esta conta";
    if (!window.confirm(`Desconectar ${nome}? Os tokens salvos serão apagados.`)) {
      return;
    }
    setErro("");
    try {
      await disconnectTikTok(account.id);
      setAccounts((items) => items.filter((item) => item.id !== account.id));
    } catch (e) {
      setErro(e.message);
    }
  }

  return (
    <div className="card">
      <h3 className="card__title">Conta do TikTok</h3>
      <p className="card__hint">
        Conecte a conta para enviar os vídeos gerados direto ao TikTok. Eles
        chegam na Caixa de entrada do app, onde você revisa e publica. O arquivo
        vai do seu computador para o TikTok — nenhum vídeo passa por servidor
        nosso.
      </p>

      {fase === "carregando" && <p className="muted">Verificando...</p>}

      {fase === "pronto" && accounts.length > 0 && (
        <>
          <div className="tiktok-accounts">
            {accounts.map((account) => (
              <div className="tiktok-account-row" key={account.id}>
                <Avatar url={account.avatar_url} nome={account.nickname} />
                <div className="tiktok-account-row__info">
                  <div style={{ fontWeight: 600 }}>
                    @{account.nickname || "conta conectada"}
                  </div>
                  <div className="muted" style={{ fontSize: "var(--text-sm)" }}>
                    {(account.scopes || "").split(",").filter(Boolean).join(" · ") ||
                      "sem escopos declarados"}
                  </div>
                </div>
                <button
                  className="btn btn--ghost btn--xs"
                  onClick={() => desconectar(account)}
                >
                  Desconectar
                </button>
              </div>
            ))}
          </div>
          <button className="btn btn--primary" onClick={conectar}>
            Adicionar outra conta
          </button>
        </>
      )}

      {fase === "pronto" && accounts.length === 0 && (
        <button className="btn btn--primary" onClick={conectar}>
          Conectar TikTok
        </button>
      )}

      {fase === "aguardando" && (
        <>
          <p style={{ margin: "14px 0 10px" }}>
            Autorize no navegador que acabou de abrir. Esta tela atualiza sozinha
            quando você terminar.
            {restante > 0 && (
              <span className="muted"> Expira em {Math.ceil(restante / 60)} min.</span>
            )}
          </p>
          <button className="btn btn--ghost" onClick={cancelar}>
            Cancelar
          </button>
        </>
      )}

      {erro && (
        <p style={{ color: "#f87171", marginTop: 12 }}>{erro}</p>
      )}

      {!cifraDoSistema && (
        <p className="card__hint" style={{ marginTop: 12 }}>
          Neste sistema os tokens ficam apenas ofuscados, não cifrados — a
          proteção do Windows (DPAPI) não existe aqui. Trate esta máquina como
          confiável.
        </p>
      )}
    </div>
  );
}


/**
 * A foto da conta, com as iniciais quando ela não carrega.
 *
 * O TikTok assina a URL da foto e ela **vence em cerca de um dia**. O backend
 * renova quando percebe que venceu, mas isso não cobre tudo: a página pode
 * ficar aberta horas, e o carimbo vira no meio. Sem isto, o que aparecia era um
 * ícone de imagem quebrada — que se lê como "a conta caiu", quando a conta está
 * perfeita.
 */
function Avatar({ url, nome }) {
  const [falhou, setFalhou] = React.useState(false);

  // Uma URL nova merece nova tentativa: sem isto, o retrato quebrado ficaria
  // preso mesmo depois de o backend renovar a foto.
  React.useEffect(() => setFalhou(false), [url]);

  const base = {
    width: 44,
    height: 44,
    borderRadius: "50%",
    flex: "0 0 auto",
  };

  if (url && !falhou) {
    return (
      <img
        src={url}
        alt=""
        width={44}
        height={44}
        style={{ ...base, objectFit: "cover" }}
        onError={() => setFalhou(true)}
      />
    );
  }

  const inicial = (nome || "?").trim().charAt(0).toUpperCase();
  return (
    <div
      style={{
        ...base,
        display: "grid",
        placeItems: "center",
        background: "var(--surface-3)",
        color: "var(--text-soft)",
        fontWeight: 700,
        fontSize: 18,
      }}
      aria-hidden="true"
    >
      {inicial}
    </div>
  );
}
