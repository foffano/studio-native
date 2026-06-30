const HIST_KEY = "studio_native_history_v1";

export function loadHistory() {
  try {
    const raw = localStorage.getItem(HIST_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (_) {
    return [];
  }
}

export function saveHistory(list) {
  try {
    localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, 100)));
  } catch (_) {
    /* quota / indisponivel */
  }
}

export function addEntry(entry) {
  const list = loadHistory();
  list.unshift(entry);
  saveHistory(list);
  return list;
}

export function deleteEntry(id) {
  const list = loadHistory().filter((e) => e.id !== id);
  saveHistory(list);
  return list;
}

export function clearHistory() {
  saveHistory([]);
  return [];
}
