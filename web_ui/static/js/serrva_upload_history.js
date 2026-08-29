(() => {
  "use strict";

  const DB_NAME = "ua_recent_upload_history";
  const DB_VERSION = 1;
  const STORE_NAME = "runs";
  const FALLBACK_KEY = "ua_recent_upload_history_fallback";
  const MAX_RECORDS = 250;
  const MAX_OUTPUT_CHARS = 30000;
  const HISTORY_BUTTON_ATTR = "data-ua-upload-history-button";
  const MODAL_ID = "ua-upload-history-modal";

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

  const stripAnsi = (value) =>
    String(value || "").replace(/\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g, "");

  const plainTextFromHtml = (html) => {
    const container = document.createElement("div");
    container.innerHTML = String(html || "");
    container.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
    container.querySelectorAll("pre, p, div").forEach((node) => node.append("\n"));
    return stripAnsi(container.textContent || "");
  };

  const parseRequestBody = (options) => {
    try {
      const body = options?.body;
      if (!body) return {};
      if (typeof body === "string") return JSON.parse(body);
      if (body instanceof URLSearchParams) return Object.fromEntries(body.entries());
    } catch (_error) {
      // History recording must never interfere with an upload.
    }
    return {};
  };

  const parseTrackersFromArgs = (args, output) => {
    const value = String(args || "");
    const match = value.match(/(?:^|\s)(?:-tk|--trackers)(?:=|\s+)(?:"([^"]+)"|'([^']+)'|([^\s]+))/i);
    if (match) {
      return String(match[1] || match[2] || match[3] || "")
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean);
    }

    const normalized = String(output || "").replace(/\s+/g, " ");
    const listMatch = normalized.match(/Trackers list before editing:\s*\[([^\]]+)\]/i);
    if (!listMatch) return [];
    return listMatch[1]
      .split(",")
      .map((item) => item.replace(/["']/g, "").trim().toUpperCase())
      .filter(Boolean);
  };

  const basenameTitle = (path) => {
    const parts = String(path || "").replace(/\\/g, "/").split("/").filter(Boolean);
    return parts[parts.length - 1] || "Unknown upload";
  };

  const firstMatch = (text, patterns) => {
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match?.[1]) return match[1].trim();
    }
    return "";
  };

  const summarizeExecution = ({ payload, output, exitCode, hadError, startedAt }) => {
    const args = String(payload?.args || "");
    const path = String(payload?.path || "");
    const normalized = String(output || "").replace(/\s+/g, " ").trim();
    const trackers = parseTrackersFromArgs(args, normalized);
    const debug = /(?:^|\s)--debug(?:\s|$)/i.test(args) || /DEBUG:\s*True\s*-\s*Will not actually upload/i.test(normalized);

    let status = "uploaded";
    if (hadError || Number(exitCode) !== 0) status = "failed";
    else if (/\bDupe:\s*Yes\b/i.test(normalized)) status = "dupe";
    else if (/\bSkipped:\s*Yes\b/i.test(normalized) || /\bBanned:\s*Yes\b/i.test(normalized)) status = "skipped";
    else if (debug) status = "dry_run";

    const finalTitle = firstMatch(normalized, [
      /['"]name['"]\s*:\s*['"]([^'"]{3,300})['"]/i,
      /(?:^|\s)[A-Z0-9][A-Z0-9_-]{1,20}:\s+([^|]{3,300}?)(?=\s+(?:INFO|DEBUG|Tracker Processing Summary|Searching for existing|$))/i,
      /Base Name:\s+(.{3,300}?)(?=\s+(?:INFO|DEBUG|$))/i,
    ]);

    const source = firstMatch(normalized, [
      /Source\.*\s+(.+?)(?=\s+Type\.*|\s+Group Tag\.|\s+INFO|$)/i,
    ]);
    const type = firstMatch(normalized, [/Type\.*\s+([A-Z0-9_-]+)/i]);
    const group = firstMatch(normalized, [/Group Tag\.\s*([A-Za-z0-9._-]+)/i]);

    const completedAt = new Date().toISOString();
    const durationSeconds = Math.max(
      0,
      Math.round((Date.parse(completedAt) - Date.parse(startedAt)) / 1000),
    );

    return {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      createdAt: startedAt,
      completedAt,
      durationSeconds,
      status,
      mode: debug ? "dry_run" : "live",
      path,
      displayTitle: finalTitle || basenameTitle(path),
      finalTitle,
      trackers,
      source,
      type,
      group,
      args,
      exitCode: Number.isFinite(Number(exitCode)) ? Number(exitCode) : null,
      output: String(output || "").slice(-MAX_OUTPUT_CHARS),
    };
  };

  const openDb = () =>
    new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        reject(new Error("IndexedDB unavailable"));
        return;
      }
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onerror = () => reject(request.error || new Error("Unable to open history DB"));
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
          store.createIndex("createdAt", "createdAt", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
    });

  const fallbackRead = () => {
    try {
      const value = JSON.parse(localStorage.getItem(FALLBACK_KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_error) {
      return [];
    }
  };

  const fallbackWrite = (records) => {
    try {
      localStorage.setItem(FALLBACK_KEY, JSON.stringify(records.slice(0, MAX_RECORDS)));
    } catch (_error) {
      // Ignore quota failures: upload execution remains authoritative.
    }
  };

  const saveRecord = async (record) => {
    try {
      const db = await openDb();
      await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        tx.objectStore(STORE_NAME).put(record);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error || new Error("Unable to save history"));
      });

      const records = await readRecords();
      if (records.length > MAX_RECORDS) {
        const stale = records.slice(MAX_RECORDS);
        await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE_NAME, "readwrite");
          const store = tx.objectStore(STORE_NAME);
          stale.forEach((item) => store.delete(item.id));
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error || new Error("Unable to trim history"));
        });
      }
      db.close();
    } catch (_error) {
      const records = fallbackRead();
      fallbackWrite([record, ...records.filter((item) => item.id !== record.id)]);
    }
  };

  const readRecords = async () => {
    try {
      const db = await openDb();
      const records = await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const request = tx.objectStore(STORE_NAME).getAll();
        request.onsuccess = () => resolve(Array.isArray(request.result) ? request.result : []);
        request.onerror = () => reject(request.error || new Error("Unable to read history"));
      });
      db.close();
      return records.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    } catch (_error) {
      return fallbackRead().sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    }
  };

  const collectExecution = async (response, payload) => {
    const startedAt = new Date().toISOString();
    let output = "";
    let exitCode = null;
    let hadError = false;
    let pending = "";

    const consumeEvent = (rawEvent) => {
      const dataLines = rawEvent
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());
      if (!dataLines.length) return;
      try {
        const event = JSON.parse(dataLines.join("\n"));
        if (event.type === "html") output += plainTextFromHtml(event.data);
        else if (event.type === "system") output += `${String(event.data || "")}\n`;
        else if (event.type === "error") {
          hadError = true;
          output += `${String(event.data || "Execution error")}\n`;
        } else if (event.type === "exit") {
          exitCode = Number(event.code);
        }
        if (output.length > MAX_OUTPUT_CHARS * 4) {
          output = output.slice(-MAX_OUTPUT_CHARS * 2);
        }
      } catch (_error) {
        // Ignore malformed/keepalive SSE events.
      }
    };

    try {
      if (!response.body?.getReader) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        pending += decoder.decode(value || new Uint8Array(), { stream: !done });
        let boundary = pending.search(/\r?\n\r?\n/);
        while (boundary >= 0) {
          const eventText = pending.slice(0, boundary);
          const separator = pending.slice(boundary).match(/^\r?\n\r?\n/)?.[0] || "\n\n";
          pending = pending.slice(boundary + separator.length);
          consumeEvent(eventText);
          boundary = pending.search(/\r?\n\r?\n/);
        }
        if (done) break;
      }
      if (pending.trim()) consumeEvent(pending);
    } catch (_error) {
      hadError = true;
    }

    const record = summarizeExecution({ payload, output, exitCode, hadError, startedAt });
    await saveRecord(record);
    window.dispatchEvent(new CustomEvent("ua-upload-history-updated", { detail: record }));
  };

  const installFetchCapture = () => {
    const originalApiFetch = window.uaApiFetch;
    if (typeof originalApiFetch !== "function" || originalApiFetch.__uaHistoryWrapped) return;

    const wrapped = async (url, options = {}) => {
      const response = await originalApiFetch(url, options);
      try {
        const parsed = new URL(String(url), window.location.href);
        const method = String(options?.method || "GET").toUpperCase();
        if (method === "POST" && parsed.pathname.endsWith("/api/execute") && response.ok) {
          const payload = parseRequestBody(options);
          const clone = response.clone();
          void collectExecution(clone, payload);
        }
      } catch (_error) {
        // The capture layer is intentionally fail-open.
      }
      return response;
    };
    wrapped.__uaHistoryWrapped = true;
    wrapped.__uaHistoryOriginal = originalApiFetch;
    window.uaApiFetch = wrapped;
  };

  const statusLabel = (status) =>
    ({
      uploaded: "Uploaded",
      dry_run: "Dry Run",
      dupe: "Dupe",
      skipped: "Skipped",
      failed: "Failed",
    })[status] || String(status || "Unknown");

  const formatDate = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
  };

  const formatDuration = (seconds) => {
    const value = Number(seconds || 0);
    if (value < 60) return `${value}s`;
    return `${Math.floor(value / 60)}m ${value % 60}s`;
  };

  let cachedRecords = [];
  let expandedId = "";

  const modal = () => document.getElementById(MODAL_ID);

  const filteredRecords = () => {
    const root = modal();
    if (!root) return [];
    const status = root.querySelector("[data-history-status]")?.value || "all";
    const tracker = root.querySelector("[data-history-tracker]")?.value || "all";
    const search = (root.querySelector("[data-history-search]")?.value || "").trim().toLowerCase();
    const limit = Number(root.querySelector("[data-history-limit]")?.value || 50);

    return cachedRecords
      .filter((item) => status === "all" || item.status === status)
      .filter((item) => tracker === "all" || (item.trackers || []).includes(tracker))
      .filter((item) => {
        if (!search) return true;
        return [item.displayTitle, item.path, item.group, item.source, item.type, ...(item.trackers || [])]
          .join(" ")
          .toLowerCase()
          .includes(search);
      })
      .slice(0, limit);
  };

  const renderHistoryRows = () => {
    const root = modal();
    if (!root) return;
    const list = root.querySelector("[data-history-list]");
    if (!list) return;
    const records = filteredRecords();

    if (!records.length) {
      list.innerHTML = '<div class="ua-history-empty">No matching uploads recorded yet.</div>';
      return;
    }

    list.innerHTML = records
      .map((item) => {
        const open = expandedId === item.id;
        const trackers = (item.trackers || []).join(", ") || "—";
        const details = open
          ? `<div class="ua-history-details">
              <div><strong>Path:</strong> <code>${escapeHtml(item.path || "—")}</code></div>
              <div><strong>Final title:</strong> ${escapeHtml(item.finalTitle || item.displayTitle || "—")}</div>
              <div><strong>Tracker:</strong> ${escapeHtml(trackers)}</div>
              <div><strong>Mode:</strong> ${escapeHtml(item.mode === "dry_run" ? "Dry Run" : "Live")}</div>
              <div><strong>Source / Type / Group:</strong> ${escapeHtml(item.source || "—")} / ${escapeHtml(item.type || "—")} / ${escapeHtml(item.group || "—")}</div>
              <div><strong>Exit code:</strong> ${escapeHtml(item.exitCode ?? "—")}</div>
              <div><strong>Arguments:</strong> <code>${escapeHtml(item.args || "—")}</code></div>
              <details><summary>Execution output</summary><pre>${escapeHtml(item.output || "No output captured.")}</pre></details>
            </div>`
          : "";
        return `<article class="ua-history-row" data-history-row="${escapeHtml(item.id)}">
          <button type="button" class="ua-history-row-main" data-history-toggle="${escapeHtml(item.id)}">
            <span class="ua-history-time">${escapeHtml(formatDate(item.completedAt || item.createdAt))}</span>
            <span class="ua-history-title" title="${escapeHtml(item.displayTitle)}">${escapeHtml(item.displayTitle)}</span>
            <span class="ua-history-tracker">${escapeHtml(trackers)}</span>
            <span class="ua-history-meta">${escapeHtml([item.source, item.type, item.group].filter(Boolean).join(" · ") || "—")}</span>
            <span class="ua-history-duration">${escapeHtml(formatDuration(item.durationSeconds))}</span>
            <span class="ua-history-status ua-history-status-${escapeHtml(item.status)}">${escapeHtml(statusLabel(item.status))}</span>
          </button>
          ${details}
        </article>`;
      })
      .join("");
  };

  const renderSummary = () => {
    const root = modal();
    if (!root) return;
    const summary = root.querySelector("[data-history-summary]");
    if (!summary) return;
    const counts = cachedRecords.reduce((acc, item) => {
      acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    }, {});
    summary.textContent = `${counts.uploaded || 0} uploaded · ${counts.dry_run || 0} dry runs · ${counts.failed || 0} failed · ${counts.dupe || 0} dupes/skipped`;
  };

  const populateTrackerFilter = () => {
    const root = modal();
    const select = root?.querySelector("[data-history-tracker]");
    if (!select) return;
    const selected = select.value;
    const trackers = [...new Set(cachedRecords.flatMap((item) => item.trackers || []))].sort();
    select.innerHTML = '<option value="all">All trackers</option>' + trackers.map((tracker) => `<option value="${escapeHtml(tracker)}">${escapeHtml(tracker)}</option>`).join("");
    if (["all", ...trackers].includes(selected)) select.value = selected;
  };

  const refreshHistory = async () => {
    cachedRecords = await readRecords();
    populateTrackerFilter();
    renderSummary();
    renderHistoryRows();
  };

  const closeHistory = () => {
    const root = modal();
    if (root) root.classList.remove("ua-history-open");
  };

  const openHistory = async () => {
    ensureModal();
    modal()?.classList.add("ua-history-open");
    await refreshHistory();
  };

  const ensureModal = () => {
    if (modal()) return;
    const root = document.createElement("div");
    root.id = MODAL_ID;
    root.innerHTML = `
      <div class="ua-history-backdrop" data-history-close></div>
      <section class="ua-history-modal" role="dialog" aria-modal="true" aria-labelledby="ua-history-title">
        <header class="ua-history-header">
          <div>
            <h2 id="ua-history-title">Recent Uploads</h2>
            <p data-history-summary>Loading history…</p>
          </div>
          <button type="button" class="ua-history-close" data-history-close aria-label="Close upload history">×</button>
        </header>
        <div class="ua-history-filters">
          <input type="search" data-history-search placeholder="Search title, path, group…" aria-label="Search upload history" />
          <select data-history-status aria-label="Filter by status">
            <option value="all">All statuses</option>
            <option value="uploaded">Uploaded</option>
            <option value="dry_run">Dry Run</option>
            <option value="dupe">Dupe</option>
            <option value="skipped">Skipped</option>
            <option value="failed">Failed</option>
          </select>
          <select data-history-tracker aria-label="Filter by tracker"><option value="all">All trackers</option></select>
          <select data-history-limit aria-label="Number of recent uploads">
            <option value="25">25</option>
            <option value="50" selected>50</option>
            <option value="100">100</option>
            <option value="250">250</option>
          </select>
        </div>
        <div class="ua-history-columns" aria-hidden="true">
          <span>Time</span><span>Title</span><span>Tracker</span><span>Source / Type / Group</span><span>Duration</span><span>Status</span>
        </div>
        <div class="ua-history-list" data-history-list></div>
        <footer class="ua-history-footer">History is kept in this browser and survives container updates and restarts. Up to ${MAX_RECORDS} executions are retained.</footer>
      </section>`;
    document.body.appendChild(root);

    root.querySelectorAll("[data-history-close]").forEach((node) => node.addEventListener("click", closeHistory));
    root.querySelectorAll("select, input").forEach((node) => node.addEventListener("input", renderHistoryRows));
    root.addEventListener("click", (event) => {
      const toggle = event.target.closest?.("[data-history-toggle]");
      if (!toggle) return;
      expandedId = expandedId === toggle.dataset.historyToggle ? "" : toggle.dataset.historyToggle;
      renderHistoryRows();
    });
  };

  const historyIcon = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="w-5 h-5" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 2m6-2a9 9 0 11-3-6.7M21 4v5h-5" />
    </svg>`;

  const ensureHistoryButtons = () => {
    document.querySelectorAll('a[aria-label="Config"]').forEach((configLink) => {
      const parent = configLink.parentElement;
      if (!parent || parent.querySelector(`[${HISTORY_BUTTON_ATTR}]`)) return;
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute(HISTORY_BUTTON_ATTR, "1");
      button.setAttribute("aria-label", "Recent Uploads");
      button.title = "Recent Uploads";
      button.className = configLink.className;
      button.innerHTML = historyIcon;
      button.addEventListener("click", openHistory);
      parent.insertBefore(button, configLink);
    });
  };

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal()?.classList.contains("ua-history-open")) closeHistory();
  });

  window.addEventListener("ua-upload-history-updated", () => {
    if (modal()?.classList.contains("ua-history-open")) void refreshHistory();
  });

  installFetchCapture();
  ensureModal();
  ensureHistoryButtons();

  const observer = new MutationObserver(() => ensureHistoryButtons());
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
