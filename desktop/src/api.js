// Onde esta o backend. Sao duas situacoes:
//
// 1. **Vite em desenvolvimento**: o front esta em :5173 e o backend em :5050.
//    Origens diferentes, entao precisa da URL absoluta.
// 2. **Servido pelo proprio Flask** (producao, inclusive atraves do tunel):
//    **mesma origem**, string vazia. E isto que faz o app funcionar no celular
//    -- uma URL absoluta com 127.0.0.1 faria o telefone tentar conectar nele
//    mesmo.
const emDev =
  typeof import.meta !== "undefined" && import.meta.env && import.meta.env.DEV;

export const BACKEND = emDev ? "http://127.0.0.1:5050" : "";

export const apiUrl = (p) => `${BACKEND}${p}`;

/** `fetch` com cookie de sessao.
 *
 * `credentials` só vale "same-origin" por padrão. Em produção o Flask serve o
 * front, então bastaria; no Vite de desenvolvimento o front está em :5173 e a
 * API em :5050 — outra origem — e o cookie de sessão não seria enviado: todo
 * pedido voltaria 401 sem explicação. */
const req = (url, opts = {}) => fetch(url, { credentials: "include", ...opts });
export const outputUrl = (file) => `${BACKEND}/outputs/${file}`;

async function jsonOrThrow(res) {
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    /* sem corpo JSON */
  }
  if (!res.ok) {
    // Sessão caiu (expirou, serviço reiniciado, logout em outra aba). Avisamos
    // o app inteiro de uma vez: sem isto, cada tela mostraria seu próprio erro
    // críptico e nenhuma levaria de volta ao login.
    //
    // Mas só quando o backend diz que é falta de sessão. Nem todo 401 significa
    // isso: errar a senha atual no formulário de troca também responde 401, e
    // antes disso derrubava o usuário para a tela de login — punindo um erro de
    // digitação com a perda da sessão inteira.
    const semSessao =
      data && (data.error === "nao_autenticado" || data.error === "sem_senha");
    if (res.status === 401 && semSessao && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("studio:sem-sessao"));
    }
    const msg = (data && data.error) || `Erro ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export async function getConfig() {
  const res = await req(apiUrl("/api/config"));
  return jsonOrThrow(res);
}

export async function getSettings() {
  const res = await req(apiUrl("/api/settings"));
  return jsonOrThrow(res);
}

export async function saveSettings(payload) {
  const res = await req(apiUrl("/api/settings"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return jsonOrThrow(res);
}

export async function startGeneration(formData) {
  const res = await req(apiUrl("/api/generate"), {
    method: "POST",
    body: formData,
  });
  return jsonOrThrow(res);
}

export async function getStatus(jobId) {
  const res = await req(apiUrl(`/api/status/${jobId}`));
  return jsonOrThrow(res);
}

export const libraryVideoUrl = (file) => `${BACKEND}/library/${file}`;
export const libraryThumbnailUrl = (id) => `${BACKEND}/library-thumbs/${id}.jpg`;

// --- Upload para a Biblioteca, em pedaços ----------------------------------
// Atrás da Cloudflare (túnel ou VPS) uma requisição não passa de 100 MB no
// plano gratuito, e vídeo de celular passa disso fácil — a resposta seria um
// 413 sem explicação. O arquivo vai em pedaços do tamanho que o backend pedir,
// e um pedaço que falha por rede é reenviado sem perder o que já chegou.

const TENTATIVAS_POR_PEDACO = 4;

const esperar = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Queda de rede, timeout e erro do servidor costumam passar sozinhos; o resto
// (formato recusado, sessão caída) não passa tentando de novo.
const falhaPassageira = (status) =>
  status === 0 || status === 408 || status === 429 || status >= 500;

/** Envia um pedaço com XMLHttpRequest: `fetch` não expõe quantos bytes do
 * corpo já saíram, e uma barra feita com ele seria só uma animação falsa. */
function enviarPedaco(uploadId, pedaco, offset, onEnviados) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", apiUrl(`/api/library/upload/${uploadId}?offset=${offset}`));
    xhr.withCredentials = true;
    xhr.responseType = "json";
    xhr.setRequestHeader("Content-Type", "application/octet-stream");

    xhr.upload.addEventListener("progress", (event) => {
      if (onEnviados) onEnviados(event.loaded);
    });

    const falhar = (mensagem, status, data = {}) => {
      const erro = new Error(mensagem);
      erro.status = status;
      erro.data = data;
      reject(erro);
    };

    xhr.addEventListener("load", () => {
      const data = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
        return;
      }
      if (xhr.status === 401 && (data.error === "nao_autenticado" || data.error === "sem_senha")) {
        window.dispatchEvent(new CustomEvent("studio:sem-sessao"));
      }
      falhar(data.error || `Erro ${xhr.status} no envio`, xhr.status, data);
    });
    xhr.addEventListener("error", () => falhar("Falha de rede durante o upload.", 0));
    xhr.addEventListener("abort", () => falhar("Upload cancelado.", -1));
    xhr.send(pedaco);
  });
}

export async function uploadToLibrary(file, onProgress) {
  const inicio = await req(apiUrl("/api/library/upload/init"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: file.name, size: file.size }),
  });
  const { upload_id: uploadId, chunk_size: tamanhoDoPedaco } = await jsonOrThrow(inicio);

  const total = file.size;
  // A barra nunca anda para trás: um pedaço reenviado recomeça do zero, e sem
  // isto ela recuaria a cada nova tentativa. E fica em 99 até o backend
  // confirmar: 100% com o item ainda por criar pareceria concluído antes da hora.
  let ultimo = -1;
  const progresso = (bytes) => {
    const percentual = Math.min(99, Math.floor((bytes / total) * 100));
    if (percentual > ultimo) {
      ultimo = percentual;
      onProgress && onProgress(percentual);
    }
  };

  try {
    let offset = 0;
    let falhas = 0;
    while (offset < total) {
      const fim = Math.min(offset + tamanhoDoPedaco, total);
      try {
        const r = await enviarPedaco(uploadId, file.slice(offset, fim), offset, (enviados) =>
          progresso(offset + enviados)
        );
        offset = typeof r.recebido === "number" ? r.recebido : fim;
        falhas = 0;
      } catch (e) {
        // 409 com `recebido`: o backend tem outra conta de quanto já chegou (a
        // resposta de um pedaço anterior se perdeu). Continua de onde ele diz.
        const recebido = e.data && e.data.recebido;
        if (e.status === 409 && typeof recebido === "number" && recebido !== offset) {
          offset = recebido;
          continue;
        }
        falhas += 1;
        if (!falhaPassageira(e.status) || falhas >= TENTATIVAS_POR_PEDACO) throw e;
        await esperar(1000 * 2 ** (falhas - 1));
      }
      progresso(offset);
    }

    let data;
    for (let tentativa = 1; ; tentativa += 1) {
      try {
        const res = await req(apiUrl(`/api/library/upload/${uploadId}/complete`), {
          method: "POST",
        });
        data = await jsonOrThrow(res);
        break;
      } catch (e) {
        // `fetch` só rejeita com TypeError em falha de rede. Repetir é seguro:
        // o backend devolve o mesmo item se a conclusão já tinha acontecido.
        if (!(e instanceof TypeError) || tentativa >= 3) throw e;
        await esperar(1000 * tentativa);
      }
    }
    onProgress && onProgress(100);
    return data;
  } catch (e) {
    // Melhor-esforço: libera o arquivo parcial no backend.
    req(apiUrl(`/api/library/upload/${uploadId}`), { method: "DELETE" }).catch(() => {});
    throw e;
  }
}

export async function updateLibraryTags(id, tags) {
  const res = await req(apiUrl(`/api/library/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
  return jsonOrThrow(res);
}

export async function deleteLibraryItem(id) {
  const res = await req(apiUrl(`/api/library/${id}`), { method: "DELETE" });
  return jsonOrThrow(res);
}

// --- Catalogo de producao: os videos que o app gerou -----------------------

export async function getOutput(id) {
  const res = await req(apiUrl(`/api/outputs/${id}`));
  return jsonOrThrow(res);
}

export async function getOutputs(params = {}) {
  // `folder_id=""` significa "sem pasta" e precisa chegar ao backend; os outros
  // parâmetros vazios continuam sendo descartados, senão virariam filtros que
  // ninguém pediu.
  const qs = new URLSearchParams(
    Object.entries(params).filter(
      ([k, v]) => v != null && (v !== "" || k === "folder_id")
    )
  ).toString();
  const res = await req(apiUrl(`/api/outputs${qs ? `?${qs}` : ""}`));
  return jsonOrThrow(res);
}

export async function updateOutput(id, patch) {
  const res = await req(apiUrl(`/api/outputs/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow(res);
}

export async function deleteOutput(id) {
  const res = await req(apiUrl(`/api/outputs/${id}`), { method: "DELETE" });
  return jsonOrThrow(res);
}

export async function regenerateCaption(id) {
  const res = await req(apiUrl(`/api/outputs/${id}/caption`), {
    method: "POST",
  });
  return jsonOrThrow(res);
}

export async function importHistoryToBackend(entries) {
  const res = await req(apiUrl("/api/outputs/import"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
  });
  return jsonOrThrow(res);
}

export async function getMetrics() {
  const res = await req(apiUrl("/api/metrics"));
  return jsonOrThrow(res);
}

// --- Conta do TikTok -------------------------------------------------------
// O callback do OAuth nao passa por aqui: ele chega direto na porta 43117, num
// listener que o backend sobe so durante o login. Estas funcoes comandam o
// fluxo e perguntam como ele foi.

export async function getTikTokAccount() {
  const res = await req(apiUrl("/api/tiktok/account"));
  return jsonOrThrow(res);
}

export async function startTikTokConnect() {
  const res = await req(apiUrl("/api/tiktok/connect"), { method: "POST" });
  return jsonOrThrow(res);
}

export async function getTikTokConnectStatus() {
  const res = await req(apiUrl("/api/tiktok/connect/status"));
  return jsonOrThrow(res);
}

export async function cancelTikTokConnect() {
  const res = await req(apiUrl("/api/tiktok/connect"), { method: "DELETE" });
  return jsonOrThrow(res);
}

export async function disconnectTikTok(accountId = "") {
  const path = accountId
    ? `/api/tiktok/accounts/${encodeURIComponent(accountId)}`
    : "/api/tiktok/account";
  const res = await req(apiUrl(path), { method: "DELETE" });
  return jsonOrThrow(res);
}

/** Leva o usuário à tela de autorização do TikTok.
 *
 * Antes, no Electron, isto abria o navegador do sistema — dentro de uma janela nossa
 * teríamos acesso ao cookie de sessão do TikTok, e ele recusa isso.
 *
 * No navegador, navega **na própria aba** em vez de abrir outra. Abrir aba nova
 * depois de um `await` perde o vínculo com o clique do usuário, e o Safari do
 * iOS bloqueia como popup — justamente no celular, que é onde este caminho mais
 * importa. Navegar na mesma aba também é o fluxo normal de OAuth: o TikTok
 * devolve para o app, e a página de retorno traz de volta.
 */
export async function openAuthorizeUrl(url) {
  window.location.assign(url);
}

// --- Publicar no TikTok ----------------------------------------------------

export async function publishOutput(id, opts = {}) {
  const res = await req(apiUrl(`/api/outputs/${id}/publish`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  return jsonOrThrow(res);
}

export async function getPublication(pubId) {
  const res = await req(apiUrl(`/api/publications/${pubId}`));
  return jsonOrThrow(res);
}

export async function listPublications(state) {
  const q = state ? `?state=${encodeURIComponent(state)}` : "";
  const res = await req(apiUrl(`/api/publications${q}`));
  return jsonOrThrow(res);
}

/** Reconsulta um envio no TikTok — o desfecho depende de uma ação fora do app. */
export async function refreshPublication(pubId) {
  const res = await req(apiUrl(`/api/publications/${pubId}/refresh`), {
    method: "POST",
  });
  return jsonOrThrow(res);
}

/** Reconsulta de uma vez todos os envios que ainda aguardam ação no TikTok. */
export async function refreshPublications() {
  const res = await req(apiUrl("/api/publications/refresh"), { method: "POST" });
  return jsonOrThrow(res);
}

// --- Autenticação ----------------------------------------------------------

export async function getAuthStatus() {
  const res = await req(apiUrl("/api/auth/status"));
  return jsonOrThrow(res);
}

export async function setupPassword(senha) {
  const res = await req(apiUrl("/api/auth/setup"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha }),
  });
  return jsonOrThrow(res);
}

export async function login(senha) {
  const res = await req(apiUrl("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha }),
  });
  return jsonOrThrow(res);
}

export async function logout() {
  const res = await req(apiUrl("/api/auth/logout"), { method: "POST" });
  return jsonOrThrow(res);
}

export async function changePassword(atual, nova) {
  const res = await req(apiUrl("/api/auth/senha"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ atual, nova }),
  });
  return jsonOrThrow(res);
}

// --- Pastas, favoritos e lixeira -------------------------------------------

export async function getLibrary(opts = {}) {
  const q = new URLSearchParams();
  if (opts.secao) q.set("secao", opts.secao);
  if (opts.pasta !== undefined && opts.pasta !== null) q.set("pasta", opts.pasta);
  const s = q.toString();
  const res = await req(apiUrl(`/api/library${s ? "?" + s : ""}`));
  return jsonOrThrow(res);
}

export async function criarPasta(nome) {
  const res = await req(apiUrl("/api/folders"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome }),
  });
  return jsonOrThrow(res);
}

export async function renomearPasta(id, nome) {
  const res = await req(apiUrl(`/api/folders/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome }),
  });
  return jsonOrThrow(res);
}

export async function apagarPasta(id) {
  const res = await req(apiUrl(`/api/folders/${id}`), { method: "DELETE" });
  return jsonOrThrow(res);
}

export async function alternarFavorito(id) {
  const res = await req(apiUrl(`/api/library/${id}/favorito`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return jsonOrThrow(res);
}

export async function restaurarVideo(id) {
  const res = await req(apiUrl(`/api/library/${id}/restaurar`), { method: "POST" });
  return jsonOrThrow(res);
}

export async function esvaziarLixeira() {
  const res = await req(apiUrl("/api/library/lixeira"), { method: "DELETE" });
  return jsonOrThrow(res);
}

/** Move um vídeo-fonte para uma pasta (string vazia = sem pasta). */
export async function updateLibraryFolder(id, folderId) {
  const res = await req(apiUrl(`/api/library/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder_id: folderId }),
  });
  return jsonOrThrow(res);
}

export function downloadOutput(file) {
  // `download=1`: o backend manda como anexo, com o nome da frase.
  const a = document.createElement("a");
  a.href = apiUrl(`/outputs/${file}?download=1`);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export async function downloadOutputsZip(ids) {
  // Vários de uma vez viram um zip: o navegador bloqueia downloads em sequência.
  const res = await req(apiUrl("/api/outputs/download"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) {
    const erro = await res.json().catch(() => ({}));
    throw new Error(erro.error || "Não consegui preparar o zip.");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `studio-native-${ids.length}-videos.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function marcarPublicado(id, publicado = true) {
  return updateOutput(id, { published_manually: publicado });
}

// --- TikTok Shop (Central do Vendedor, pelo navegador do servidor) ----------

const postJson = (path, body) =>
  req(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).then(async (res) => (res.status === 204 ? null : jsonOrThrow(res)));

export const shopFrameUrl = (nonce) => apiUrl(`/api/shop/browser/frame?t=${nonce}`);

export async function getShopStatus() {
  return jsonOrThrow(await req(apiUrl("/api/shop/status")));
}

export const openShopBrowser = (shop) => postJson("/api/shop/browser", { shop });
export const addShop = () => postJson("/api/shop/shops");
export async function removeShop(shop) {
  return jsonOrThrow(await req(apiUrl(`/api/shop/shops/${shop}`), { method: "DELETE" }));
}
export const closeShopBrowser = () => postJson("/api/shop/browser/close");

/** Um clique, tecla ou arrasto de quem está olhando o navegador. */
export const sendShopInput = (comando) => postJson("/api/shop/browser/input", comando);

/** Resposta a um pedido de ajuda da automação: continuar, pular ou publicado. */
export const answerShop = (action) => postJson("/api/shop/attention", { action });

export async function getShopQueue() {
  return jsonOrThrow(await req(apiUrl("/api/shop/queue")));
}

export const enqueueShop = (payload) => postJson("/api/shop/queue", payload);
export const pauseShop = (paused) => postJson("/api/shop/queue/pause", { paused });
export const cancelShopItem = (id) => postJson(`/api/shop/queue/${id}/cancel`);
export const retryShopItem = (id) => postJson(`/api/shop/queue/${id}/retry`);

// Gravação de uma sessão real (para calibrar o roteiro da automação).
export const setShopRecording = (on) => postJson("/api/shop/recording", { on });
export const shopSnapshot = () => postJson("/api/shop/recording/snapshot");
export const shopRecordingUrl = () => apiUrl("/api/shop/recording/download");

// Catálogo do TikTok Shop e o vínculo produto ↔ vídeo.
export const shopThumbUrl = (id) => apiUrl(`/api/shop/products/${id}/thumb`);
export async function getShopProducts() {
  return jsonOrThrow(await req(apiUrl("/api/shop/products")));
}
export const syncShopProducts = (shop) => postJson("/api/shop/products/sync", { shop });
export async function linkShopProduct(kind, refId, shop, productId) {
  const res = await req(apiUrl("/api/shop/links"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, ref_id: refId, shop, product_id: productId || "" }),
  });
  return jsonOrThrow(res);
}
export const shopAvatarUrl = (handle) => apiUrl(`/api/shop/accounts/${handle}/avatar`);
