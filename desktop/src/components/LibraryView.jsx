import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  alternarFavorito,
  esvaziarLixeira,
  restaurarVideo,
  updateLibraryFolder,
  getLibrary,
  uploadToLibrary,
  updateLibraryTags,
  deleteLibraryItem,
  libraryVideoUrl,
} from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import { IconUpload, IconTrash, IconVideo, IconPlus, IconStar, IconRefresh } from "./Icons.jsx";

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

export default function LibraryView({
  secao = "todos",
  pastaId = null,
  pastas = [],
  importarPedido = 0,
  onMudou,
  onUseForGeneration,
}) {
  const [items, setItems] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tagDraft, setTagDraft] = useState({});
  const [busca, setBusca] = useState("");
  const [tagFiltro, setTagFiltro] = useState("");
  // O upload fica recolhido quando ja existe acervo. Numa biblioteca vazia ele
  // se abre sozinho: e a unica acao possivel, e a orientacao de estado vazio e
  // justamente mostrar a acao em vez de uma tela em branco.
  const [uploadAberto, setUploadAberto] = useState(false);
  const [dias, setDias] = useState(30);
  const pollRef = useRef(null);

  const visiveis = items.filter((i) => {
    if (tagFiltro && !(i.tags || []).includes(tagFiltro)) return false;
    const termo = busca.trim().toLowerCase();
    if (!termo) return true;
    return [i.name, ...(i.tags || [])].join(" ").toLowerCase().includes(termo);
  });

  const naLixeira = secao === "lixeira";

  const favoritar = async (id) => {
    try {
      await alternarFavorito(id);
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  const moverPara = async (id, folderId) => {
    try {
      await updateLibraryFolder(id, folderId);
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  const restaurar = async (id) => {
    try {
      await restaurarVideo(id);
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  const esvaziar = async () => {
    if (!window.confirm(
      "Apagar em definitivo tudo que está na lixeira? Os arquivos somem do disco."
    )) return;
    try {
      await esvaziarLixeira();
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  const refresh = useCallback(async () => {
    try {
      const data = await getLibrary(
        pastaId !== null ? { pasta: pastaId } : { secao }
      );
      setItems(data.items || []);
      setMetrics(data.metrics || null);
      if (data.lixeira_dias) setDias(data.lixeira_dias);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, [secao, pastaId]);

  useEffect(() => {
    if (importarPedido > 0) setUploadAberto(true);
  }, [importarPedido]);

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
    // O aviso muda com o contexto, porque a acao muda: fora da lixeira e
    // reversivel, dentro dela e definitiva. Um texto so para os dois casos
    // ou assusta a toa, ou nao assusta quando deveria.
    const pergunta = naLixeira
      ? "Apagar este vídeo em definitivo? O arquivo some do disco."
      : `Mover para a lixeira? Fica lá por ${dias} dias antes de sumir de vez.`;
    if (!confirm(pergunta)) return;
    try {
      await deleteLibraryItem(id);
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  const m = metrics || {};

  return (
    <>
      {error && <div className="banner banner--error">Erro: {error}</div>}

      {/* Uma faixa de numeros, nao dois cartoes competindo com o conteudo.
          Produzidos e publicados mudaram de casa para a aba Produzidos; aqui
          fica so o que e da Biblioteca. */}
      <div className="statline">
        <span className="statline__item">
          <strong>{m.total ?? 0}</strong> vídeos-fonte
        </span>
        <span className="statline__sep" aria-hidden="true">·</span>
        <span className="statline__item">
          <strong>{m.total_produced ?? 0}</strong> gerados a partir deles
        </span>
        {m.produced_7d > 0 && (
          <>
            <span className="statline__sep" aria-hidden="true">·</span>
            <span className="statline__item statline__item--soft">
              {m.produced_7d} nos últimos 7 dias
            </span>
          </>
        )}
      </div>

      {naLixeira && (
        <div className="toolbar">
          <p className="muted" style={{ flex: 1, margin: 0, maxWidth: "var(--measure)" }}>
            Vídeos aqui somem do disco automaticamente depois de{" "}
            {dias || 30} dias. Restaurar traz de volta para a Biblioteca.
          </p>
          {items.length > 0 && (
            <button className="btn btn--ghost" onClick={esvaziar}>
              <IconTrash width={16} height={16} /> Esvaziar lixeira
            </button>
          )}
        </div>
      )}

      {/* Barra de trabalho: buscar, filtrar e adicionar. Fica acima do acervo
          porque e o que se opera; o upload virou um botao, e nao a maior peca
          da tela -- arquivo entra de vez em quando, video se escolhe sempre. */}
      <div className="toolbar" hidden={naLixeira}>
        <input
          className="input toolbar__search"
          type="search"
          placeholder={`Buscar entre ${items.length} vídeos`}
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />

        {m.tag_counts && Object.keys(m.tag_counts).length > 0 && (
          <div className="chips toolbar__tags">
            {Object.entries(m.tag_counts)
              .sort((a, b) => b[1] - a[1])
              .map(([tag, count]) => (
                <button
                  key={tag}
                  type="button"
                  className={"chip chip--btn" + (tagFiltro === tag ? " chip--on" : "")}
                  onClick={() => setTagFiltro(tagFiltro === tag ? "" : tag)}
                  aria-pressed={tagFiltro === tag}
                >
                  {tag} · {count}
                </button>
              ))}
          </div>
        )}

        <button
          type="button"
          className="btn btn--primary toolbar__add"
          onClick={() => setUploadAberto((v) => !v)}
          aria-expanded={uploadAberto || items.length === 0}
        >
          <IconPlus width={16} height={16} /> Adicionar vídeos
        </button>
      </div>

      {(uploadAberto || items.length === 0) && (
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
          <div style={{ fontSize: "var(--text-xs)" }}>
            ou clique para escolher (vários de uma vez). MP4, MOV, MKV — o app
            normaliza HDR, rotação e .mov de iPhone automaticamente.
          </div>
          <input
            type="file"
            accept="video/*"
            multiple
            hidden
            disabled={busy}
            onChange={(e) => uploadFiles(e.target.files)}
          />
        </label>
      )}

      {items.length === 0 ? (
        <div className="empty">
          Nenhum vídeo na biblioteca. Adicione arquivos acima — é daqui que toda
          produção começa.
        </div>
      ) : visiveis.length === 0 ? (
        <div className="empty">
          Nenhum vídeo com esse nome ou tag.{" "}
          <button
            className="btn btn--ghost btn--xs"
            onClick={() => {
              setBusca("");
              setTagFiltro("");
            }}
          >
            Limpar filtros
          </button>
        </div>
      ) : (
        <div className="lib-grid">
          {visiveis.map((item) => (
            <LibraryCard
              key={item.id}
              item={item}
              tagDraft={tagDraft[item.id] || ""}
              onTagDraft={(v) => setTagDraft((d) => ({ ...d, [item.id]: v }))}
              onAddTag={() => addTag(item.id, item.tags)}
              onRemoveTag={(tag) => removeTag(item.id, item.tags, tag)}
              onDelete={() => del(item.id)}
              onGenerate={() => onUseForGeneration && onUseForGeneration(item)}
              onFavoritar={() => favoritar(item.id)}
              onMoverPara={(fid) => moverPara(item.id, fid)}
              onRestaurar={() => restaurar(item.id)}
              pastas={pastas}
              naLixeira={naLixeira}
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
  onFavoritar,
  onMoverPara,
  onRestaurar,
  pastas = [],
  naLixeira = false,
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

        {!naLixeira && (
          <button
            className={"lib-card__fav" + (item.favorito ? " is-on" : "")}
            onClick={onFavoritar}
            title={item.favorito ? "Remover dos favoritos" : "Marcar como favorito"}
            aria-pressed={!!item.favorito}
          >
            {/* O preenchimento e o que distingue a distancia; cor sozinha nao
                bastaria para quem nao a percebe. */}
            <IconStar width={16} height={16} fill={item.favorito ? "currentColor" : "none"} />
          </button>
        )}
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

        {naLixeira ? (
          <div className="lib-card__actions">
            <button className="btn btn--ghost" onClick={onRestaurar}>
              <IconRefresh width={15} height={15} /> Restaurar
            </button>
            <button
              className="icon-btn icon-btn--perigo"
              onClick={onDelete}
              title="Apagar definitivamente"
            >
              <IconTrash width={15} height={15} />
            </button>
          </div>
        ) : (
          <>
            {pastas.length > 0 && (
              <select
                className="input lib-card__pasta"
                value={item.folder_id || ""}
                onChange={(e) => onMoverPara(e.target.value)}
                aria-label="Pasta"
              >
                <option value="">Sem pasta</option>
                {pastas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            <div className="lib-card__actions">
              <button
                className="btn btn--primary"
                disabled={!ready}
                onClick={onGenerate}
              >
                Produzir vídeo
              </button>
              <button className="icon-btn" onClick={onDelete} title="Mover para a lixeira">
                <IconTrash width={15} height={15} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
