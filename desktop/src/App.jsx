import React, { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import GenerateView from "./components/GenerateView.jsx";
import LibraryView from "./components/LibraryView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import { getConfig } from "./api.js";

const THEME_KEY = "studio_native_theme";

const HEADINGS = {
  generate: { eyebrow: "Estúdio", title: "Gerar vídeo" },
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
  }, []);

  useEffect(() => {
    const updates = window.studioNative?.updates;
    if (!updates) return undefined;
    updates.getState().then(setUpdateState).catch(() => {});
    const unsubscribe = updates.onState(setUpdateState);
    return unsubscribe;
  }, []);

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
    setActiveEntry(entry);
    setView("generate");
  };

  const handleHistoryChange = (entryId) => {
    setHistoryVersion((v) => v + 1);
    if (entryId) setActiveChatId(entryId);
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
        {view === "generate" && (
          <>
            <div className="content__head">
              <div>
                <div className="eyebrow">{head.eyebrow}</div>
                <h1 className="title">{head.title}</h1>
              </div>
            </div>
            <GenerateView
              key={(activeChatId || "new") + (libraryPick?.id || "")}
              config={config}
              activeEntry={activeEntry}
              libraryPick={libraryPick}
              onLibraryPickConsumed={() => setLibraryPick(null)}
              onHistoryChange={handleHistoryChange}
            />
          </>
        )}

        {view === "library" && (
          <LibraryView onUseForGeneration={handleUseLibrary} />
        )}

        {view === "settings" && <SettingsView onSaved={refreshConfig} />}
      </main>
    </div>
  );
}
