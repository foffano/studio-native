const { contextBridge } = require("electron");

function readBackendUrl() {
  // 1) via env (definido pelo main antes de criar a janela)
  if (process.env.STUDIO_BACKEND_URL) return process.env.STUDIO_BACKEND_URL;
  // 2) via additionalArguments (--backend-url=...)
  const arg = (process.argv || []).find((a) => a.startsWith("--backend-url="));
  if (arg) return arg.split("=").slice(1).join("=");
  return "";
}

contextBridge.exposeInMainWorld("studioNative", {
  backendUrl: readBackendUrl(),
  isElectron: true,
  platform: process.platform,
});
