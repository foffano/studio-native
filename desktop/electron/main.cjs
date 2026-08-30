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
  // Abrir a tela de autorizacao do TikTok no navegador do sistema.
  //
  // O OAuth precisa acontecer fora do app: dentro de uma BrowserWindow nossa,
  // nos teriamos acesso ao cookie de sessao do TikTok -- o TikTok recusa isso,
  // e com razao. Fora, quem digita a senha e o navegador do usuario, e nos so
  // recebemos o `code` de volta na 43117.
  //
  // A allowlist de host existe porque este canal atravessa o contextIsolation:
  // sem ela, qualquer script na janela poderia abrir qualquer coisa no
  // navegador do usuario, com um clique so.
  ipcMain.handle("shell:open-external", (_event, url) => {
    let parsed;
    try {
      parsed = new URL(String(url));
    } catch (_) {
      return { ok: false, error: "URL invalida" };
    }
    const hostOk =
      parsed.hostname === "tiktok.com" || parsed.hostname.endsWith(".tiktok.com");
    if (parsed.protocol !== "https:" || !hostOk) {
      console.warn("[StudioNative] openExternal recusado:", parsed.origin);
      return { ok: false, error: "Destino nao permitido" };
    }
    shell.openExternal(parsed.toString());
    return { ok: true };
  });

  ipcMain.handle("updates:install", () => {
    if (!isDev) autoUpdater.quitAndInstall(false, true);
    return updateState;
  });
}

// Porta preferida do modo navegador. Sortear uma porta livre a cada abertura
// funcionava enquanto so o Electron falava com o backend -- mas quem quer abrir
// o app no navegador (ou pelo celular, por um tunel) precisa de um endereco que
// nao mude. Tentamos esta primeiro e so sorteamos outra se estiver ocupada,
// porque nunca abrir o app seria um preco alto demais por um numero bonito.
const PORTA_PREFERIDA = 5050;

function portaLivre(porta) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", () => resolve(false));
    srv.listen(porta, "127.0.0.1", () => srv.close(() => resolve(true)));
  });
}

function portaSorteada() {
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

async function getFreePort() {
  if (await portaLivre(PORTA_PREFERIDA)) return PORTA_PREFERIDA;
  console.log(
    `[StudioNative] porta ${PORTA_PREFERIDA} ocupada; sorteando outra`
  );
  return portaSorteada();
}

/** Ja existe um Studio Native servindo nesta porta?
 *
 * Desde que o backend virou servico em segundo plano, a 5050 costuma estar
 * ocupada quando a janela abre -- e ai o Electron nao deve subir um segundo
 * backend. Dois processos contra o mesmo SQLite, e o backend recusando iniciar
 * pela guarda de porta, deixariam a janela sem nada para mostrar.
 *
 * Conferimos que quem responde e o proprio app, e nao qualquer coisa que
 * calhou de estar na porta.
 */
function backendJaRodando(porta) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port: porta, path: "/api/health", timeout: 1500 },
      (res) => {
        let corpo = "";
        res.on("data", (d) => (corpo += d));
        res.on("end", () => resolve(res.statusCode === 200 && corpo.includes("ok")));
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
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
  // Se o servico ja esta de pe na porta preferida, a janela apenas se conecta
  // a ele. Antes disso o Electron sempre subia o proprio backend, e com o
  // servico rodando os dois brigariam pela mesma porta e pelo mesmo banco.
  const reaproveitar = await backendJaRodando(PORTA_PREFERIDA);
  const port = reaproveitar ? PORTA_PREFERIDA : await getFreePort();
  backendUrl = `http://127.0.0.1:${port}`;
  process.env.STUDIO_BACKEND_URL = backendUrl;

  if (reaproveitar) {
    console.log(`[StudioNative] backend ja rodando em ${backendUrl}; reaproveitando`);
  } else {
    startBackend(port);
  }
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
