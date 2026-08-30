import React, { useEffect, useState } from "react";
import LibraryView from "./LibraryView.jsx";
import ProducedView from "./ProducedView.jsx";
import { apagarPasta, renomearPasta } from "../api.js";

/**
 * Uma pasta, com as duas coisas que ela contém.
 *
 * Pastas valem para os dois lados do app — os vídeos-fonte e os produzidos —
 * então a pasta precisa mostrar os dois. Em abas, e não numa lista só, porque
 * são coisas de natureza diferente: uma é matéria-prima que se escolhe para
 * produzir, a outra é resultado que se publica. Misturá-las numa grade faria o
 * usuário ter que ler cada card para saber com o que está lidando.
 */
export default function FolderView({ pasta, pastas, onMudou, onUseForGeneration, onSair }) {
  const [aba, setAba] = useState("fontes");
  const semPasta = !pasta;

  // Trocar de pasta volta para a primeira aba: a aba escolhida valia para a
  // pasta anterior, e manter "produzidos" ao entrar numa pasta que só tem
  // fontes mostraria uma tela vazia sem motivo aparente.
  useEffect(() => {
    setAba("fontes");
  }, [pasta?.id]);

  async function renomear() {
    const nome = window.prompt("Novo nome da pasta", pasta.name);
    if (!nome || !nome.trim() || nome.trim() === pasta.name) return;
    try {
      await renomearPasta(pasta.id, nome.trim());
      onMudou && onMudou();
    } catch (e) {
      window.alert("Não foi possível renomear: " + e.message);
    }
  }

  async function apagar() {
    if (
      !window.confirm(
        `Apagar a pasta "${pasta.name}"?\n\n` +
          "Os vídeos não são apagados — eles voltam para “Sem pasta”."
      )
    )
      return;
    try {
      await apagarPasta(pasta.id);
      onMudou && onMudou();
      onSair && onSair();
    } catch (e) {
      window.alert("Não foi possível apagar: " + e.message);
    }
  }

  return (
    <>
      <div className="abas">
        <div className="abas__lista" role="tablist">
          <button
            role="tab"
            aria-selected={aba === "fontes"}
            className={"aba" + (aba === "fontes" ? " aba--on" : "")}
            onClick={() => setAba("fontes")}
          >
            Vídeos-fonte
          </button>
          <button
            role="tab"
            aria-selected={aba === "produzidos"}
            className={"aba" + (aba === "produzidos" ? " aba--on" : "")}
            onClick={() => setAba("produzidos")}
          >
            Produzidos
          </button>
        </div>

        {/* "Sem pasta" não é uma pasta de verdade: é o resto. Renomear ou
            apagar não faz sentido lá. */}
        {!semPasta && (
          <div className="abas__acoes">
            <button className="btn btn--ghost btn--xs" onClick={renomear}>
              Renomear
            </button>
            <button className="btn btn--ghost btn--xs" onClick={apagar}>
              Apagar pasta
            </button>
          </div>
        )}
      </div>

      {aba === "fontes" ? (
        <LibraryView
          secao={null}
          pastaId={semPasta ? "" : pasta.id}
          pastas={pastas}
          onMudou={onMudou}
          onUseForGeneration={onUseForGeneration}
        />
      ) : (
        <ProducedView folderId={semPasta ? "" : pasta.id} />
      )}
    </>
  );
}
