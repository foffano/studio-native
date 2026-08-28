import React, { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import GenerateView from "./components/GenerateView.jsx";
import ProducedView from "./components/ProducedView.jsx";
import LibraryView from "./components/LibraryView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import { getConfig, importHistoryToBackend } from "./api.js";
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

const HEADINGS = {
  generate: { eyebrow: "Estúdio", title: "Gerar vídeo" },
  produced: { eyebrow: "Estúdio", title: "Produzidos" },
  library: { eyebrow: "Estúdio", title: "Biblioteca de vídeos" },
  settings: { eyebrow: "Configuração", title: "Ajustes" },
};

export default function App() {
  const [view, setView] = useState("generate");
  const [theme, setTheme] = useState(
    () => localStorage.getItem(THEME_KEY) || "light"
  );
  const [config, setConfig] = useState(null);
  const [activeChatId, setActiveChatId] = useState(null);
  const [activeEntry, setActiveEntry] = useState(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [libraryPick, setLibraryPick] = useState(null);
  const [updateState, setUpdateState] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const refreshConfig = async () => {
    try {
      setConfig(await getConfig());
    } catch (_) {
      setConfig({ api_key_set: false, elevenlabs_available: false });
    }
  };

  useEffect(() => {
    refreshConfig();
    migrateHistoryOnce();
    resumeRunningGenerations();
    return subscribeGeneration(() => setHistoryVersion((v) => v + 1));
  }, []);

  useEffect(() => {
    const updates = window.studioNative?.updates;
    if (!updates) return undefined;
    updates.getState().then(setUpdateState).catch(() => {});
    const unsubscribe = updates.onState(setUpdateState);
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (activeChatId) setActiveEntry(getEntry(activeChatId));
    else setActiveEntry(null);
  }, [activeChatId, historyVersion]);

  const updateAction = async (action) => {
    const updates = window.studioNative?.updates;
    if (!updates) return;
    try {
      if (action === "check") setUpdateState(await updates.check());
      if (action === "download") setUpdateState(await updates.download());
      if (action === "install") await updates.install();
    } catch (e) {
      setUpdateState({
        status: "error",
        message: e.message || "Falha ao processar atualizacao.",
      });
    }
  };

  const handleNewChat = () => {
    setActiveChatId(null);
    setActiveEntry(null);
    setView("generate");
  };

  const handleSelectChat = (entry) => {
    setActiveChatId(entry.id);
    setActiveEntry(getEntry(entry.id) || entry);
    setView("generate");
  };

  const handleGenerationStarted = (jobId, entry) => {
    setActiveChatId(jobId);
    setActiveEntry(entry);
    setView("generate");
    setHistoryVersion((v) => v + 1);
  };

  const handleUseLibrary = (item) => {
    setLibraryPick(item);
    setActiveChatId(null);
    setActiveEntry(null);
    setView("generate");
  };

  const head = HEADINGS[view] || HEADINGS.generate;

  return (
    <div className="app">
      <Sidebar
        view={view}
        onNavigate={setView}
        theme={theme}
        onToggleTheme={() =>
          setTheme((t) => (t === "dark" ? "light" : "dark"))
        }
        updateState={updateState}
        onUpdateAction={updateAction}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
        historyVersion={historyVersion}
      />

      <main className="content">
        <div className="content__head">
          <div>
            <div className="eyebrow">{head.eyebrow}</div>
            <h1 className="title">{head.title}</h1>
          </div>
        </div>

        {view === "generate" && (
          <>
            <GenerateView
              config={config}
              activeEntry={activeEntry}
              isNewSession={!activeChatId}
              libraryPick={libraryPick}
              onLibraryPickConsumed={() => setLibraryPick(null)}
              onGenerationStarted={handleGenerationStarted}
            />
          </>
        )}

        {view === "produced" && <ProducedView />}

        {view === "library" && (
          <LibraryView onUseForGeneration={handleUseLibrary} />
        )}

        {view === "settings" && <SettingsView onSaved={refreshConfig} />}
      </main>
    </div>
  );
}
