// Resolve onde esta o backend Python. Sao tres situacoes, e a ordem importa:
//
// 1. **Electron**: a URL chega pelo preload, porque o backend sobe numa porta
//    sorteada e o renderer e carregado de file://.
// 2. **Vite dev no navegador**: nao ha ponte, e o front esta em :5173 enquanto
//    o backend esta em :5050. Precisa da URL absoluta.
// 3. **Servido pelo proprio Flask** (modo navegador, inclusive atraves de um
//    tunel): usa a **mesma origem**, string vazia. Isto e o que faz o app
//    funcionar no celular -- uma URL absoluta com 127.0.0.1 faria o telefone
//    tentar conectar nele mesmo.
const bridgeUrl =
  typeof window !== "undefined" &&
  window.studioNative &&
  window.studioNative.backendUrl;

const emDev =
  typeof import.meta !== "undefined" && import.meta.env && import.meta.env.DEV;

export const BACKEND = bridgeUrl || (emDev ? "http://127.0.0.1:5050" : "");

export const isElectron =
  typeof window !== "undefined" &&
  !!(window.studioNative && window.studioNative.isElectron);

export const apiUrl = (p) => `${BACKEND}${p}`;

/** `fetch` com cookie de sessao.
 *
 * `credentials` só vale "same-origin" por padrão. Servido pelo Flask isso
 * bastaria, mas no Electron o front fala com `http://127.0.0.1:<porta>` — outra
 * origem — e o cookie de sessão simplesmente não seria enviado: todo pedido
 * voltaria 401 sem explicação. */
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
    if (res.status === 401 && typeof window !== "undefined") {
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

export async function getLibrary() {
  const res = await req(apiUrl("/api/library"));
  return jsonOrThrow(res);
}

export async function uploadToLibrary(file) {
  const fd = new FormData();
  fd.append("video", file);
  const res = await req(apiUrl("/api/library/upload"), {
    method: "POST",
    body: fd,
  });
  return jsonOrThrow(res);
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
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== "" && v != null)
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

export async function disconnectTikTok() {
  const res = await req(apiUrl("/api/tiktok/account"), { method: "DELETE" });
  return jsonOrThrow(res);
}

/** Abre a autorizacao no navegador do sistema.
 *
 * Fora do Electron (dev no navegador) cai em window.open, que serve para
 * testar o fluxo sem empacotar o app.
 */
export async function openAuthorizeUrl(url) {
  const bridge = typeof window !== "undefined" && window.studioNative;
  if (bridge && bridge.openExternal) {
    const r = await bridge.openExternal(url);
    if (!r || !r.ok) throw new Error((r && r.error) || "Nao foi possivel abrir o navegador");
    return;
  }
  window.open(url, "_blank", "noopener");
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
