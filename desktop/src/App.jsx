import React, { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import GenerateView from "./components/GenerateView.jsx";
import HistoryView from "./components/HistoryView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import { getConfig } from "./api.js";

const THEME_KEY = "studio_native_theme";

const HEADINGS = {
  generate: { eyebrow: "Estúdio", title: "Gerar vídeo" },
  history: { eyebrow: "Estúdio", title: "Histórico" },
  settings: { eyebrow: "Configuração", title: "Ajustes" },
};

export default function App() {
  const [view, setView] = useState("generate");
  const [theme, setTheme] = useState(
    () => localStorage.getItem(THEME_KEY) || "light"
  );
  const [config, setConfig] = useState(null);
  const [reopen, setReopen] = useState(null);
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

  const openHistoryEntry = (entry) => {
    setReopen(entry);
    setView("generate");
  };

  const head = HEADINGS[view];

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
              config={config}
              reopen={reopen}
              onReopened={() => setReopen(null)}
            />
          </>
        )}

        {view === "history" && <HistoryView onOpen={openHistoryEntry} />}

        {view === "settings" && <SettingsView onSaved={refreshConfig} />}
      </main>
    </div>
  );
}
