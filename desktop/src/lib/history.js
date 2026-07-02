const HIST_KEY = "studio_native_history_v1";
const TITLE_MAX = 28;

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

export function getEntryTitle(entry) {
  const theme = (entry.meta?.theme || "").trim();
  if (theme) {
    return theme.length > TITLE_MAX ? theme.slice(0, TITLE_MAX) + "…" : theme;
  }
  const name = entry.meta?.sourceName || "Nova geração";
  return name.length > TITLE_MAX ? name.slice(0, TITLE_MAX) + "…" : name;
}

export function formatHistoryDate(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "Ontem";
    const sameYear = d.getFullYear() === now.getFullYear();
    return d.toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "short",
      ...(sameYear ? {} : { year: "2-digit" }),
    });
  } catch (_) {
    return "";
  }
}
