const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const net = require("net");
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const { autoUpdater } = require("electron-updater");

const isDev = !app.isPackaged || process.env.STUDIO_DEV === "1";

let mainWindow = null;
let backendProc = null;
let backendUrl = "";
let updateState = {
  status: "idle",
  message: "Nenhuma verificacao iniciada.",
  info: null,
  progress: null,
};

autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = true;

function sendUpdateState(patch) {
  updateState = Object.assign({}, updateState, patch);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("updates:state", updateState);
  }
  return updateState;
}

function setupAutoUpdater() {
  autoUpdater.on("checking-for-update", () => {
    sendUpdateState({
      status: "checking",
      message: "Verificando atualizacoes...",
      progress: null,
    });
  });
  autoUpdater.on("update-available", (info) => {
    sendUpdateState({
      status: "available",
      message: `Atualizacao ${info.version} disponivel.`,
      info,
      progress: null,
    });
  });
  autoUpdater.on("update-not-available", (info) => {
    sendUpdateState({
      status: "none",
      message: "Voce ja esta na versao mais recente.",
      info,
      progress: null,
    });
  });
  autoUpdater.on("download-progress", (progress) => {
    sendUpdateState({
      status: "downloading",
      message: `Baixando atualizacao... ${Math.round(progress.percent || 0)}%`,
      progress,
    });
  });
  autoUpdater.on("update-downloaded", (info) => {
    sendUpdateState({
      status: "downloaded",
      message: "Atualizacao baixada. Reinicie para instalar.",
      info,
      progress: null,
    });
  });
  autoUpdater.on("error", (err) => {
    sendUpdateState({
      status: "error",
      message: err && err.message ? err.message : "Falha ao verificar atualizacoes.",
      progress: null,
    });
  });

  ipcMain.handle("updates:get-state", () => updateState);
  ipcMain.handle("updates:check", async () => {
    if (isDev) {
      return sendUpdateState({
        status: "disabled",
        message: "Atualizacoes automaticas ficam ativas no app instalado.",
      });
    }
    await autoUpdater.checkForUpdates();
    return updateState;
  });
  ipcMain.handle("updates:download", async () => {
    if (isDev) return updateState;
    await autoUpdater.downloadUpdate();
    return updateState;
  });
  ipcMain.handle("updates:install", () => {
    if (!isDev) autoUpdater.quitAndInstall(false, true);
    return updateState;
  });
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function repoRoot() {
  // desktop/electron/main.cjs -> repo root (dois niveis acima)
  return path.resolve(__dirname, "..", "..");
}

function backendCommand(port) {
  const env = Object.assign({}, process.env, {
    STUDIO_PORT: String(port),
    STUDIO_HOST: "127.0.0.1",
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  });

  if (isDev) {
    const py = process.env.STUDIO_PYTHON || "python";
    return { cmd: py, args: [path.join(repoRoot(), "app.py")], env, cwd: repoRoot() };
  }

  const exeName =
    process.platform === "win32"
      ? "StudioNativeBackend.exe"
      : "StudioNativeBackend";
  const exe = path.join(process.resourcesPath, "backend", exeName);
  return { cmd: exe, args: [], env, cwd: path.dirname(exe) };
}

function startBackend(port) {
  const { cmd, args, env, cwd } = backendCommand(port);
  console.log("[StudioNative] iniciando backend:", cmd, args.join(" "));
  backendProc = spawn(cmd, args, { env, cwd, windowsHide: true });
  backendProc.stdout.on("data", (d) =>
    process.stdout.write(`[backend] ${d}`)
  );
  backendProc.stderr.on("data", (d) =>
    process.stderr.write(`[backend] ${d}`)
  );
  backendProc.on("exit", (code) =>
    console.log(`[StudioNative] backend saiu com codigo ${code}`)
  );
}

function waitForHealth(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url + "/api/health", (res) => {
        if (res.statusCode === 200) {
          res.resume();
          return resolve(true);
        }
        res.resume();
        retry();
      });
      req.on("error", retry);
      req.setTimeout(2000, () => req.destroy());
    };
    const retry = () => {
      if (Date.now() > deadline) {
        return reject(new Error("backend nao respondeu a tempo"));
      }
      setTimeout(tick, 350);
    };
    tick();
  });
}

async function createWindow() {
  const port = await getFreePort();
  backendUrl = `http://127.0.0.1:${port}`;
  process.env.STUDIO_BACKEND_URL = backendUrl;

  startBackend(port);
  try {
    await waitForHealth(backendUrl, 40000);
    console.log("[StudioNative] backend pronto em", backendUrl);
  } catch (e) {
    console.error("[StudioNative]", e.message);
  }

  mainWindow = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0e1726",
    title: "Studio Native",
    icon: path.join(__dirname, "..", "build", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--backend-url=${backendUrl}`],
    },
  });

  mainWindow.removeMenu();

  // Abrir links externos no navegador padrao, nao numa janela do app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    await mainWindow.loadURL("http://127.0.0.1:5173");
    // mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    const indexFile = path.join(__dirname, "..", "dist", "index.html");
    if (!fs.existsSync(indexFile)) {
      console.error("[StudioNative] dist/index.html ausente. Rode `npm run build`.");
    }
    await mainWindow.loadFile(indexFile);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function stopBackend() {
  if (backendProc && !backendProc.killed) {
    try {
      backendProc.kill();
    } catch (_) {}
    backendProc = null;
  }
}

app.whenReady().then(createWindow);
setupAutoUpdater();

app.whenReady().then(() => {
  if (!isDev) {
    setTimeout(() => {
      autoUpdater.checkForUpdates().catch((err) => {
        sendUpdateState({
          status: "error",
          message: err && err.message ? err.message : "Falha ao verificar atualizacoes.",
        });
      });
    }, 5000);
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopBackend);
app.on("will-quit", stopBackend);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

process.on("exit", stopBackend);
