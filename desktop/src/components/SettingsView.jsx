import React, { useEffect, useState } from "react";
import { getSettings, saveSettings } from "../api.js";
import { IconCheck } from "./Icons.jsx";
import VoicesManager from "./VoicesManager.jsx";

export default function SettingsView({ onSaved }) {
  const [data, setData] = useState(null);
  const [orModel, setOrModel] = useState("");
  const [elModel, setElModel] = useState("");
  const [maxHeight, setMaxHeight] = useState(1080);
  const [orKey, setOrKey] = useState("");
  const [elKey, setElKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(0);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const s = await getSettings();
      setData(s);
      setOrModel(s.openrouter_model || "");
      setElModel(s.elevenlabs_model || "");
      setMaxHeight(s.max_height || 1080);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  async function save() {
    setSaving(true);
    setError("");
    const payload = {
      openrouter_model: orModel,
      elevenlabs_model: elModel,
      max_height: maxHeight,
    };
    // Só envia chaves se o usuário digitou algo (evita apagar as salvas).
    if (orKey.trim() !== "") payload.openrouter_api_key = orKey.trim();
    if (elKey.trim() !== "") payload.elevenlabs_api_key = elKey.trim();
    try {
      const s = await saveSettings(payload);
      setData(s);
      setOrKey("");
      setElKey("");
      setSavedAt(Date.now());
      onSaved && onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function clearKey(which) {
    setError("");
    try {
      const payload =
        which === "or"
          ? { openrouter_api_key: "" }
          : { elevenlabs_api_key: "" };
      const s = await saveSettings(payload);
      setData(s);
      onSaved && onSaved();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <>
      <div className="content__head">
        <div>
          <div className="eyebrow">Configuração</div>
          <h1 className="title">Ajustes</h1>
        </div>
        {savedAt > 0 && (
          <span className="saved-pill">
            <IconCheck width={15} height={15} /> Salvo
          </span>
        )}
      </div>

      {error && <div className="banner banner--error">Erro: {error}</div>}

      <div className="card">
        <h3 className="card__title">Chaves de API</h3>
        <p className="card__hint">
          As chaves ficam salvas localmente neste computador
          {data?.config_path ? ` (${data.config_path})` : ""} e nunca são
          enviadas para outro lugar além das APIs oficiais.
        </p>

        <div className="field">
          <label className="field__label">OpenRouter API Key</label>
          <input
            className="input"
            type="password"
            placeholder={
              data?.openrouter_key_set
                ? `salva: ${data.openrouter_key_masked} — digite para substituir`
                : "cole sua chave (sk-or-...)"
            }
            value={orKey}
            onChange={(e) => setOrKey(e.target.value)}
          />
          {data?.openrouter_key_set && (
            <div className="field__hint">
              <button
                className="hist-del"
                style={{ padding: "2px 6px" }}
                onClick={() => clearKey("or")}
              >
                Remover chave salva
              </button>
            </div>
          )}
        </div>

        <div className="field">
          <label className="field__label">OpenRouter Model</label>
          <input
            className="input"
            value={orModel}
            placeholder="openai/gpt-4o-mini"
            onChange={(e) => setOrModel(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label">ElevenLabs API Key</label>
          <input
            className="input"
            type="password"
            placeholder={
              data?.elevenlabs_key_set
                ? `salva: ${data.elevenlabs_key_masked} — digite para substituir`
                : "cole sua chave (opcional, para narração)"
            }
            value={elKey}
            onChange={(e) => setElKey(e.target.value)}
          />
          {data?.elevenlabs_key_set && (
            <div className="field__hint">
              <button
                className="hist-del"
                style={{ padding: "2px 6px" }}
                onClick={() => clearKey("el")}
              >
                Remover chave salva
              </button>
            </div>
          )}
        </div>

        <div className="field">
          <label className="field__label">ElevenLabs Model</label>
          <input
            className="input"
            value={elModel}
            placeholder="eleven_multilingual_v2"
            onChange={(e) => setElModel(e.target.value)}
          />
        </div>
      </div>

      <VoicesManager
        voices={data?.voices || []}
        onSaved={() => {
          load();
          onSaved && onSaved();
        }}
      />

      <div className="card">
        <h3 className="card__title">Renderização</h3>
        <div className="field">
          <label className="field__label">
            Altura máxima do vídeo (px):{" "}
            <span className="range-val">{maxHeight}p</span>
          </label>
          <input
            type="range"
            min="480"
            max="2160"
            step="120"
            value={maxHeight}
            onChange={(e) => setMaxHeight(parseInt(e.target.value))}
          />
          <div className="field__hint">
            Vídeos maiores são reduzidos a esta altura na normalização (mantendo
            a proporção). Padrão: 1080p.
          </div>
        </div>
      </div>

      <div className="card">
        <button className="btn btn--primary" disabled={saving} onClick={save}>
          {saving ? "Salvando..." : "Salvar ajustes"}
        </button>
        <span className="muted" style={{ marginLeft: 14 }}>
          As alterações valem imediatamente, sem reiniciar o app.
        </span>
      </div>
    </>
  );
}
