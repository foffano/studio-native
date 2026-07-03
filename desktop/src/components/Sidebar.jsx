import React, { useEffect, useState } from "react";
import logoUrl from "../assets/logo.png";
import {
  loadHistory,
  deleteEntry,
  getEntryTitle,
  formatHistoryDate,
} from "../lib/history.js";
import {
  IconSettings,
  IconSun,
  IconMoon,
  IconPlus,
  IconTrash,
  IconFolder,
  IconVideo,
} from "./Icons.jsx";

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
  activeChatId,
  onSelectChat,
  onNewChat,
  historyVersion,
}) {
  const [chats, setChats] = useState([]);

  useEffect(() => {
    setChats(loadHistory());
  }, [historyVersion]);

  const updatesEnabled = !!onUpdateAction;
  const updateStatus = updateState?.status || "idle";
  const updateBusy =
    updateStatus === "checking" || updateStatus === "downloading";

  const handleDelete = (e, id) => {
    e.stopPropagation();
    if (!confirm("Apagar esta geração do histórico?")) return;
    setChats(deleteEntry(id));
    if (activeChatId === id) onNewChat();
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand__logo" src={logoUrl} alt="Studio Native" />
        <div>
          <div className="brand__name">Studio Native</div>
          <div className="brand__sub">Gerador de vídeos IA</div>
        </div>
      </div>

      <nav className="nav nav--main">
        <button
          className={"nav__item" + (view === "generate" ? " active" : "")}
          onClick={() => onNavigate("generate")}
        >
          <IconVideo />
          Gerar vídeo
        </button>
        <button
          className={"nav__item" + (view === "library" ? " active" : "")}
          onClick={() => onNavigate("library")}
        >
          <IconFolder />
          Biblioteca
        </button>
      </nav>

      <div className="nav__label">Histórico</div>

      <button
        className={
          "chat-new" + (view === "generate" && !activeChatId ? " active" : "")
        }
        onClick={onNewChat}
      >
        <IconPlus width={16} height={16} />
        Nova geração
      </button>

      <div className="chat-list">
        {chats.length === 0 ? (
          <div className="chat-list__empty">Nenhuma geração ainda</div>
        ) : (
          chats.map((entry) => (
            <button
              key={entry.id}
              className={
                "chat-item" +
                (activeChatId === entry.id && view === "generate"
                  ? " active"
                  : "") +
                (entry.status === "running" ? " chat-item--running" : "")
              }
              onClick={() => onSelectChat(entry)}
              title={getEntryTitle(entry)}
            >
              <span className="chat-item__title">
                {entry.status === "running" && (
                  <span className="chat-item__spin">
                    <span className="spinner spinner--sm" />
                  </span>
                )}
                {getEntryTitle(entry)}
              </span>
              <span className="chat-item__meta">
                <span className="chat-item__date">
                  {formatHistoryDate(entry.date)}
                </span>
                <span
                  className="chat-item__del"
                  role="button"
                  tabIndex={-1}
                  title="Apagar"
                  onClick={(e) => handleDelete(e, entry.id)}
                >
                  <IconTrash width={13} height={13} />
                </span>
              </span>
            </button>
          ))
        )}
      </div>

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
