// Resolve a URL do backend Python (sidecar). No Electron vem via preload;
// rodando o Vite isolado (dev no navegador), usa a porta padrao 5050.
const bridgeUrl =
  typeof window !== "undefined" &&
  window.studioNative &&
  window.studioNative.backendUrl;

export const BACKEND = bridgeUrl || "http://127.0.0.1:5050";

export const isElectron =
  typeof window !== "undefined" &&
  !!(window.studioNative && window.studioNative.isElectron);

export const apiUrl = (p) => `${BACKEND}${p}`;
export const outputUrl = (file) => `${BACKEND}/outputs/${file}`;

async function jsonOrThrow(res) {
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    /* sem corpo JSON */
  }
  if (!res.ok) {
    const msg = (data && data.error) || `Erro ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export async function getConfig() {
  const res = await fetch(apiUrl("/api/config"));
  return jsonOrThrow(res);
}

export async function getSettings() {
  const res = await fetch(apiUrl("/api/settings"));
  return jsonOrThrow(res);
}

export async function saveSettings(payload) {
  const res = await fetch(apiUrl("/api/settings"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return jsonOrThrow(res);
}

export async function startGeneration(formData) {
  const res = await fetch(apiUrl("/api/generate"), {
    method: "POST",
    body: formData,
  });
  return jsonOrThrow(res);
}

export async function getStatus(jobId) {
  const res = await fetch(apiUrl(`/api/status/${jobId}`));
  return jsonOrThrow(res);
}
