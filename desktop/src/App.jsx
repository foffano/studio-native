import React, { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import GenerateView from "./components/GenerateView.jsx";
import FolderView from "./components/FolderView.jsx";
import ProducedView from "./components/ProducedView.jsx";
import LibraryView from "./components/LibraryView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import { criarPasta, getConfig, getLibrary, importHistoryToBackend } from "./api.js";
import { getEntry, loadHistory } from "./lib/history.js";
import {
  subscribeGeneration,
  resumeRunningGenerations,
} from "./lib/generationManager.js";

const THEME_KEY = "studio_native_theme";
const MIGRATED_KEY = "studio_native_history_migrated_v1";

/** Manda para o backend o histórico que vivia só no localStorage.
 *
 * Antes do catálogo de produção, o backend não sabia quais vídeos ele mesmo
 * tinha gerado. Isso roda uma vez por instalação; o endpoint é idempotente e
 * ignora entradas cujo arquivo já não existe.
 */
async function migrateHistoryOnce() {
  if (localStorage.getItem(MIGRATED_KEY)) return;
  const entries = loadHistory().filter((e) => (e.results || []).length > 0);
  if (!entries.length) {
    localStorage.setItem(MIGRATED_KEY, "1");
    return;
  }
  try {
    await importHistoryToBackend(entries);
    localStorage.setItem(MIGRATED_KEY, "1");
  } catch (_) {
    // Backend ainda subindo: tenta de novo na próxima abertura.
  }
}

export default function App() {
  // Um destino, e nao uma string de tela: area diz onde, secao diz o recorte, e
  // pastaId a pasta aberta. Com "todos os videos", "favoritos", "lixeira" e uma
  // pasta qualquer sendo todas a mesma tela com filtros diferentes, uma string
  // so nao descreve para onde o usuario foi.
  const [destino, setDestino] = useState({ area: "biblioteca", secao: "todos" });

  // Dados que a barra lateral mostra: contagens e pastas. Vivem aqui porque a
  // barra e a Biblioteca precisam dos mesmos numeros, e busca-los duas vezes
  // deixaria os dois lados discordando por alguns segundos.
  const [navDados, setNavDados] = useState({ contagens: {}, pastas: [], metrics: {} });
  const [importarPedido, setImportarPedido] = useState(0);
  const [theme, setTheme] = useState(
    () => localStorage.getItem(THEME_KEY) || "light"
  );
  const [config, setConfig] = useState(null);
  const [activeChatId, setActiveChatId] = useState(null);
  const [activeEntry, setActiveEntry] = useState(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [libraryPick, setLibraryPick] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const recarregarNav = async () => {
    try {
      const d = await getLibrary();
      setNavDados({
        contagens: d.contagens || {},
        pastas: d.pastas || [],
        metrics: d.metrics || {},
      });
    } catch (_) {
      /* barra lateral sem numeros e melhor que tela de erro */
    }
  };

  const refreshConfig = async () => {
    try {
      setConfig(await getConfig());
    } catch (_) {
      setConfig({ api_key_set: false, elevenlabs_available: false });
    }
  };

  useEffect(() => {
    recarregarNav();
  }, [destino.area, destino.secao, destino.pastaId]);

  useEffect(() => {
    refreshConfig();
    migrateHistoryOnce();
    resumeRunningGenerations();
    return subscribeGeneration(() => setHistoryVersion((v) => v + 1));
  }, []);

  useEffect(() => {
    if (activeChatId) setActiveEntry(getEntry(activeChatId));
    else setActiveEntry(null);
  }, [activeChatId, historyVersion]);


  const handleGenerationStarted = (jobId, entry) => {
    setActiveChatId(jobId);
    setActiveEntry(entry);
    setDestino({ area: "gerar" });
    setHistoryVersion((v) => v + 1);
  };

  const handleUseLibrary = (item) => {
    setLibraryPick(item);
    setActiveChatId(null);
    setActiveEntry(null);
    setDestino({ area: "gerar" });
  };

  const novaPasta = async () => {
    const nome = window.prompt("Nome da pasta");
    if (!nome || !nome.trim()) return;
    try {
      const pasta = await criarPasta(nome.trim());
      await recarregarNav();
      setDestino({ area: "pasta", pastaId: pasta.id, secao: "fontes" });
    } catch (e) {
      window.alert("Não foi possível criar a pasta: " + e.message);
    }
  };

  // Importar leva para a Biblioteca e pede a ela que abra a area de upload.
  // O contador serve de sinal: incrementar dispara o efeito mesmo quando ja
  // estamos na tela.
  const importar = () => {
    setDestino({ area: "biblioteca", secao: "todos" });
    setImportarPedido((n) => n + 1);
  };

  // Titulo derivado do destino. Antes era um mapa fixo por tela; com secoes e
  // pastas, o titulo precisa dizer *onde* voce esta -- "Favoritos" e "Receitas"
  // sao lugares diferentes dentro da mesma tela.
  const pastaAtual = (navDados.pastas || []).find((p) => p.id === destino.pastaId);
  const TITULOS = {
    biblioteca: {
      todos: "Todos os vídeos",
      favoritos: "Favoritos",
      recentes: "Recentes",
      lixeira: "Lixeira",
    },
    produzidos: {
      todos: "Produzidos",
      aguardando: "Esperando no TikTok",
      publicados: "Publicados",
    },
  };
  const titulo =
    destino.area === "pasta"
      ? pastaAtual?.name || "Sem pasta"
      : destino.area === "ajustes"
      ? "Ajustes"
      : destino.area === "gerar"
      ? "Produzir vídeo"
      : (TITULOS[destino.area] || {})[destino.secao] || "Studio Native";

  return (
    <div className="app">
      <Sidebar
        destino={destino}
        onNavegar={setDestino}
        onImportar={importar}
        onNovaPasta={novaPasta}
        contagens={navDados.contagens}
        pastas={navDados.pastas}
        contagensProduzidos={navDados.metrics}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      />

      <main className="content">
        <div className="content__head">
          <h1 className="title">{titulo}</h1>
        </div>

        {destino.area === "gerar" && (
          <GenerateView
            onBackToLibrary={() => setDestino({ area: "biblioteca", secao: "todos" })}
            config={config}
            activeEntry={activeEntry}
            isNewSession={!activeChatId}
            libraryPick={libraryPick}
            onLibraryPickConsumed={() => setLibraryPick(null)}
            onGenerationStarted={handleGenerationStarted}
          />
        )}

        {destino.area === "produzidos" && <ProducedView secao={destino.secao} />}

        {destino.area === "biblioteca" && (
          <LibraryView
            secao={destino.secao}
            pastas={navDados.pastas}
            importarPedido={importarPedido}
            onMudou={recarregarNav}
            onUseForGeneration={handleUseLibrary}
            onAbrirPasta={(id) =>
              setDestino({ area: "pasta", pastaId: id, secao: "fontes" })
            }
          />
        )}

        {destino.area === "pasta" && (
          <FolderView
            pasta={pastaAtual}
            pastas={navDados.pastas}
            onMudou={recarregarNav}
            onUseForGeneration={handleUseLibrary}
            onSair={() => setDestino({ area: "biblioteca", secao: "todos" })}
          />
        )}

        {destino.area === "ajustes" && <SettingsView onSaved={refreshConfig} />}
      </main>
    </div>
  );
}
