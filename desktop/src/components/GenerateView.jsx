import React, { useEffect, useRef, useState } from "react";
import {
  getLibrary,
  libraryVideoUrl,
  outputUrl,
  updateOutput,
  regenerateCaption,
} from "../api.js";
import { beginGeneration } from "../lib/generationManager.js";
import HeightPicker from "./HeightPicker.jsx";
import Swatches from "./Swatches.jsx";
import {
  IconUpload,
  IconDownload,
  IconMic,
  IconPlus,
  IconMinus,
  IconCheck,
  IconFolder,
  IconRefresh,
} from "./Icons.jsx";

const MAX_HASHTAGS = 5;

const DEFAULTS = {
  theme: "",
  num: 1,
  vertical: 0.5,
  color: "#ffffff",
  strokeColor: "#000000",
  fontSize: 40,
  strokeWidth: 5,
  lineSpacing: 0.95,
  fps: 30,
};

const STAGES = [
  { key: "queued", label: "Fila" },
  { key: "normalizing", label: "Normalizar" },
  { key: "generating_text", label: "Frases" },
  { key: "tts", label: "Voz" },
  { key: "rendering", label: "Renderizar" },
  { key: "done", label: "Pronto" },
];

const STAGE_ORDER = STAGES.map((s) => s.key);

function stageIndex(status) {
  const i = STAGE_ORDER.indexOf(status);
  return i >= 0 ? i : 0;
}

function fmtDur(sec) {
  if (!sec) return "—";
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

function metaChips(meta) {
  if (!meta) return [];
  const chips = [];
  if (meta.fromLibrary) chips.push("Da biblioteca");
  if (meta.audioEnabled) chips.push("Narração (ElevenLabs)");
  if (meta.theme) chips.push("Tema: " + meta.theme);
  if (meta.audioEnabled && meta.audioTheme)
    chips.push("Narração: " + meta.audioTheme);
  chips.push("Altura: " + Math.round((meta.vertical ?? 0.5) * 100) + "%");
  chips.push("Fonte: " + meta.fontSize);
  return chips;
}

export default function GenerateView({
  config,
  activeEntry,
  isNewSession,
  libraryPick,
  onLibraryPickConsumed,
  onGenerationStarted,
}) {
  if (!isNewSession && activeEntry) {
    return <GenerationSession entry={activeEntry} config={config} />;
  }

  return (
    <GenerationForm
      config={config}
      libraryPick={libraryPick}
      onLibraryPickConsumed={onLibraryPickConsumed}
      onGenerationStarted={onGenerationStarted}
    />
  );
}

function GenerationSession({ entry }) {
  const resultsRef = useRef(null);
  const prevCount = useRef(entry.results?.length || 0);
  const meta = entry.meta || {};
  const busy = entry.status === "running";
  const error = entry.status === "error" ? entry.error : "";
  const results = entry.results || [];
  const sourceMode = meta.fromLibrary ? "library" : "upload";
  const audioEnabled = !!meta.audioEnabled;

  useEffect(() => {
    if (results.length > prevCount.current && resultsRef.current) {
      resultsRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    prevCount.current = results.length;
  }, [results.length]);

  const currentStage = stageIndex(entry.jobStatus || "");
  const showStages =
    busy || (entry.jobStatus && entry.status !== "error");

  return (
    <>
      {error && <div className="banner banner--error">Erro: {error}</div>}

      <div className="session-head">
        <span className="filechip">🎬 {meta.sourceName || "Geração"}</span>
        {busy && (
          <span className="results-live-badge">
            <span className="spinner spinner--sm" /> em andamento
          </span>
        )}
      </div>

      {showStages && (
        <div className={"gen-stages" + (busy ? " gen-stages--live" : "")}>
          {STAGES.filter((s) => {
            if (s.key === "tts" && !audioEnabled) return false;
            if (s.key === "normalizing" && sourceMode === "library") return false;
            return true;
          }).map((s, i) => {
            const done = i < currentStage;
            const active = i === currentStage && busy;
            return (
              <div
                key={s.key}
                className={
                  "gen-stage" +
                  (done ? " done" : "") +
                  (active ? " active" : "")
                }
              >
                <span className="gen-stage__dot">
                  {done ? <IconCheck width={12} height={12} /> : i + 1}
                </span>
                <span className="gen-stage__label">{s.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {busy && (
        <div className="card progress progress--live" style={{ marginBottom: 18 }}>
          <div className="progress__msg">
            <span className="spinner" />
            {entry.statusMsg || "Gerando..."}
          </div>
          <div className="progress__bar">
            <div
              className="progress__fill"
              style={{ width: (entry.progress || 0) + "%" }}
            />
          </div>
          <div className="progress__pct">{Math.round(entry.progress || 0)}%</div>
        </div>
      )}

      {results.length > 0 && (
        <div className="card results-panel" ref={resultsRef}>
          <h3 className="card__title">
            Resultados · {results.length}{" "}
            {results.length === 1 ? "vídeo" : "vídeos"}
            {busy && (
              <span className="results-live-badge">
                <span className="spinner spinner--sm" /> ao vivo
              </span>
            )}
          </h3>
          <div className="chips">
            {metaChips(meta).map((c, i) => (
              <span className="chip" key={i}>
                {c}
              </span>
            ))}
          </div>
          <div className="results">
            {results.map((r, i) => (
              <ResultCard key={r.file || i} r={r} index={i} isNew={busy} />
            ))}
          </div>
        </div>
      )}

      {!busy && results.length === 0 && entry.status === "done" && (
        <div className="card">
          <div className="empty">Nenhum resultado nesta geração.</div>
        </div>
      )}
    </>
  );
}

function GenerationForm({
  config,
  libraryPick,
  onLibraryPickConsumed,
  onGenerationStarted,
}) {
  const [sourceMode, setSourceMode] = useState("library");
  const [file, setFile] = useState(null);
  const [libraryItem, setLibraryItem] = useState(null);
  const [libraryOptions, setLibraryOptions] = useState([]);
  const [drag, setDrag] = useState(false);
  const [opts, setOpts] = useState(DEFAULTS);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [voiceSel, setVoiceSel] = useState("");
  const [audioTheme, setAudioTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const voices = config?.voices || [];
  const set = (patch) => setOpts((o) => ({ ...o, ...patch }));

  useEffect(() => {
    if (voices.length && !voices.some((v) => v.id === voiceSel)) {
      setVoiceSel(voices[0].id);
    }
  }, [config]);

  useEffect(() => {
    if (libraryPick && libraryPick.status === "ready") {
      setSourceMode("library");
      setLibraryItem(libraryPick);
      setFile(null);
      onLibraryPickConsumed && onLibraryPickConsumed();
    }
  }, [libraryPick]);

  useEffect(() => {
    getLibrary()
      .then((data) => {
        const ready = (data.items || []).filter((i) => i.status === "ready");
        setLibraryOptions(ready);
        if (sourceMode === "library" && !libraryItem && ready.length > 0) {
          setLibraryItem(ready[0]);
        }
      })
      .catch(() => {});
  }, [sourceMode]);

  const onFiles = (files) => {
    if (files && files.length) {
      setFile(files[0]);
      setSourceMode("upload");
      setLibraryItem(null);
    }
  };

  const hasSource = sourceMode === "library" ? !!libraryItem : !!file;
  const clampNum = (v) => Math.max(1, Math.min(10, parseInt(v) || 1));

  async function start() {
    setError("");
    if (!hasSource) {
      setError(
        sourceMode === "library"
          ? "Selecione um vídeo da biblioteca."
          : "Selecione um vídeo primeiro."
      );
      return;
    }

    let resolvedVoice = null;
    if (audioEnabled) {
      if (!config?.elevenlabs_available) {
        setError("ELEVENLABS_API_KEY não configurada. Configure em Ajustes.");
        return;
      }
      if (voices.length > 0) {
        const v = voices.find((x) => x.id === voiceSel);
        if (!v) {
          setError("Selecione uma voz da biblioteca (ou cadastre em Ajustes).");
          return;
        }
        resolvedVoice = {
          id: v.id,
          voice_id: v.voice_id,
          name: v.name,
          model_id: v.model_id || "",
          stability: v.stability ?? 0.5,
          similarity: v.similarity ?? 0.75,
        };
      } else {
        setError("Cadastre uma voz em Ajustes > Vozes antes de gerar áudio.");
        return;
      }
    }

    const sourceName =
      sourceMode === "library" ? libraryItem.name : file.name;

    const meta = {
      sourceName,
      libraryId: sourceMode === "library" ? libraryItem.id : "",
      fromLibrary: sourceMode === "library",
      theme: opts.theme.trim(),
      vertical: opts.vertical,
      num: clampNum(opts.num),
      fontSize: opts.fontSize,
      strokeWidth: opts.strokeWidth,
      lineSpacing: opts.lineSpacing,
      color: opts.color,
      strokeColor: opts.strokeColor,
      fps: opts.fps,
      audioEnabled,
      audioTheme: audioTheme.trim(),
      voiceProfileId: resolvedVoice ? resolvedVoice.id : "",
      voiceId: resolvedVoice ? resolvedVoice.voice_id : "",
      voiceName: resolvedVoice ? resolvedVoice.name : "",
      audioModel: resolvedVoice ? resolvedVoice.model_id : "",
    };

    const fd = new FormData();
    if (sourceMode === "library") {
      fd.append("library_id", libraryItem.id);
    } else {
      fd.append("video", file);
    }
    fd.append("theme", meta.theme);
    fd.append("num_variations", String(meta.num));
    fd.append("font_size", String(meta.fontSize));
    fd.append("color", meta.color);
    fd.append("stroke_color", meta.strokeColor);
    fd.append("stroke_width", String(meta.strokeWidth));
    fd.append("vertical", String(meta.vertical));
    fd.append("fps", String(meta.fps));
    fd.append("line_spacing", String(meta.lineSpacing));
    if (audioEnabled && resolvedVoice) {
      fd.append("audio_enabled", "1");
      fd.append("voice_profile_id", resolvedVoice.id);
      fd.append("voice_id", resolvedVoice.voice_id);
      fd.append("audio_theme", meta.audioTheme);
      fd.append("audio_model_id", resolvedVoice.model_id);
      fd.append("stability", String(resolvedVoice.stability));
      fd.append("similarity", String(resolvedVoice.similarity));
    }

    setBusy(true);
    try {
      const { job_id, entry } = await beginGeneration(fd, meta);
      onGenerationStarted && onGenerationStarted(job_id, entry);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {!config?.api_key_set && (
        <div className="banner banner--warn">
          OPENROUTER_API_KEY não configurada. Vá em <b>Ajustes</b> para inserir
          sua chave e habilitar a geração de frases.
        </div>
      )}
      {error && <div className="banner banner--error">Erro: {error}</div>}

      <div className="grid grid--2">
        <div>
          <div className="card">
            <h3 className="card__title">
              <span className="dot">
                <IconUpload width={18} height={18} />
              </span>
              Vídeo de origem
            </h3>
            <p className="card__hint">
              Escolha um vídeo da biblioteca (com miniatura) ou envie um arquivo
              novo.
            </p>

            <div className="source-tabs">
              <button
                type="button"
                className={"source-tab" + (sourceMode === "library" ? " active" : "")}
                disabled={busy}
                onClick={() => setSourceMode("library")}
              >
                <IconFolder width={16} height={16} /> Biblioteca
              </button>
              <button
                type="button"
                className={"source-tab" + (sourceMode === "upload" ? " active" : "")}
                disabled={busy}
                onClick={() => setSourceMode("upload")}
              >
                <IconUpload width={16} height={16} /> Upload novo
              </button>
            </div>

            {sourceMode === "library" ? (
              <div className="lib-picker">
                {libraryOptions.length === 0 ? (
                  <div className="banner banner--warn" style={{ margin: 0 }}>
                    Nenhum vídeo pronto na biblioteca. Adicione em{" "}
                    <b>Biblioteca</b>.
                  </div>
                ) : (
                  <div className="lib-source-list">
                    {libraryOptions.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={
                          "lib-source-item" +
                          (libraryItem?.id === item.id ? " active" : "")
                        }
                        disabled={busy}
                        onClick={() => setLibraryItem(item)}
                      >
                        <div className="lib-source-item__thumb">
                          {item.file ? (
                            <video
                              src={libraryVideoUrl(item.file)}
                              muted
                              preload="metadata"
                            />
                          ) : null}
                        </div>
                        <div className="lib-source-item__info">
                          <div className="lib-source-item__name">{item.name}</div>
                          <div className="lib-source-item__meta">
                            {fmtDur(item.duration_sec)}
                            {item.generation_count > 0 &&
                              ` · ${item.generation_count} sessões · ${item.total_outputs} vídeos`}
                          </div>
                          {(item.tags || []).length > 0 && (
                            <div className="lib-source-item__tags">
                              {item.tags.slice(0, 3).map((t) => (
                                <span className="chip" key={t}>
                                  {t}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <>
                <label
                  className={
                    "drop" + (drag ? " drag" : "") + (file ? " has-file" : "")
                  }
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    onFiles(e.dataTransfer.files);
                  }}
                >
                  <div className="drop__icon">
                    <IconUpload width={26} height={26} />
                  </div>
                  <div className="drop__title">Solte o vídeo aqui</div>
                  <input
                    type="file"
                    accept="video/*"
                    hidden
                    disabled={busy}
                    onChange={(e) => onFiles(e.target.files)}
                  />
                </label>
                {file && <div className="filechip">🎬 {file.name}</div>}
              </>
            )}

            <div className="field" style={{ marginTop: 18 }}>
              <label className="field__label">Tema / contexto (opcional)</label>
              <textarea
                className="textarea"
                placeholder="Ex.: promoção relâmpago de tênis, humor..."
                value={opts.theme}
                onChange={(e) => set({ theme: e.target.value })}
                disabled={busy}
              />
            </div>

            <div className="grid2">
              <div className="field">
                <label className="field__label">Número de variações</label>
                <div className="stepper">
                  <button
                    disabled={busy}
                    onClick={() => set({ num: clampNum(opts.num - 1) })}
                  >
                    <IconMinus width={16} height={16} />
                  </button>
                  <input
                    value={opts.num}
                    disabled={busy}
                    onChange={(e) => set({ num: e.target.value })}
                    onBlur={(e) => set({ num: clampNum(e.target.value) })}
                  />
                  <button
                    disabled={busy}
                    onClick={() => set({ num: clampNum(opts.num + 1) })}
                  >
                    <IconPlus width={16} height={16} />
                  </button>
                </div>
              </div>
              <div className="field">
                <label className="field__label">Altura da frase</label>
                <HeightPicker
                  value={opts.vertical}
                  onChange={(v) => set({ vertical: v })}
                />
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="card__title">
              <span className="dot">
                <IconMic width={18} height={18} />
              </span>
              Narração (ElevenLabs)
            </h3>
            <label className="toggle">
              <input
                type="checkbox"
                checked={audioEnabled}
                disabled={busy}
                onChange={(e) => setAudioEnabled(e.target.checked)}
              />
              <span className="toggle__track" />
              <span>Gerar áudio (narração por voz)</span>
            </label>
            {audioEnabled && voices.length > 0 && (
              <div className="field" style={{ marginTop: 14 }}>
                <label className="field__label">Voz</label>
                <select
                  className="select"
                  value={voiceSel}
                  disabled={busy}
                  onChange={(e) => setVoiceSel(e.target.value)}
                >
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {audioEnabled && (
              <div className="field">
                <label className="field__label">Tema da narração (opcional)</label>
                <input
                  className="input"
                  value={audioTheme}
                  disabled={busy}
                  onChange={(e) => setAudioTheme(e.target.value)}
                />
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h3 className="card__title">Estilo do texto</h3>
            <div className="grid2">
              <div className="field">
                <label className="field__label">Cor do texto</label>
                <Swatches value={opts.color} onChange={(c) => set({ color: c })} />
              </div>
              <div className="field">
                <label className="field__label">Cor do contorno</label>
                <Swatches
                  value={opts.strokeColor}
                  onChange={(c) => set({ strokeColor: c })}
                />
              </div>
            </div>
            <div className="grid2">
              <div className="field">
                <label className="field__label">Tamanho da fonte</label>
                <input
                  className="input"
                  type="number"
                  value={opts.fontSize}
                  disabled={busy}
                  onChange={(e) =>
                    set({ fontSize: parseInt(e.target.value) || 40 })
                  }
                />
              </div>
              <div className="field">
                <label className="field__label">Espessura do contorno</label>
                <input
                  className="input"
                  type="number"
                  value={opts.strokeWidth}
                  disabled={busy}
                  onChange={(e) =>
                    set({ strokeWidth: parseInt(e.target.value) || 0 })
                  }
                />
              </div>
            </div>
            <div className="grid2">
              <div className="field">
                <label className="field__label">FPS</label>
                <input
                  className="input"
                  type="number"
                  value={opts.fps}
                  disabled={busy}
                  onChange={(e) => set({ fps: parseInt(e.target.value) || 30 })}
                />
              </div>
              <div className="field">
                <label className="field__label">
                  Entrelinha:{" "}
                  <span className="range-val">
                    {Number(opts.lineSpacing).toFixed(2)}x
                  </span>
                </label>
                <input
                  type="range"
                  min="0.8"
                  max="2"
                  step="0.05"
                  value={opts.lineSpacing}
                  disabled={busy}
                  onChange={(e) =>
                    set({ lineSpacing: parseFloat(e.target.value) })
                  }
                />
              </div>
            </div>
          </div>

          <div className={"card" + (busy ? " card--generating" : "")}>
            <button
              className={"btn btn--primary btn--block" + (busy ? " btn--pulse" : "")}
              disabled={busy}
              onClick={start}
            >
              {busy ? "Iniciando..." : "Gerar vídeos"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function ResultCard({ r, index, isNew }) {
  const [broken, setBroken] = useState(false);
  const url = outputUrl(r.file);
  return (
    <div
      className={"rcard" + (isNew ? " rcard--enter" : "")}
      style={{ animationDelay: `${index * 0.12}s` }}
    >
      {broken ? (
        <div className="rcard__unavail">
          Vídeo indisponível (arquivo removido do servidor).
        </div>
      ) : (
        <video
          src={url}
          controls
          preload="metadata"
          onError={() => setBroken(true)}
        />
      )}
      <div className="rcard__body">
        <p className="rcard__phrase">{r.phrase}</p>
        {r.speech && <p className="rcard__speech">🎙 {r.speech}</p>}
        <CaptionEditor result={r} />
        <a className="btn btn--ghost btn--block" href={url} download={r.file}>
          <IconDownload width={16} height={16} /> Baixar
        </a>
      </div>
    </div>
  );
}

/** Legenda do post + hashtags, editáveis e salvas no catálogo do backend. */
function CaptionEditor({ result }) {
  const [caption, setCaption] = useState(result.caption || "");
  const [tags, setTags] = useState(result.hashtags || []);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState("idle"); // idle | saving | saved | error
  const [error, setError] = useState("");
  const timerRef = useRef(null);
  const id = result.id;

  // O card é remontado quando a geração avança; mantém o texto em dia sem
  // sobrescrever o que o usuário está digitando.
  useEffect(() => {
    if (state === "idle") {
      setCaption(result.caption || "");
      setTags(result.hashtags || []);
    }
  }, [result.caption, result.hashtags]);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const persist = async (nextCaption, nextTags) => {
    if (!id) return;
    setState("saving");
    setError("");
    try {
      const saved = await updateOutput(id, {
        caption: nextCaption,
        hashtags: nextTags,
      });
      setCaption(saved.caption);
      setTags(saved.hashtags);
      setState("saved");
      timerRef.current = setTimeout(() => setState("idle"), 1600);
    } catch (e) {
      setState("error");
      setError(e.message);
    }
  };

  const addTag = () => {
    const value = draft.trim();
    if (!value || tags.length >= MAX_HASHTAGS) return;
    const next = [...tags, value];
    setDraft("");
    setTags(next);
    persist(caption, next);
  };

  const removeTag = (tag) => {
    const next = tags.filter((t) => t !== tag);
    setTags(next);
    persist(caption, next);
  };

  const regenerate = async () => {
    if (!id) return;
    setState("saving");
    setError("");
    try {
      const fresh = await regenerateCaption(id);
      setCaption(fresh.caption);
      setTags(fresh.hashtags);
      setState("saved");
      timerRef.current = setTimeout(() => setState("idle"), 1600);
    } catch (e) {
      setState("error");
      setError(e.message);
    }
  };

  if (!id) return null;

  const full = tags.length >= MAX_HASHTAGS;

  return (
    <div className="caption">
      <div className="caption__head">
        <span className="caption__label">Legenda do post</span>
        <span className="caption__state">
          {state === "saving" && "salvando…"}
          {state === "saved" && "salvo"}
          {state === "error" && "não salvou"}
        </span>
      </div>

      <textarea
        className="caption__text"
        value={caption}
        rows={2}
        maxLength={150}
        placeholder="Escreva a legenda do post…"
        onChange={(e) => setCaption(e.target.value)}
        onBlur={() => caption !== result.caption && persist(caption, tags)}
      />

      <div className="caption__tags">
        {tags.map((t) => (
          <button
            type="button"
            className="tagchip"
            key={t}
            onClick={() => removeTag(t)}
            title="Remover hashtag"
          >
            #{t}
            <IconMinus width={12} height={12} />
          </button>
        ))}
        {!full && (
          <input
            className="tagchip tagchip--input"
            value={draft}
            placeholder="+ hashtag"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addTag();
              }
            }}
            onBlur={addTag}
          />
        )}
      </div>

      <div className="caption__foot">
        <span className={"caption__count" + (full ? " is-full" : "")}>
          {tags.length}/{MAX_HASHTAGS} hashtags · {caption.length}/150
        </span>
        <button
          type="button"
          className="btn btn--ghost btn--xs"
          onClick={regenerate}
          disabled={state === "saving"}
        >
          <IconRefresh width={14} height={14} /> Outra legenda
        </button>
      </div>

      {error && <div className="caption__err">{error}</div>}
    </div>
  );
}
