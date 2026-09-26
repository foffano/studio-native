import React, { useState } from "react";
import { shopAvatarUrl } from "../api.js";

/**
 * As contas vinculadas à loja (baixadas da Central junto com os produtos),
 * para escolher com um toque em vez de digitar o @.
 */
const PAPEL = { 1: "Oficial", 2: "Marketing" };

export function AvatarConta({ conta, tamanho = 32 }) {
  const [falhou, setFalhou] = useState(false);
  const estilo = { width: tamanho, height: tamanho };
  if (!conta.avatar || falhou) {
    return (
      <span className="conta-avatar conta-avatar--vazio" style={estilo} aria-hidden="true">
        {(conta.nickname || conta.handle || "?").charAt(0).toUpperCase()}
      </span>
    );
  }
  return (
    <img className="conta-avatar" style={estilo} src={shopAvatarUrl(conta.handle)} alt="" onError={() => setFalhou(true)} />
  );
}

export default function AccountPicker({ contas, value, onChange }) {
  return (
    <div className="contas" role="radiogroup" aria-label="Conta que publica">
      {contas.map((c) => (
        <button
          type="button"
          role="radio"
          aria-checked={value === c.handle}
          key={c.handle}
          disabled={c.eligible === false}
          className={"conta" + (value === c.handle ? " is-on" : "")}
          onClick={() => onChange(c.handle)}
          title={c.eligible === false ? "O TikTok não deixa esta conta publicar agora" : ""}
        >
          <AvatarConta conta={c} />
          <span className="conta__texto">
            <span className="conta__handle">@{c.handle}</span>
            <span className="conta__meta">
              {[c.nickname, PAPEL[c.role]].filter(Boolean).join(" · ") || "conta vinculada"}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
