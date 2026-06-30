import React, { useEffect, useState } from "react";
import { saveSettings } from "../api.js";
import { IconPlus, IconTrash, IconCheck } from "./Icons.jsx";

const EMPTY = {
  id: "",
  name: "",
  voice_id: "",
  model_id: "",
  stability: 0.5,
  similarity: 0.75,
};

const newId = () =>
  (crypto.randomUUID && crypto.randomUUID()) ||
  "v" + Math.random().toString(36).slice(2);

export default function VoicesManager({ voices, onSaved }) {
  const [list, setList] = useState(voices || []);
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setList(voices || []);
  }, [voices]);

  const resetForm = () => {
    setForm(EMPTY);
    setEditingId(null);
  };

  async function persist(newList) {
    setBusy(true);
    setError("");
    try {
      const res = await saveSettings({ voices: newList });
      setList(res.voices || []);
      onSaved && onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function addOrUpdate() {
    if (!form.name.trim() || !form.voice_id.trim()) {
      setError("Informe um nome/apelido e o Voice ID.");
      return;
    }
    const voice = {
      id: editingId || newId(),
      name: form.name.trim(),
      voice_id: form.voice_id.trim(),
      model_id: form.model_id.trim(),
      stability: form.stability,
      similarity: form.similarity,
    };
    const next = editingId
      ? list.map((v) => (v.id === editingId ? voice : v))
      : [...list, voice];
    persist(next);
    resetForm();
  }

  function edit(v) {
    setEditingId(v.id);
    setForm({
      id: v.id,
      name: v.name || "",
      voice_id: v.voice_id || "",
      model_id: v.model_id || "",
      stability: v.stability ?? 0.5,
      similarity: v.similarity ?? 0.75,
    });
  }

  function remove(id) {
    persist(list.filter((v) => v.id !== id));
    if (editingId === id) resetForm();
  }

  return (
    <div className="card">
      <h3 className="card__title">Vozes (ElevenLabs)</h3>
      <p className="card__hint">
        Cadastre vozes para selecioná-las rapidamente na aba de geração, sem
        digitar o Voice ID toda vez.
      </p>

      {error && <div className="banner banner--error">Erro: {error}</div>}

      {list.length === 0 ? (
        <div className="muted" style={{ marginBottom: 16 }}>
          Nenhuma voz cadastrada ainda.
        </div>
      ) : (
        <div className="voice-list">
          {list.map((v) => (
            <div className="voice-item" key={v.id}>
              <div className="voice-item__info">
                <div className="voice-item__name">{v.name}</div>
                <div className="voice-item__meta">
                  ID: {v.voice_id}
                  {v.model_id ? ` · ${v.model_id}` : ""} · stab{" "}
                  {(v.stability ?? 0.5).toFixed(2)} · sim{" "}
                  {(v.similarity ?? 0.75).toFixed(2)}
                </div>
              </div>
              <div className="voice-item__actions">
                <button className="icon-btn" onClick={() => edit(v)}>
                  Editar
                </button>
                <button
                  className="hist-del"
                  title="Remover"
                  onClick={() => remove(v.id)}
                >
                  <IconTrash width={15} height={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="voice-form">
        <div className="voice-form__title">
          {editingId ? "Editar voz" : "Adicionar voz"}
        </div>
        <div className="grid2">
          <div className="field">
            <label className="field__label">Nome / apelido</label>
            <input
              className="input"
              placeholder="ex.: Narrador BR masculino"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="field__label">Voice ID</label>
            <input
              className="input"
              placeholder="ex.: 21m00Tcm4TlvDq8ikWAM"
              value={form.voice_id}
              onChange={(e) => setForm({ ...form, voice_id: e.target.value })}
            />
          </div>
        </div>
        <div className="field">
          <label className="field__label">
            Modelo TTS (opcional — vazio usa o padrão)
          </label>
          <input
            className="input"
            placeholder="eleven_multilingual_v2"
            value={form.model_id}
            onChange={(e) => setForm({ ...form, model_id: e.target.value })}
          />
        </div>
        <div className="grid2">
          <div className="field">
            <label className="field__label">
              Estabilidade:{" "}
              <span className="range-val">{form.stability.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={form.stability}
              onChange={(e) =>
                setForm({ ...form, stability: parseFloat(e.target.value) })
              }
            />
          </div>
          <div className="field">
            <label className="field__label">
              Similaridade:{" "}
              <span className="range-val">{form.similarity.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={form.similarity}
              onChange={(e) =>
                setForm({ ...form, similarity: parseFloat(e.target.value) })
              }
            />
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn--primary" disabled={busy} onClick={addOrUpdate}>
            {editingId ? (
              <>
                <IconCheck width={16} height={16} /> Salvar voz
              </>
            ) : (
              <>
                <IconPlus width={16} height={16} /> Adicionar voz
              </>
            )}
          </button>
          {editingId && (
            <button className="btn btn--ghost" onClick={resetForm}>
              Cancelar
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
