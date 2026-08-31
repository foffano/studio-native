import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  alternarFavorito,
  criarPasta,
  esvaziarLixeira,
  restaurarVideo,
  updateLibraryFolder,
  getLibrary,
  uploadToLibrary,
  updateLibraryTags,
  deleteLibraryItem,
  libraryVideoUrl,
  libraryThumbnailUrl,
} from "../api.js";
import LazyVideo from "./LazyVideo.jsx";
import SourcePanel from "./SourcePanel.jsx";
import FolderTile from "./FolderTile.jsx";
import { IconUpload, IconTrash, IconVideo, IconPlus, IconStar, IconRefresh, IconPlay, IconPause } from "./Icons.jsx";

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
  onAbrirPasta,
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
  const [uploadProgress, setUploadProgress] = useState(null);
  const [dias, setDias] = useState(30);
  const [selecionadoId, setSelecionadoId] = useState(null);
  const [arrastando, setArrastando] = useState(null);   // id do video em movimento
  const [alvo, setAlvo] = useState(null);               // id sob o cursor
  const pollRef = useRef(null);
  const fileInputRef = useRef(null);

  // Na raiz ("todos"), o modelo e de gerenciador de arquivos: aparecem as
  // pastas e os videos que nao estao em nenhuma. Nas outras secoes -- favoritos,
  // recentes, lixeira -- o recorte e o assunto, e esconder por pasta la
  // esconderia justamente o que a secao existe para mostrar.
  const naRaiz = secao === "todos" && pastaId === null;

  // Deriva de `items` em vez de guardar o objeto: assim o painel acompanha
  // qualquer mudanca feita por ele mesmo (favoritar, mover de pasta, tags).
  const selecionado = items.find((i) => i.id === selecionadoId) || null;

  const visiveis = items.filter((i) => {
    if (naRaiz && (i.folder_id || "")) return false;
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

  /** Solta um video sobre outro: cria uma pasta com os dois. */
  const juntarEmPasta = async (idArrastado, idAlvo) => {
    if (idArrastado === idAlvo) return;
    const nome = window.prompt("Nome da nova pasta");
    if (!nome || !nome.trim()) return;
    try {
      const pasta = await criarPasta(nome.trim());
      // Sequencial, e nao em paralelo: os dois escrevem no mesmo library.json,
      // e duas gravacoes concorrentes se sobrescreveriam.
      await updateLibraryFolder(idArrastado, pasta.id);
      await updateLibraryFolder(idAlvo, pasta.id);
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    }
  };

  /** Solta um video sobre uma pasta existente. */
  const soltarNaPasta = async (idArrastado, pastaId) => {
    try {
      await updateLibraryFolder(idArrastado, pastaId);
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
    const queue = Array.from(files);
    setBusy(true);
    setError("");
    try {
      for (let index = 0; index < queue.length; index += 1) {
        const f = queue[index];
        setUploadProgress({ phase: "upload", fileName: f.name, index: index + 1, total: queue.length, percent: 0 });
        await uploadToLibrary(f, (percent) =>
          setUploadProgress({ phase: "upload", fileName: f.name, index: index + 1, total: queue.length, percent })
        );
      }
      await refresh();
      onMudou && onMudou();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      setUploadProgress(null);
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
    if (!confirm(pergunta)) return false;
    try {
      await deleteLibraryItem(id);
      await refresh();
      onMudou && onMudou();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  };

  const m = metrics || {};
  const processingCount = items.filter(
    (item) => item.status === "processing" || item.status === "queued"
  ).length;

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

        {/* No celular o rótulo encolhe para "Adicionar" -- e não some. Um
            botão só de ícone precisaria de `aria-label` e ainda assim exigiria
            adivinhar o que o "+" faz. Trocar de palavra custa nada. */}
        <button
          type="button"
          className="btn btn--primary toolbar__add"
          onClick={() => fileInputRef.current?.click()}
          disabled={busy}
        >
          <IconPlus width={16} height={16} />
          <span className="toolbar__add-longo">Adicionar vídeos</span>
          <span className="toolbar__add-curto">Adicionar</span>
        </button>
      </div>

      <input
        ref={fileInputRef}
        id="library-upload-input"
        type="file"
        accept="video/*"
        multiple
        hidden
        disabled={busy}
        onChange={(e) => {
          const selected = e.target.files;
          uploadFiles(selected);
          e.target.value = "";
        }}
      />

      {(uploadProgress || processingCount > 0) && (
        <section className="upload-status" aria-live="polite" aria-label="Progresso da importação">
          <div className="upload-status__head">
            <div>
              <strong>
                {uploadProgress
                  ? `Enviando ${uploadProgress.index} de ${uploadProgress.total}`
                  : processingCount === 1
                  ? "Preparando vídeo"
                  : `Preparando ${processingCount} vídeos`}
              </strong>
              <span>
                {uploadProgress
                  ? uploadProgress.fileName
                  : "Normalizando formato, cor e rotação para a biblioteca"}
              </span>
            </div>
            <b>{uploadProgress ? `${uploadProgress.percent}%` : "Em andamento"}</b>
          </div>
          <div className={"upload-status__track" + (!uploadProgress ? " upload-status__track--processing" : "")}>
            <div style={uploadProgress ? { width: `${uploadProgress.percent}%` } : undefined} />
          </div>
        </section>
      )}

      {(uploadAberto || items.length === 0) && (
        <label
          htmlFor="library-upload-input"
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
        <div className={"lib-layout" + (selecionado ? " lib-layout--com-painel" : "")}>
        <div className="lib-grid">
          {naRaiz &&
            pastas.map((pst) => (
              <FolderTile
                key={pst.id}
                pasta={pst}
                total={items.filter((i) => (i.folder_id || "") === pst.id).length}
                amostra={items.filter((i) => (i.folder_id || "") === pst.id).slice(0, 4)}
                arrastandoSobre={alvo === "pasta:" + pst.id}
                onAbrir={() => onAbrirPasta && onAbrirPasta(pst.id)}
                onDragOver={(e) => {
                  e.preventDefault();
                  setAlvo("pasta:" + pst.id);
                }}
                onDragLeave={() => setAlvo(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setAlvo(null);
                  const id = e.dataTransfer.getData("text/studio-video");
                  if (id) soltarNaPasta(id, pst.id);
                }}
              />
            ))}

          {visiveis.map((item) => (
            <LibraryCard
              key={item.id}
              item={item}
              selecionado={selecionadoId === item.id}
              onSelecionar={() =>
                setSelecionadoId((a) => (a === item.id ? null : item.id))
              }
              arrastavel={!naLixeira}
              arrastandoSobre={alvo === item.id}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/studio-video", item.id);
                e.dataTransfer.effectAllowed = "move";
                setArrastando(item.id);
              }}
              onDragEnd={() => {
                setArrastando(null);
                setAlvo(null);
              }}
              onDragOver={(e) => {
                if (!arrastando || arrastando === item.id) return;
                e.preventDefault();
                setAlvo(item.id);
              }}
              onDragLeave={() => setAlvo(null)}
              onDrop={(e) => {
                e.preventDefault();
                setAlvo(null);
                const id = e.dataTransfer.getData("text/studio-video");
                if (id && id !== item.id) juntarEmPasta(id, item.id);
              }}
            />
          ))}
        </div>

        {selecionado && (
          <SourcePanel
            item={selecionado}
            pastas={pastas}
            naLixeira={naLixeira}
            tagDraft={tagDraft[selecionado.id] || ""}
            onTagDraft={(v) =>
              setTagDraft((d) => ({ ...d, [selecionado.id]: v }))
            }
            onAddTag={() => addTag(selecionado.id, selecionado.tags)}
            onRemoveTag={(tag) => removeTag(selecionado.id, selecionado.tags, tag)}
            onFavoritar={() => favoritar(selecionado.id)}
            onMoverPara={(fid) => moverPara(selecionado.id, fid)}
            onRestaurar={() => restaurar(selecionado.id)}
            onExcluir={async () => {
              if (await del(selecionado.id)) setSelecionadoId(null);
            }}
            onFechar={() => setSelecionadoId(null)}
            onProduzir={() => onUseForGeneration && onUseForGeneration(selecionado)}
          />
        )}
        </div>
      )}
    </>
  );
}

/**
 * Um vídeo na grade: só o quadro.
 *
 * Sem nome, sem metadado, sem controle. Numa grade de dezenas de vídeos, o que
 * identifica cada um é a imagem — o nome de arquivo (`IMG_0826(1).MOV`) não
 * diz nada, e os controles repetidos em cada card enchiam a tela de botões que
 * quase nunca são usados.
 *
 * Tudo que era daqui vive agora no painel, aberto ao clicar. A única exceção é
 * o estado: um vídeo ainda processando ou com erro é indistinguível de um
 * pronto pela imagem, e essa diferença decide se dá para produzir com ele.
 */
function LibraryCard({
  item,
  onSelecionar,
  selecionado = false,
  arrastavel = false,
  arrastandoSobre = false,
  ...dnd
}) {
  const [previewing, setPreviewing] = useState(false);
  const ready = item.status === "ready";
  const pending = item.status === "processing" || item.status === "queued";
  const url = ready && item.file ? libraryVideoUrl(item.file) : null;
  const producedCount = Number(item.produced_count ?? item.total_outputs ?? 0);
  const durationLabel = item.duration_sec ? fmtDur(item.duration_sec) : "";
  const cardLabel = [
    item.name,
    durationLabel && `duração ${durationLabel}`,
    `${producedCount} ${producedCount === 1 ? "vídeo gerado" : "vídeos gerados"}`,
  ].filter(Boolean).join(", ");

  return (
    <div
      className={
        "vcard" +
        (selecionado ? " vcard--on" : "") +
        (arrastandoSobre ? " vcard--alvo" : "")
      }
      draggable={arrastavel}
      onMouseLeave={() => setPreviewing(false)}
      {...dnd}
    >
      <button
        className="vcard__abrir"
        onClick={onSelecionar}
        aria-pressed={selecionado}
        aria-label={cardLabel}
        title={item.name}
      >
        {url ? (
          <LazyVideo
            src={url}
            poster={libraryThumbnailUrl(item.id)}
            playing={previewing}
            onEnded={() => setPreviewing(false)}
          />
        ) : (
          <div className="vcard__placeholder">
            {pending ? <span className="spinner" /> : <IconVideo width={24} height={24} />}
          </div>
        )}

        {/* Só aparece quando NÃO está pronto. Um selo "Pronto" em todo card
            seria ruído: pronto é o estado esperado. */}
        {!ready && (
          <span className={"vcard__estado vcard__estado--" + item.status}>
            {statusLabel(item.status)}
          </span>
        )}

        {item.favorito && (
          <span className="vcard__fav" aria-hidden="true">
            <IconStar width={14} height={14} fill="currentColor" />
          </span>
        )}

        {ready && durationLabel && (
          <span className="vcard__badge vcard__badge--duration" aria-hidden="true">
            {durationLabel}
          </span>
        )}

        {ready && (
          <span className="vcard__badge vcard__badge--produced" aria-hidden="true">
            {producedCount} {producedCount === 1 ? "gerado" : "gerados"}
          </span>
        )}
      </button>

      {ready && url && (
        <button
          type="button"
          className={"vcard__preview" + (previewing ? " vcard__preview--playing" : "")}
          aria-label={previewing ? `Parar prévia de ${item.name}` : `Reproduzir prévia de ${item.name}`}
          aria-pressed={previewing}
          title={previewing ? "Parar prévia" : "Reproduzir prévia"}
          onClick={(e) => {
            e.stopPropagation();
            setPreviewing((value) => !value);
          }}
          onPointerDown={(e) => e.stopPropagation()}
          draggable={false}
        >
          {previewing ? <IconPause width={18} height={18} /> : <IconPlay width={18} height={18} />}
        </button>
      )}
    </div>
  );
}
