import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  getLibrary,
  uploadToLibrary,
  updateLibraryTags,
  deleteLibraryItem,
  libraryVideoUrl,
} from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import { IconUpload, IconTrash, IconVideo, IconPlus } from "./Icons.jsx";

function fmtDur(sec) {
  if (!sec) return "—";
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

function fmtSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function statusLabel(status) {
  if (status === "ready") return "Pronto";
  if (status === "processing") return "Processando";
  if (status === "queued") return "Na fila";
  if (status === "error") return "Erro";
  return status;
}

export default function LibraryView({ onUseForGeneration }) {
  const [items, setItems] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tagDraft, setTagDraft] = useState({});
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getLibrary();
      setItems(data.items || []);
      setMetrics(data.metrics || null);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  useEffect(() => {
    clearInterval(pollRef.current);
    const hasPending = items.some(
      (i) => i.status === "processing" || i.status === "queued"
    );
    if (hasPending) {
      pollRef.current = setInterval(refresh, 2000);
    }
    return () => clearInterval(pollRef.current);
  }, [items, refresh]);

  const uploadFiles = async (files) => {
    if (!files || !files.length) return;
    setBusy(true);
    setError("");
    try {
      for (const f of files) {
        await uploadToLibrary(f);
      }
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addTag = async (id, currentTags) => {
    const raw = (tagDraft[id] || "").trim().toLowerCase();
    if (!raw) return;
    const tags = [...(currentTags || [])];
    if (!tags.includes(raw)) tags.push(raw);
    setTagDraft((d) => ({ ...d, [id]: "" }));
    try {
      await updateLibraryTags(id, tags);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const removeTag = async (id, currentTags, tag) => {
    const tags = (currentTags || []).filter((t) => t !== tag);
    try {
      await updateLibraryTags(id, tags);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const del = async (id) => {
    if (!confirm("Remover este vídeo da biblioteca?")) return;
    try {
      await deleteLibraryItem(id);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const m = metrics || {};

  return (
    <>
      {error && <div className="banner banner--error">Erro: {error}</div>}

      {/* Produzidos e publicados mudaram de casa: agora vivem na aba
          Produzidos, que e de onde se publica. Repetir os mesmos numeros aqui
          so criava duas fontes para a mesma pergunta. O quanto cada fonte
          rendeu continua visivel, por item, no card dela. */}
      <div className="metrics-row">
        <div className="metric-card">
          <div className="metric-card__val">{m.total ?? 0}</div>
          <div className="metric-card__lbl">Vídeos-fonte</div>
        </div>
        <div className="metric-card metric-card--accent">
          <div className="metric-card__val">{m.total_produced ?? 0}</div>
          <div className="metric-card__lbl">Gerados a partir deles</div>
          {m.produced_7d > 0 && (
            <div className="metric-card__sub">{m.produced_7d} nos últimos 7 dias</div>
          )}
        </div>
      </div>

      {m.tag_counts && Object.keys(m.tag_counts).length > 0 && (
        <div className="card" style={{ marginBottom: 18 }}>
          <h3 className="card__title">Tags em uso</h3>
          <div className="chips">
            {Object.entries(m.tag_counts)
              .sort((a, b) => b[1] - a[1])
              .map(([tag, count]) => (
                <span className="chip" key={tag}>
                  {tag} · {count}
                </span>
              ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3 className="card__title">
          <span className="dot">
            <IconUpload width={18} height={18} />
          </span>
          Adicionar à biblioteca
        </h3>
        <p className="card__hint">
          Envie vídeos (MP4, MOV, MKV…). O app normaliza automaticamente — HDR,
          rotação e .mov de iPhone ficam prontos para gerar sem espera.
        </p>
        <label
          className={"drop" + (drag ? " drag" : "")}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            uploadFiles(e.dataTransfer.files);
          }}
        >
          <div className="drop__icon">
            <IconUpload width={26} height={26} />
          </div>
          <div className="drop__title">
            {busy ? "Enviando e pré-processando..." : "Solte vídeos aqui"}
          </div>
          <div style={{ fontSize: "var(--text-xs)" }}>ou clique para escolher (vários de uma vez)</div>
          <input
            type="file"
            accept="video/*"
            multiple
            hidden
            disabled={busy}
            onChange={(e) => uploadFiles(e.target.files)}
          />
        </label>
      </div>

      {items.length === 0 ? (
        <div className="card" style={{ marginTop: 18 }}>
          <div className="empty">
            Nenhum vídeo na biblioteca. Adicione arquivos acima — é daqui que
            toda produção começa.
          </div>
        </div>
      ) : (
        <div className="lib-grid">
          {items.map((item) => (
            <LibraryCard
              key={item.id}
              item={item}
              tagDraft={tagDraft[item.id] || ""}
              onTagDraft={(v) => setTagDraft((d) => ({ ...d, [item.id]: v }))}
              onAddTag={() => addTag(item.id, item.tags)}
              onRemoveTag={(tag) => removeTag(item.id, item.tags, tag)}
              onDelete={() => del(item.id)}
              onGenerate={() => onUseForGeneration && onUseForGeneration(item)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function LibraryCard({
  item,
  tagDraft,
  onTagDraft,
  onAddTag,
  onRemoveTag,
  onDelete,
  onGenerate,
}) {
  const ready = item.status === "ready";
  const pending = item.status === "processing" || item.status === "queued";
  const url = ready && item.file ? libraryVideoUrl(item.file) : null;

  return (
    <div className={"lib-card" + (pending ? " lib-card--busy" : "")}>
      <div className="lib-card__media">
        {url ? (
          <LazyVideo src={url} />
        ) : (
          <div className="lib-card__placeholder">
            {pending ? <span className="spinner" /> : <IconVideo width={28} height={28} />}
          </div>
        )}
        <span className={"lib-card__status lib-card__status--" + item.status}>
          {statusLabel(item.status)}
        </span>
      </div>

      <div className="lib-card__body">
        <div className="lib-card__name" title={item.name}>
          {item.name}
        </div>
        <div className="lib-card__meta">
          {fmtDur(item.duration_sec)}
          {item.size_bytes ? ` · ${fmtSize(item.size_bytes)}` : ""}
          {item.produced_count > 0 && (
            <>
              {" · "}
              <strong>{item.produced_count}</strong> vídeos ·{" "}
              <strong>{item.published_count}</strong> publicados
            </>
          )}
        </div>

        {item.status === "error" && item.error && (
          <div className="lib-card__err">{item.error}</div>
        )}
        {pending && item.message && (
          <div className="lib-card__msg">{item.message}</div>
        )}

        <div className="lib-card__tags">
          {(item.tags || []).map((tag) => (
            <span className="lib-tag" key={tag}>
              {tag}
              <button type="button" onClick={() => onRemoveTag(tag)} aria-label="Remover tag">
                ×
              </button>
            </span>
          ))}
          <span className="lib-tag-add">
            <input
              placeholder="+ tag"
              value={tagDraft}
              onChange={(e) => onTagDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAddTag()}
            />
            <button type="button" onClick={onAddTag} title="Adicionar tag">
              <IconPlus width={12} height={12} />
            </button>
          </span>
        </div>

        <div className="lib-card__actions">
          <button
            className="btn btn--primary"
            disabled={!ready}
            onClick={onGenerate}
          >
            Produzir vídeo
          </button>
          <button className="icon-btn" onClick={onDelete} title="Remover">
            <IconTrash width={15} height={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
