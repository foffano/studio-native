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

export async function uploadToLibrary(file, onProgress) {
  // XMLHttpRequest continua sendo a API mais leve e confiável para progresso
  // de upload no navegador. `fetch` não expõe quantos bytes do body já foram
  // enviados, então uma barra feita com ele seria apenas uma animação falsa.
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("video", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("/api/library/upload"));
    xhr.withCredentials = true;
    xhr.responseType = "json";

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      const data = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress && onProgress(100);
        resolve(data);
        return;
      }
      if (xhr.status === 401 && (data.error === "nao_autenticado" || data.error === "sem_senha")) {
        window.dispatchEvent(new CustomEvent("studio:sem-sessao"));
      }
      reject(new Error(data.error || `Erro ${xhr.status}`));
    });
    xhr.addEventListener("error", () => reject(new Error("Falha de rede durante o upload.")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelado.")));
    xhr.send(fd);
  });
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
