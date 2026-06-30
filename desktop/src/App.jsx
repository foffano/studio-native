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
