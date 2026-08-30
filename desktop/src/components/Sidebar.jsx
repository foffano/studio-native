import React, { useState } from "react";
import logoUrl from "../assets/logo.png";
import {
  IconSettings,
  IconSun,
  IconMoon,
  IconPlus,
  IconFolder,
  IconHistory,
  IconStar,
  IconClock,
  IconTrash,
  IconVideo,
} from "./Icons.jsx";

/** Item de navegação com ícone, rótulo e contagem opcional. */
function Item({ icone, rotulo, rotuloCurto, principal, contagem, ativo, onClick }) {
  return (
    <button
      className={
        "navitem" +
        (ativo ? " navitem--on" : "") +
        // As entradas "principal" sao as unicas que sobrevivem na barra
        // inferior do celular. Sem elas o rodape ficaria sem navegacao.
        (principal ? " navitem--principal" : "")
      }
      onClick={onClick}
      aria-current={ativo ? "page" : undefined}
    >
      <span className="navitem__ico" aria-hidden="true">{icone}</span>
      <span className="navitem__txt">{rotulo}</span>
      {rotuloCurto && <span className="navitem__curto">{rotuloCurto}</span>}
      {contagem > 0 && <span className="navitem__num">{contagem}</span>}
    </button>
  );
}

/**
 * Navegação do app, no modelo de um gerenciador de mídia.
 *
 * Duas ações no topo (importar, nova pasta), depois as seções da Biblioteca,
 * as de Produzidos, e as pastas — que valem para os dois lados, com a contagem
 * de fontes e saídas de cada uma.
 *
 * O que saiu daqui: a lista de "Histórico" vinda do localStorage. Ela ocupava
 * um terço da barra, nunca mudava, e era uma segunda fonte para a mesma
 * pergunta que Produzidos responde melhor.
 */
export default function Sidebar({
  destino,
  onNavegar,
  onImportar,
  onNovaPasta,
  contagens,
  pastas,
  contagensProduzidos,
  theme,
  onToggleTheme,
}) {
  const [pastasAbertas, setPastasAbertas] = useState(true);

  const em = (area, secao, pastaId) =>
    destino.area === area &&
    (secao === undefined || destino.secao === secao) &&
    (pastaId === undefined || destino.pastaId === pastaId);

  const c = contagens || {};
  const cp = contagensProduzidos || {};

  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand__logo" src={logoUrl} alt="" />
        <div>
          <div className="brand__name">Studio Native</div>
        </div>
      </div>

      <div className="sidebar__acoes">
        <button className="btn btn--primary btn--block" onClick={onImportar}>
          <IconPlus width={16} height={16} /> Importar vídeos
        </button>
        <button className="btn btn--ghost btn--block" onClick={onNovaPasta}>
          <IconFolder width={16} height={16} /> Nova pasta
        </button>
      </div>

      <div className="sidebar__rolagem">
        <div className="nav__label">Biblioteca</div>
        <Item
          icone={<IconVideo />}
          rotulo="Todos os vídeos"
          rotuloCurto="Biblioteca"
          principal
          contagem={c.todos}
          ativo={em("biblioteca", "todos")}
          onClick={() => onNavegar({ area: "biblioteca", secao: "todos" })}
        />
        <Item
          icone={<IconStar />}
          rotulo="Favoritos"
          contagem={c.favoritos}
          ativo={em("biblioteca", "favoritos")}
          onClick={() => onNavegar({ area: "biblioteca", secao: "favoritos" })}
        />
        <Item
          icone={<IconClock />}
          rotulo="Recentes"
          ativo={em("biblioteca", "recentes")}
          onClick={() => onNavegar({ area: "biblioteca", secao: "recentes" })}
        />
        <Item
          icone={<IconTrash />}
          rotulo="Lixeira"
          contagem={c.lixeira}
          ativo={em("biblioteca", "lixeira")}
          onClick={() => onNavegar({ area: "biblioteca", secao: "lixeira" })}
        />

        {/* Uma entrada so, e nao tres.
            "Todos os produzidos" e "Publicados" repetiam o que agora esta no
            painel de cada video-fonte: para ver o que saiu de um video,
            clica-se nele. Uma lista global das saidas nao responde a nenhuma
            pergunta que a Biblioteca ja nao responda melhor.

            "Esperando no TikTok" fica porque e a excecao: e a unica lista cuja
            pergunta atravessa as fontes -- "o que eu preciso terminar de
            postar?" -- e quem a faz nao sabe de qual video veio cada uma.
            Aparece so quando ha algo esperando; uma linha marcando zero seria
            uma tarefa que nao existe. */}
        {cp.awaiting > 0 && (
          <>
            <div className="nav__label">Pendências</div>
            <Item
              icone={<IconHistory />}
              rotulo="Esperando no TikTok"
              rotuloCurto="TikTok"
              principal
              contagem={cp.awaiting}
              ativo={em("produzidos", "aguardando")}
              onClick={() => onNavegar({ area: "produzidos", secao: "aguardando" })}
            />
          </>
        )}

        <button
          className="nav__label nav__label--btn"
          onClick={() => setPastasAbertas((v) => !v)}
          aria-expanded={pastasAbertas}
        >
          Pastas
          <span className="nav__label__seta" aria-hidden="true">
            {pastasAbertas ? "−" : "+"}
          </span>
        </button>

        {pastasAbertas && (
          <>
            {(pastas || []).map((p) => (
              <Item
                key={p.id}
                icone={<IconFolder />}
                rotulo={p.name}
                contagem={(c.por_pasta || {})[p.id]}
                ativo={em("pasta", undefined, p.id)}
                onClick={() => onNavegar({ area: "pasta", pastaId: p.id, secao: "fontes" })}
              />
            ))}
            {(c.por_pasta || {})[""] > 0 && (
              <Item
                icone={<IconFolder />}
                rotulo="Sem pasta"
                contagem={(c.por_pasta || {})[""]}
                ativo={em("pasta", undefined, "")}
                onClick={() => onNavegar({ area: "pasta", pastaId: "", secao: "fontes" })}
              />
            )}
            {(pastas || []).length === 0 && (
              <p className="nav__vazio">
                Nenhuma pasta. Crie uma para organizar fontes e produzidos.
              </p>
            )}
          </>
        )}
      </div>

      <div className="sidebar__footer">
        {/* Nao ha mais "Verificar atualizacoes": aquilo era o electron-updater,
            que baixava um .exe novo. Como servico, atualizar e `git pull` e
            reiniciar -- feito por `tools/atualizar.ps1`, no PC que hospeda. */}
        <button className="navitem" onClick={onToggleTheme}>
          <span className="navitem__ico" aria-hidden="true">
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </span>
          <span className="navitem__txt">
            {theme === "dark" ? "Tema claro" : "Tema escuro"}
          </span>
        </button>
        <button
          className={"navitem" + (destino.area === "ajustes" ? " navitem--on" : "")}
          onClick={() => onNavegar({ area: "ajustes" })}
        >
          <span className="navitem__ico" aria-hidden="true"><IconSettings /></span>
          <span className="navitem__txt">Ajustes</span>
        </button>
      </div>
    </aside>
  );
}
