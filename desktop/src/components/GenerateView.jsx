import React, { useEffect, useRef, useState } from "react";
import { startGeneration, getStatus, outputUrl } from "../api.js";
import { addEntry } from "../lib/history.js";
import HeightPicker from "./HeightPicker.jsx";
import Swatches from "./Swatches.jsx";
import {
  IconUpload,
  IconDownload,
  IconMic,
  IconPlus,
  IconMinus,
} from "./Icons.jsx";

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

function metaChips(meta) {
  const chips = [];
  if (meta.audioEnabled) chips.push("Narração (ElevenLabs)");
  if (meta.theme) chips.push("Tema: " + meta.theme);
  if (meta.audioEnabled && meta.audioTheme)
    chips.push("Narração: " + meta.audioTheme);
  chips.push("Altura: " + Math.round((meta.vertical ?? 0.5) * 100) + "%");
  chips.push("Fonte: " + meta.fontSize);
  chips.push("Contorno: " + meta.strokeWidth);
  chips.push("Entrelinha: " + Number(meta.lineSpacing).toFixed(2) + "x");
  return chips;
}

export default function GenerateView({ config, reopen, onReopened }) {
  const [file, setFile] = useState(null);
  const [drag, setDrag] = useState(false);
  const [opts, setOpts] = useState(DEFAULTS);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [voiceSel, setVoiceSel] = useState("");
  const [manualVoice, setManualVoice] = useState("");
  const [audioTheme, setAudioTheme] = useState("");

  const [busy, setBusy] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [results, setResults] = useState([]);
  const [resultMeta, setResultMeta] = useState(null);
  const pollRef = useRef(null);

  const voices = config?.voices || [];
  const set = (patch) => setOpts((o) => ({ ...o, ...patch }));

  // Seleciona a primeira voz automaticamente quando a lista carrega.
  useEffect(() => {
    if (voices.length && !voices.some((v) => v.id === voiceSel)) {
      setVoiceSel(voices[0].id);
    }
  }, [config]);

  // Reabrir uma entrada do histórico (somente exibe os resultados salvos).
  useEffect(() => {
    if (reopen) {
      setResults(reopen.results || []);
      setResultMeta(reopen.meta || null);
      setError("");
      onReopened && onReopened();
    }
  }, [reopen]);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const onFiles = (files) => {
    if (files && files.length) setFile(files[0]);
  };

  const clampNum = (v) => Math.max(1, Math.min(10, parseInt(v) || 1));

  async function start() {
    setError("");
    if (!file) {
      setError("Selecione um vídeo primeiro.");
      return;
    }
    // Resolve a voz selecionada (cadastrada) ou um Voice ID avulso (fallback).
    let resolvedVoice = null;
    if (audioEnabled) {
      if (!config?.elevenlabs_available) {
        setError(
          "ELEVENLABS_API_KEY não configurada. Configure em Ajustes para usar o modo com áudio."
        );
        return;
      }
      if (voices.length > 0) {
        const v = voices.find((x) => x.id === voiceSel);
        if (!v) {
          setError("Selecione uma voz da biblioteca (ou cadastre em Ajustes).");
          return;
        }
        resolvedVoice = {
          voice_id: v.voice_id,
          name: v.name,
          model_id: v.model_id || "",
          stability: v.stability ?? 0.5,
          similarity: v.similarity ?? 0.75,
        };
      } else if (manualVoice.trim()) {
        resolvedVoice = {
          voice_id: manualVoice.trim(),
          name: manualVoice.trim(),
          model_id: "",
          stability: 0.5,
          similarity: 0.75,
        };
      } else {
        setError(
          "Cadastre uma voz em Ajustes › Vozes, ou informe um Voice ID avulso."
        );
        return;
      }
    }

    const meta = {
      sourceName: file.name,
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
      voiceId: resolvedVoice ? resolvedVoice.voice_id : "",
      voiceName: resolvedVoice ? resolvedVoice.name : "",
      audioModel: resolvedVoice ? resolvedVoice.model_id : "",
    };

    const fd = new FormData();
    fd.append("video", file);
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
      fd.append("voice_id", resolvedVoice.voice_id);
      fd.append("audio_theme", meta.audioTheme);
      fd.append("audio_model_id", resolvedVoice.model_id);
      fd.append("stability", String(resolvedVoice.stability));
      fd.append("similarity", String(resolvedVoice.similarity));
    }

    setBusy(true);
    setResults([]);
    setResultMeta(meta);
    setProgress(4);
    setStatusMsg("Enviando vídeo...");

    try {
      const { job_id } = await startGeneration(fd);
      poll(job_id, meta);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  function poll(jobId, meta) {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await getStatus(jobId);
        setStatusMsg(j.message || j.status || "");
        setProgress(j.progress || 0);
        if (j.results && j.results.length) setResults(j.results);
        if (j.status === "done") {
          clearInterval(pollRef.current);
          setBusy(false);
          setProgress(100);
          const finalResults = j.results || [];
          setResults(finalResults);
          addEntry({
            id: jobId,
            date: new Date().toISOString(),
            meta,
            results: finalResults,
          });
        } else if (j.status === "error") {
          clearInterval(pollRef.current);
          setBusy(false);
          setError(j.message || "Erro na geração.");
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setBusy(false);
        setError("Falha ao consultar status: " + e.message);
      }
    }, 1400);
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
        {/* Coluna esquerda: upload + opções principais */}
        <div>
          <div className="card">
            <h3 className="card__title">
              <span className="dot">
                <IconUpload width={18} height={18} />
              </span>
              Vídeo de origem
            </h3>
            <p className="card__hint">
              Arraste um arquivo ou clique para selecionar. Suporta MP4, MOV
              (iPhone HDR), MKV, AVI, WEBM, M4V.
            </p>

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
              <div style={{ fontSize: 12 }}>ou clique para escolher</div>
              <input
                type="file"
                accept="video/*"
                hidden
                onChange={(e) => onFiles(e.target.files)}
              />
            </label>
            {file && <div className="filechip">🎬 {file.name}</div>}

            <div className="field" style={{ marginTop: 18 }}>
              <label className="field__label">Tema / contexto (opcional)</label>
              <textarea
                className="textarea"
                placeholder="Ex.: promoção relâmpago de tênis, humor, curiosidades..."
                value={opts.theme}
                onChange={(e) => set({ theme: e.target.value })}
              />
              <div className="field__hint">
                Apenas texto é enviado à OpenRouter — o vídeo nunca sai do seu PC.
              </div>
            </div>

            <div className="grid2">
              <div className="field">
                <label className="field__label">Número de variações</label>
                <div className="stepper">
                  <button onClick={() => set({ num: clampNum(opts.num - 1) })}>
                    <IconMinus width={16} height={16} />
                  </button>
                  <input
                    value={opts.num}
                    onChange={(e) => set({ num: e.target.value })}
                    onBlur={(e) => set({ num: clampNum(e.target.value) })}
                  />
                  <button onClick={() => set({ num: clampNum(opts.num + 1) })}>
                    <IconPlus width={16} height={16} />
                  </button>
                </div>
                <div className="field__hint">1 a 10 vídeos, frases diferentes.</div>
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

          {/* Modo com áudio */}
          <div className="card">
            <h3 className="card__title">
              <span className="dot">
                <IconMic width={18} height={18} />
              </span>
              Narração por voz (ElevenLabs)
            </h3>
            <label className="toggle" style={{ marginBottom: 6 }}>
              <input
                type="checkbox"
                checked={audioEnabled}
                onChange={(e) => setAudioEnabled(e.target.checked)}
              />
              <span className="toggle__track" />
              <span>Gerar áudio (narração por voz)</span>
            </label>

            {audioEnabled && !config?.elevenlabs_available && (
              <div className="banner banner--warn" style={{ marginTop: 12 }}>
                ELEVENLABS_API_KEY não configurada. Adicione em <b>Ajustes</b>.
              </div>
            )}

            {audioEnabled && (
              <div style={{ marginTop: 14 }}>
                {voices.length > 0 ? (
                  <div className="field">
                    <label className="field__label">Voz</label>
                    <select
                      className="select"
                      value={voiceSel}
                      onChange={(e) => setVoiceSel(e.target.value)}
                    >
                      {voices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                        </option>
                      ))}
                    </select>
                    {(() => {
                      const v = voices.find((x) => x.id === voiceSel);
                      if (!v) return null;
                      return (
                        <div className="voice-select-info">
                          Voice ID: {v.voice_id}
                          {v.model_id ? ` · ${v.model_id}` : ""} · stab{" "}
                          {(v.stability ?? 0.5).toFixed(2)} · sim{" "}
                          {(v.similarity ?? 0.75).toFixed(2)}
                        </div>
                      );
                    })()}
                  </div>
                ) : (
                  <>
                    <div className="banner banner--warn">
                      Nenhuma voz cadastrada. Vá em <b>Ajustes › Vozes</b> para
                      cadastrar suas vozes da ElevenLabs. Você também pode
                      informar um Voice ID avulso abaixo.
                    </div>
                    <div className="field">
                      <label className="field__label">Voice ID avulso</label>
                      <input
                        className="input"
                        placeholder="ex.: 21m00Tcm4TlvDq8ikWAM"
                        value={manualVoice}
                        onChange={(e) => setManualVoice(e.target.value)}
                      />
                    </div>
                  </>
                )}

                <div className="field">
                  <label className="field__label">
                    Tema / contexto da narração (opcional)
                  </label>
                  <input
                    className="input"
                    placeholder="Roteiro da fala (separado do tema da frase)"
                    value={audioTheme}
                    onChange={(e) => setAudioTheme(e.target.value)}
                  />
                </div>

                <div className="field__hint">
                  Os parâmetros avançados (modelo, estabilidade, similaridade)
                  vêm da voz cadastrada em Ajustes. A narração é dimensionada
                  para a duração do vídeo + 10s; se for mais longa, o último
                  frame é congelado.
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Coluna direita: estilo do texto + ação */}
        <div>
          <div className="card">
            <h3 className="card__title">Estilo do texto</h3>
            <div className="grid2">
              <div className="field">
                <label className="field__label">Cor do texto</label>
                <Swatches
                  value={opts.color}
                  onChange={(c) => set({ color: c })}
                />
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
                  onChange={(e) =>
                    set({ lineSpacing: parseFloat(e.target.value) })
                  }
                />
              </div>
            </div>
          </div>

          <div className="card">
            <button
              className="btn btn--primary btn--block"
              disabled={busy}
              onClick={start}
            >
              {busy ? "Gerando..." : "Gerar vídeos"}
            </button>

            {busy && (
              <div className="progress">
                <div className="progress__msg">
                  <span className="spinner" />
                  {statusMsg}
                </div>
                <div className="progress__bar">
                  <div
                    className="progress__fill"
                    style={{ width: progress + "%" }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Resultados */}
      {results.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3 className="card__title">
            Resultados · {results.length}{" "}
            {results.length === 1 ? "vídeo" : "vídeos"}
          </h3>
          {resultMeta && (
            <div className="chips">
              {metaChips(resultMeta).map((c, i) => (
                <span className="chip" key={i}>
                  {c}
                </span>
              ))}
            </div>
          )}
          <div className="results">
            {results.map((r, i) => (
              <ResultCard key={i} r={r} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function ResultCard({ r }) {
  const [broken, setBroken] = useState(false);
  const url = outputUrl(r.file);
  return (
    <div className="rcard">
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
        <a className="btn btn--ghost btn--block" href={url} download={r.file}>
          <IconDownload width={16} height={16} /> Baixar
        </a>
      </div>
    </div>
  );
}
