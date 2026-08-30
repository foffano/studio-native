import React, { useState } from "react";
import { changePassword, logout } from "../api.js";

/**
 * Trocar a senha de acesso, e sair.
 *
 * A rota existia desde que a autenticação foi criada e nunca teve interface —
 * quem quisesse trocar a senha precisaria de um `curl`. E sair só era possível
 * apagando o cookie na mão.
 */
export default function PasswordCard() {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirma, setConfirma] = useState("");
  const [msg, setMsg] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function trocar(e) {
    e.preventDefault();
    setErro("");
    setMsg("");
    if (nova !== confirma) {
      setErro("As duas senhas novas não são iguais.");
      return;
    }
    setOcupado(true);
    try {
      await changePassword(atual, nova);
      setAtual("");
      setNova("");
      setConfirma("");
      // A sessão continua válida: trocar a senha não deve derrubar quem está
      // no meio de um trabalho.
      setMsg("Senha alterada. Ela vale no próximo login.");
    } catch (err) {
      setErro(err.message);
    } finally {
      setOcupado(false);
    }
  }

  async function sair() {
    if (!window.confirm("Sair desta sessão?")) return;
    try {
      await logout();
      // O portão de login escuta este evento e reassume a tela.
      window.dispatchEvent(new CustomEvent("studio:sem-sessao"));
    } catch (e) {
      setErro(e.message);
    }
  }

  return (
    <div className="card">
      <h3 className="card__title">Senha de acesso</h3>
      <p className="card__hint">
        É ela que separa este app do resto da internet quando ele está atrás de
        um túnel.
      </p>

      <form onSubmit={trocar} className="form-senha">
        <input
          className="input"
          type="password"
          autoComplete="current-password"
          placeholder="Senha atual"
          value={atual}
          onChange={(e) => setAtual(e.target.value)}
          disabled={ocupado}
        />
        <input
          className="input"
          type="password"
          autoComplete="new-password"
          placeholder="Nova senha (mín. 10 caracteres)"
          value={nova}
          onChange={(e) => setNova(e.target.value)}
          disabled={ocupado}
        />
        <input
          className="input"
          type="password"
          autoComplete="new-password"
          placeholder="Repita a nova senha"
          value={confirma}
          onChange={(e) => setConfirma(e.target.value)}
          disabled={ocupado}
        />
        <div className="form-senha__acoes">
          <button
            className="btn btn--primary"
            disabled={ocupado || !atual || !nova}
          >
            {ocupado ? "Alterando..." : "Alterar senha"}
          </button>
          <button type="button" className="btn btn--ghost" onClick={sair}>
            Sair
          </button>
        </div>
      </form>

      {msg && <p className="form-senha__ok">{msg}</p>}
      {erro && <p className="form-senha__erro">{erro}</p>}
    </div>
  );
}
