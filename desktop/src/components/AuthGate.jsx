import React, { useEffect, useState } from "react";
import { getAuthStatus, login, setupPassword } from "../api.js";

/**
 * Porta de entrada: nada do app é montado antes de a sessão existir.
 *
 * É um portão, e não um "esconder a tela": a proteção de verdade está no
 * backend, que recusa as 34 rotas sem sessão. Isto aqui existe para o usuário
 * ver um formulário em vez de uma tela quebrada.
 */
export default function AuthGate({ children }) {
  const [estado, setEstado] = useState(null); // null = carregando
  const [senha, setSenha] = useState("");
  const [confirma, setConfirma] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const conferir = () =>
    getAuthStatus()
      .then(setEstado)
      .catch((e) => {
        setEstado({ senha_configurada: true, autenticado: false });
        setErro("Não foi possível falar com o serviço: " + e.message);
      });

  useEffect(() => {
    conferir();
    // Qualquer 401 em qualquer tela devolve para cá.
    const aoPerderSessao = () =>
      setEstado((e) => (e ? { ...e, autenticado: false } : e));
    window.addEventListener("studio:sem-sessao", aoPerderSessao);
    return () => window.removeEventListener("studio:sem-sessao", aoPerderSessao);
  }, []);

  async function enviar(e) {
    e.preventDefault();
    setErro("");
    setOcupado(true);
    try {
      if (!estado.senha_configurada) {
        if (senha !== confirma) throw new Error("As duas senhas não são iguais.");
        await setupPassword(senha);
      } else {
        await login(senha);
      }
      setSenha("");
      setConfirma("");
      await conferir();
    } catch (err) {
      setErro(err.message);
    } finally {
      setOcupado(false);
    }
  }

  if (!estado) {
    return <div className="auth-screen"><p className="muted">Carregando...</p></div>;
  }

  if (estado.autenticado) return children;

  const primeiroAcesso = !estado.senha_configurada;

  return (
    <div className="auth-screen">
      <form className="auth-box" onSubmit={enviar}>
        <h1 className="auth-box__title">Studio Native</h1>

        {primeiroAcesso ? (
          <p className="auth-box__hint">
            Primeiro acesso. Crie a senha que vai proteger este serviço — é ela
            que separa o seu estúdio do resto da internet. Use uma frase longa,
            não uma palavra.
          </p>
        ) : (
          <p className="auth-box__hint">Entre para continuar.</p>
        )}

        <input
          className="input"
          type="password"
          autoFocus
          autoComplete={primeiroAcesso ? "new-password" : "current-password"}
          placeholder={primeiroAcesso ? "Nova senha (mín. 10 caracteres)" : "Senha"}
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          disabled={ocupado}
        />

        {primeiroAcesso && (
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            placeholder="Repita a senha"
            value={confirma}
            onChange={(e) => setConfirma(e.target.value)}
            disabled={ocupado}
            style={{ marginTop: 10 }}
          />
        )}

        <button
          className="btn btn--primary btn--block"
          style={{ marginTop: 14 }}
          disabled={ocupado || !senha}
        >
          {ocupado ? "Aguarde..." : primeiroAcesso ? "Criar senha e entrar" : "Entrar"}
        </button>

        {erro && <p className="auth-box__erro">{erro}</p>}
      </form>
    </div>
  );
}
