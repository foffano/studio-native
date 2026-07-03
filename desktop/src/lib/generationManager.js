import { upsertEntry, updateEntry, loadHistory } from "./history.js";
import { startGeneration, getStatus } from "../api.js";

const polls = new Map();
const listeners = new Set();

export function subscribeGeneration(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  listeners.forEach((fn) => fn());
}

export function resumeRunningGenerations() {
  loadHistory()
    .filter((e) => e.status === "running")
    .forEach((e) => startPolling(e.id));
}

export async function beginGeneration(fd, meta) {
  const { job_id } = await startGeneration(fd);
  const entry = {
    id: job_id,
    date: new Date().toISOString(),
    meta,
    results: [],
    status: "running",
    progress: 4,
    statusMsg: meta.fromLibrary
      ? "Iniciando com vídeo da biblioteca..."
      : "Enviando vídeo...",
    jobStatus: "queued",
    error: "",
  };
  upsertEntry(entry);
  emit();
  startPolling(job_id);
  return { job_id, entry };
}

export function startPolling(jobId) {
  if (polls.has(jobId)) return;

  const tick = async () => {
    try {
      const j = await getStatus(jobId);
      const patch = {
        statusMsg: j.message || j.status || "",
        jobStatus: j.status || "",
        progress: j.progress || 0,
        results: j.results || [],
      };
      if (j.status === "done") {
        stopPolling(jobId);
        updateEntry(jobId, { ...patch, status: "done", progress: 100 });
      } else if (j.status === "error") {
        stopPolling(jobId);
        updateEntry(jobId, {
          ...patch,
          status: "error",
          error: j.message || "Erro na geração.",
        });
      } else {
        updateEntry(jobId, { ...patch, status: "running" });
      }
      emit();
    } catch (e) {
      stopPolling(jobId);
      updateEntry(jobId, {
        status: "error",
        error: "Falha ao consultar status: " + e.message,
      });
      emit();
    }
  };

  tick();
  polls.set(jobId, setInterval(tick, 800));
}

export function stopPolling(jobId) {
  const handle = polls.get(jobId);
  if (handle) clearInterval(handle);
  polls.delete(jobId);
}
