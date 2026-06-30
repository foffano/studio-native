import React, { useEffect, useState } from "react";
import { loadHistory, deleteEntry, clearHistory } from "../lib/history.js";
import { IconTrash } from "./Icons.jsx";

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString("pt-BR");
  } catch (_) {
    return iso;
  }
}

export default function HistoryView({ onOpen }) {
  const [list, setList] = useState([]);

  useEffect(() => {
    setList(loadHistory());
  }, []);

  const del = (e, id) => {
    e.stopPropagation();
    setList(deleteEntry(id));
  };
  const clearAll = () => {
    if (confirm("Apagar todo o histórico?")) setList(clearHistory());
  };

  return (
    <>
      <div className="content__head">
        <div>
          <div className="eyebrow">Estúdio</div>
          <h1 className="title">Histórico</h1>
        </div>
        {list.length > 0 && (
          <button className="icon-btn" onClick={clearAll}>
            <IconTrash width={16} height={16} /> Limpar tudo
          </button>
        )}
      </div>

      {list.length === 0 ? (
        <div className="card">
          <div className="empty">
            Nenhuma geração ainda. Crie vídeos na aba <b>Gerar vídeo</b> e eles
            aparecerão aqui.
          </div>
        </div>
      ) : (
        <div className="hist-list">
          {list.map((entry) => {
            const m = entry.meta || {};
            return (
              <div
                className="hist-card"
                key={entry.id}
                onClick={() => onOpen(entry)}
              >
                <div className="hist-card__top">
                  <span className="hist-card__date">{fmtDate(entry.date)}</span>
                  <button
                    className="hist-del"
                    title="Apagar"
                    onClick={(e) => del(e, entry.id)}
                  >
                    <IconTrash width={15} height={15} />
                  </button>
                </div>
                <div className="hist-card__name">
                  {m.sourceName || "vídeo"}
                </div>
                <div className="hist-card__meta">
                  {(entry.results || []).length}{" "}
                  {(entry.results || []).length === 1 ? "vídeo" : "vídeos"}
                  {m.audioEnabled ? " · com narração" : ""}
                  {m.theme ? ` · ${m.theme}` : ""}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
