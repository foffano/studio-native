import React from "react";
import logoUrl from "../assets/logo.png";
import {
  IconVideo,
  IconHistory,
  IconSettings,
  IconSun,
  IconMoon,
} from "./Icons.jsx";

const NAV = [
  { id: "generate", label: "Gerar vídeo", icon: IconVideo },
  { id: "history", label: "Histórico", icon: IconHistory },
];

function updateButtonLabel(status) {
  if (status === "available") return "Baixar atualização";
  if (status === "downloaded") return "Reiniciar e instalar";
  if (status === "checking") return "Verificando...";
  if (status === "downloading") return "Baixando...";
  return "Verificar atualizações";
}

function updateActionFor(status) {
  if (status === "available") return "download";
  if (status === "downloaded") return "install";
  return "check";
}

export default function Sidebar({
  view,
  onNavigate,
  theme,
  onToggleTheme,
  updateState,
  onUpdateAction,
}) {
  const updatesEnabled = !!onUpdateAction;
  const updateStatus = updateState?.status || "idle";
  const updateBusy = updateStatus === "checking" || updateStatus === "downloading";

  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand__logo" src={logoUrl} alt="Studio Native" />
        <div>
          <div className="brand__name">Studio Native</div>
          <div className="brand__sub">Gerador de vídeos IA</div>
        </div>
      </div>

      <nav className="nav">
        <div className="nav__label">Estúdio</div>
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={"nav__item" + (view === item.id ? " active" : "")}
              onClick={() => onNavigate(item.id)}
            >
              <Icon />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="sidebar__spacer" />

      <div className="sidebar__footer">
        {updatesEnabled && (
          <div className="update-card">
            <div className="update-card__title">Atualizações</div>
            <div className="update-card__msg">
              {updateState?.message || "Verifique novas releases no GitHub."}
            </div>
            <button
              className="update-card__btn"
              disabled={updateBusy}
              onClick={() => onUpdateAction(updateActionFor(updateStatus))}
            >
              {updateButtonLabel(updateStatus)}
            </button>
          </div>
        )}
        <button className="nav__item" onClick={onToggleTheme}>
          {theme === "dark" ? <IconSun /> : <IconMoon />}
          {theme === "dark" ? "Tema claro" : "Tema escuro"}
        </button>
        <button
          className={"nav__item" + (view === "settings" ? " active" : "")}
          onClick={() => onNavigate("settings")}
        >
          <IconSettings />
          Ajustes
        </button>
      </div>
    </aside>
  );
}
