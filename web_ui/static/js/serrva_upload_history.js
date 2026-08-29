// Serrva Web UI upload history.
//
// This is intentionally isolated from upstream app.js. It wraps the existing
// authenticated API helper before app.js captures it, observes /api/execute
// streams through Response.clone(), stores a compact structured summary in the
// browser, and renders a standalone Recent Uploads panel. No upload behavior is
// changed and the original response is always returned untouched to app.js.
(() => {
  const originalApiFetch = window.uaApiFetch;
  if (typeof originalApiFetch !== "function") return;

  const STORAGE_KEY = "ua_serrva_upload_history_v1";
  const MAX_ENTRIES = 250;
  const MAX_OUTPUT_CHARS = 50000;
  const HISTORY_EVENT = "ua:upload-history-updated";

  const safeJsonParse = (value, fallback = null) => {
    try {
      return JSON.parse(value);
    } catch (_error) {
      return fallback;
    }
  };

  const loadHistory = () => {
    try {
      const parsed = safeJsonParse(window.localStorage.getItem(STORAGE_KEY), []);
      return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") : [];
    } catch (_error) {
      return [];
    }
  };

  const saveHistory = (entries) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
      window.dispatchEvent(new CustomEvent(HISTORY_EVENT));
    } catch (error) {
      console.warn("Could not persist upload history:", error);
    }
  };

  const upsertHistory = (entry) => {
    const history = loadHistory();
    const next = [entry, ...history.filter((item) => item.id !== entry.id)].slice(0, MAX_ENTRIES);
    saveHistory(next);
  };

  const basename = (path) => {
    const text = String(path || "").replace(/[\\/]+$/, "");
    const parts = text.split(/[\\/]/);
    return parts[parts.length - 1] || text || "Upload";
  };

  const stripHtml = (html) => {
    const text = String(html || "");
    if (!text) return "";
    try {
      const doc = new DOMParser().parseFromString(text, "text/html");
      return String(doc.body?.textContent || "");
    } catch (_error) {
      return text.replace(/<[^>]*>/g, " ");
    }
  };

  const normalizeOutput = (value) =>
    String(value || "")
      .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
      .replace(/\r/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .slice(-MAX_OUTPUT_CHARS);

  const parseTrackers = (args) => {
    const text = String(args || "");
    const match = text.match(/(?:^|\s)(?:-tk|--trackers)(?:=|\s+)(?:"([^"]+)"|'([^']+)'|([^\s]+))/i);
    const raw = match ? match[1] || match[2] || match[3] || "" : "";
    return raw
      .split(/[,+]/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  };

  const extractFirst = (text, patterns) => {
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match?.[1]) return String(match[1]).trim();
    }
    return "";
  };

  const escapeRegex = (value) => String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  const extractTrackerTitles = (text, trackers) => {
    const titles = [];
    const seen = new Set();
    for (const tracker of trackers) {
      const escaped = escapeRegex(tracker);
      const patterns = [
        new RegExp(`${escaped}:\\s*Request Data:[\\s\\S]{0,900}?'name'\\s*:\\s*'([^']+)'`, "i"),
        new RegExp(`${escaped}:\\s+([^\\n]{12,220}(?:-[A-Za-z0-9._]+)?)`, "i"),
      ];
      const title = extractFirst(text, patterns);
      if (title && !seen.has(title)) {
        seen.add(title);
        titles.push({ tracker, title });
      }
    }
    return titles;
  };

  const extractTrackerResults = (text) => {
    const results = [];
    const regex = /Tracker:\s*([A-Z0-9._-]+)\s*\|\s*Banned:\s*(Yes|No)\s*\|\s*Skipped:\s*(Yes|No)\s*\|\s*Dupe:\s*(Yes|No)\s*\|\s*Upload:\s*(Yes|No)/gi;
    let match;
    while ((match = regex.exec(text)) !== null) {
      results.push({
        tracker: match[1].toUpperCase(),
        banned: match[2].toLowerCase() === "yes",
        skipped: match[3].toLowerCase() === "yes",
        dupe: match[4].toLowerCase() === "yes",
        upload: match[5].toLowerCase() === "yes",
      });
    }
    return results;
  };

  const summarizeExecution = (entry, output, exitCode, aborted = false) => {
    const text = normalizeOutput(output);
    const debug = /(?:^|\s)--debug(?:\s|$)/i.test(entry.args || "") || /DEBUG MODE does not upload|Debug mode enabled, not uploading/i.test(text);
    const trackerResults = extractTrackerResults(text);
    let status = "completed";
    if (aborted) status = "cancelled";
    else if (Number.isInteger(exitCode) && exitCode !== 0) status = "failed";
    else if (debug) status = "dry-run";
    else if (trackerResults.some((item) => item.banned || item.skipped || item.dupe || !item.upload)) status = "skipped";
    else if (/successfully uploaded|upload(?:ed)?\s+(?:success|complete)|torrent uploaded/i.test(text)) status = "uploaded";

    const group = extractFirst(text, [/Group Tag\.\s*([^\n]+)/i, /release group ['"]?-?([A-Za-z0-9._-]+)['"]?/i]);
    const source = extractFirst(text, [/Source\.\.\.\.\s*([^\n]+)/i]);
    const type = extractFirst(text, [/Type\.\.\.\.\.\.\s*([^\n]+)/i]);
    const resolution = extractFirst(text, [/Resolution\s+([^\n]+)/i]);
    const trackerTitles = extractTrackerTitles(text, entry.trackers || []);

    return {
      ...entry,
      finished_at: new Date().toISOString(),
      exit_code: Number.isInteger(exitCode) ? exitCode : null,
      status,
      mode: debug ? "debug" : "live",
      group,
      source,
      type,
      resolution,
      tracker_results: trackerResults,
      tracker_titles: trackerTitles,
      output_excerpt: text,
    };
  };

  const consumeExecutionStream = async (response, entry, signal) => {
    let fullText = "";
    let trailingText = "";
    let exitCode = null;
    let aborted = Boolean(signal?.aborted);
    const abortHandler = () => {
      aborted = true;
    };
    signal?.addEventListener?.("abort", abortHandler, { once: true });

    try {
      if (!response.body) {
        const text = await response.text().catch(() => "");
        upsertHistory(summarizeExecution(entry, text, response.ok ? null : response.status, aborted));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const processLine = (line) => {
        if (!line.startsWith("data: ")) return;
        const payload = safeJsonParse(line.slice(6));
        if (!payload || typeof payload !== "object") return;
        if (payload.type === "html_full") {
          fullText = stripHtml(payload.data || "");
          trailingText = "";
        } else if (payload.type === "html") {
          trailingText += `${stripHtml(payload.data || "")}\n`;
          if (trailingText.length > MAX_OUTPUT_CHARS) trailingText = trailingText.slice(-MAX_OUTPUT_CHARS);
        } else if (payload.type === "exit") {
          const parsedCode = Number(payload.code);
          exitCode = Number.isInteger(parsedCode) ? parsedCode : null;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) processLine(line);
      }
      if (buffer) processLine(buffer);

      const combined = fullText ? `${fullText}\n${trailingText}` : trailingText;
      upsertHistory(summarizeExecution(entry, combined, exitCode, aborted));
    } catch (error) {
      const failed = summarizeExecution(entry, `${fullText}\n${trailingText}\n${error?.message || error}`, exitCode, aborted);
      if (!aborted && failed.status === "completed") failed.status = "failed";
      upsertHistory(failed);
    } finally {
      signal?.removeEventListener?.("abort", abortHandler);
    }
  };

  window.uaApiFetch = async (url, options = {}) => {
    let parsedUrl = null;
    try {
      parsedUrl = new URL(String(url), window.location.origin);
    } catch (_error) {
      return originalApiFetch(url, options);
    }

    if (parsedUrl.pathname !== "/api/execute" || String(options?.method || "GET").toUpperCase() !== "POST") {
      return originalApiFetch(url, options);
    }

    const payload = safeJsonParse(String(options?.body || ""), {}) || {};
    const startedAt = new Date();
    const path = String(payload.path || "");
    const args = String(payload.args || "");
    const entry = {
      id: String(payload.session_id || `history_${Date.now()}_${Math.random().toString(16).slice(2)}`),
      started_at: startedAt.toISOString(),
      finished_at: null,
      title: basename(path),
      path,
      args,
      trackers: parseTrackers(args),
      mode: /(?:^|\s)--debug(?:\s|$)/i.test(args) ? "debug" : "live",
      status: "running",
      group: "",
      source: "",
      type: "",
      resolution: "",
      tracker_results: [],
      tracker_titles: [],
      exit_code: null,
      output_excerpt: "",
    };
    upsertHistory(entry);

    let response;
    try {
      response = await originalApiFetch(url, options);
    } catch (error) {
      upsertHistory(
        summarizeExecution(entry, String(error?.message || error), null, Boolean(options?.signal?.aborted)),
      );
      throw error;
    }

    try {
      const clone = response.clone();
      if (!response.ok) {
        clone
          .text()
          .then((text) => {
            const failed = summarizeExecution(entry, text, response.status, false);
            failed.status = "failed";
            upsertHistory(failed);
          })
          .catch(() => {
            const failed = summarizeExecution(entry, `HTTP ${response.status}`, response.status, false);
            failed.status = "failed";
            upsertHistory(failed);
          });
      } else {
        consumeExecutionStream(clone, entry, options?.signal);
      }
    } catch (error) {
      console.warn("Could not observe execution for upload history:", error);
    }

    return response;
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

  const statusLabel = (status) => {
    const labels = {
      uploaded: "Uploaded",
      completed: "Completed",
      "dry-run": "Dry Run",
      skipped: "Skipped / Dupe",
      failed: "Failed",
      cancelled: "Cancelled",
      running: "Running",
    };
    return labels[status] || status || "Unknown";
  };

  const formatDate = (value) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, {
      year: "2-digit",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
  };

  const durationText = (entry) => {
    if (!entry.started_at || !entry.finished_at) return "-";
    const ms = new Date(entry.finished_at).getTime() - new Date(entry.started_at).getTime();
    if (!Number.isFinite(ms) || ms < 0) return "-";
    if (ms < 60000) return `${Math.max(0, Math.round(ms / 1000))}s`;
    return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  };

  const installStyles = () => {
    if (document.getElementById("serrva-upload-history-style")) return;
    const style = document.createElement("style");
    style.id = "serrva-upload-history-style";
    style.textContent = `
      #serrva-history-button { position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; border: 1px solid #7c3aed; background: #6d28d9; color: #fff; border-radius: 9999px; padding: 10px 16px; font: 600 13px/1.2 system-ui, sans-serif; box-shadow: 0 12px 30px rgba(0,0,0,.35); cursor: pointer; }
      #serrva-history-button:hover { background: #7c3aed; }
      #serrva-history-button .count { display:inline-block; min-width:20px; margin-left:7px; padding:2px 6px; border-radius:9999px; background:rgba(255,255,255,.18); font-size:11px; }
      #serrva-history-overlay { position:fixed; inset:0; z-index:2147483001; background:rgba(0,0,0,.72); display:none; align-items:center; justify-content:center; padding:24px; font-family:system-ui,sans-serif; }
      #serrva-history-overlay.open { display:flex; }
      #serrva-history-panel { width:min(1180px,96vw); max-height:90vh; display:flex; flex-direction:column; overflow:hidden; border:1px solid #374151; border-radius:14px; background:#111827; color:#e5e7eb; box-shadow:0 24px 80px rgba(0,0,0,.55); }
      .serrva-history-header { display:flex; gap:12px; align-items:center; justify-content:space-between; padding:16px 18px; border-bottom:1px solid #374151; }
      .serrva-history-header h2 { margin:0; font-size:18px; font-weight:700; }
      .serrva-history-header p { margin:3px 0 0; color:#9ca3af; font-size:12px; }
      .serrva-history-actions { display:flex; gap:8px; align-items:center; }
      .serrva-history-actions button, .serrva-history-controls select, .serrva-history-controls input { border:1px solid #4b5563; background:#1f2937; color:#e5e7eb; border-radius:8px; padding:7px 9px; font-size:12px; }
      .serrva-history-actions button { cursor:pointer; }
      .serrva-history-actions button:hover { background:#374151; }
      .serrva-history-controls { display:flex; flex-wrap:wrap; gap:8px; padding:12px 18px; border-bottom:1px solid #374151; background:#0f172a; }
      .serrva-history-controls input { min-width:180px; }
      .serrva-history-summary { display:flex; flex-wrap:wrap; gap:7px; padding:0 18px 12px; background:#0f172a; }
      .serrva-history-chip { border:1px solid #374151; border-radius:9999px; padding:4px 9px; font-size:11px; color:#d1d5db; }
      .serrva-history-table-wrap { overflow:auto; flex:1; }
      .serrva-history-table { width:100%; border-collapse:collapse; font-size:12px; }
      .serrva-history-table th { position:sticky; top:0; z-index:1; text-align:left; padding:9px 10px; background:#1f2937; color:#d1d5db; border-bottom:1px solid #374151; white-space:nowrap; }
      .serrva-history-table td { padding:9px 10px; border-bottom:1px solid #273244; vertical-align:top; }
      .serrva-history-row { cursor:pointer; }
      .serrva-history-row:hover { background:#182235; }
      .serrva-history-title { max-width:370px; font-weight:600; color:#f3f4f6; overflow-wrap:anywhere; }
      .serrva-history-muted { color:#9ca3af; }
      .serrva-history-status { display:inline-block; border-radius:9999px; padding:3px 7px; font-weight:650; white-space:nowrap; }
      .serrva-history-status.uploaded, .serrva-history-status.completed { background:#064e3b; color:#a7f3d0; }
      .serrva-history-status.dry-run { background:#1e3a8a; color:#bfdbfe; }
      .serrva-history-status.failed { background:#7f1d1d; color:#fecaca; }
      .serrva-history-status.skipped, .serrva-history-status.cancelled { background:#78350f; color:#fde68a; }
      .serrva-history-status.running { background:#4c1d95; color:#ddd6fe; }
      .serrva-history-details td { background:#0b1220; padding:12px 16px 16px; }
      .serrva-history-details-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 18px; }
      .serrva-history-details code { color:#c4b5fd; white-space:pre-wrap; overflow-wrap:anywhere; }
      .serrva-history-output { margin-top:10px; max-height:220px; overflow:auto; border:1px solid #273244; border-radius:8px; background:#030712; padding:10px; white-space:pre-wrap; font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; color:#d1d5db; }
      .serrva-history-empty { padding:46px 20px; text-align:center; color:#9ca3af; }
      @media (max-width: 760px) { #serrva-history-overlay { padding:8px; } #serrva-history-panel { width:100%; max-height:96vh; } .serrva-history-details-grid { grid-template-columns:1fr; } .serrva-history-table th:nth-child(4), .serrva-history-table td:nth-child(4), .serrva-history-table th:nth-child(6), .serrva-history-table td:nth-child(6) { display:none; } #serrva-history-button { right:12px; bottom:12px; } }
    `;
    document.head.appendChild(style);
  };

  const installUi = () => {
    if (!document.body || document.getElementById("serrva-history-button")) return;
    installStyles();

    const button = document.createElement("button");
    button.id = "serrva-history-button";
    button.type = "button";
    button.innerHTML = `Recent Uploads <span class="count">0</span>`;

    const overlay = document.createElement("div");
    overlay.id = "serrva-history-overlay";
    overlay.innerHTML = `
      <section id="serrva-history-panel" role="dialog" aria-modal="true" aria-label="Recent Uploads">
        <div class="serrva-history-header">
          <div><h2>Recent Uploads</h2><p>Web UI runs saved in this browser (up to ${MAX_ENTRIES})</p></div>
          <div class="serrva-history-actions">
            <button type="button" data-history-action="export">Export JSON</button>
            <button type="button" data-history-action="clear">Clear</button>
            <button type="button" data-history-action="close">Close</button>
          </div>
        </div>
        <div class="serrva-history-controls">
          <select data-history-filter="status">
            <option value="all">All statuses</option>
            <option value="uploaded">Uploaded / Completed</option>
            <option value="dry-run">Dry Run</option>
            <option value="skipped">Skipped / Dupe</option>
            <option value="failed">Failed / Cancelled</option>
            <option value="running">Running</option>
          </select>
          <input data-history-filter="tracker" type="search" placeholder="Filter tracker..." />
          <input data-history-filter="search" type="search" placeholder="Search title/path/group..." />
          <select data-history-filter="limit">
            <option value="25">Last 25</option>
            <option value="50" selected>Last 50</option>
            <option value="100">Last 100</option>
            <option value="250">Last 250</option>
          </select>
        </div>
        <div class="serrva-history-summary"></div>
        <div class="serrva-history-table-wrap"></div>
      </section>
    `;

    document.body.appendChild(button);
    document.body.appendChild(overlay);

    let expandedId = "";

    const currentFilters = () => ({
      status: overlay.querySelector('[data-history-filter="status"]')?.value || "all",
      tracker: String(overlay.querySelector('[data-history-filter="tracker"]')?.value || "").trim().toLowerCase(),
      search: String(overlay.querySelector('[data-history-filter="search"]')?.value || "").trim().toLowerCase(),
      limit: Number(overlay.querySelector('[data-history-filter="limit"]')?.value || 50),
    });

    const matchesStatus = (entry, status) => {
      if (status === "all") return true;
      if (status === "uploaded") return entry.status === "uploaded" || entry.status === "completed";
      if (status === "failed") return entry.status === "failed" || entry.status === "cancelled";
      return entry.status === status;
    };

    const render = () => {
      const history = loadHistory();
      const count = button.querySelector(".count");
      if (count) count.textContent = String(history.length);

      const summary = overlay.querySelector(".serrva-history-summary");
      const tableWrap = overlay.querySelector(".serrva-history-table-wrap");
      if (!summary || !tableWrap) return;

      const totals = {
        uploaded: history.filter((e) => e.status === "uploaded" || e.status === "completed").length,
        dry: history.filter((e) => e.status === "dry-run").length,
        skipped: history.filter((e) => e.status === "skipped").length,
        failed: history.filter((e) => e.status === "failed" || e.status === "cancelled").length,
        running: history.filter((e) => e.status === "running").length,
      };
      summary.innerHTML = `
        <span class="serrva-history-chip">${totals.uploaded} completed</span>
        <span class="serrva-history-chip">${totals.dry} dry runs</span>
        <span class="serrva-history-chip">${totals.skipped} skipped/dupe</span>
        <span class="serrva-history-chip">${totals.failed} failed</span>
        ${totals.running ? `<span class="serrva-history-chip">${totals.running} running</span>` : ""}
      `;

      const filters = currentFilters();
      const entries = history
        .filter((entry) => matchesStatus(entry, filters.status))
        .filter((entry) => !filters.tracker || (entry.trackers || []).some((tracker) => tracker.toLowerCase().includes(filters.tracker)))
        .filter((entry) => {
          if (!filters.search) return true;
          const haystack = [entry.title, entry.path, entry.group, entry.source, entry.type, ...(entry.trackers || []), ...(entry.tracker_titles || []).map((item) => item.title)]
            .join(" ")
            .toLowerCase();
          return haystack.includes(filters.search);
        })
        .slice(0, Number.isFinite(filters.limit) ? filters.limit : 50);

      if (!entries.length) {
        tableWrap.innerHTML = '<div class="serrva-history-empty">No matching upload history yet.</div>';
        return;
      }

      const body = entries
        .map((entry) => {
          const detailsOpen = expandedId === entry.id;
          const trackerText = (entry.trackers || []).join(", ") || "-";
          const finalTitles = (entry.tracker_titles || []).map((item) => `${item.tracker}: ${item.title}`).join("\n") || "-";
          return `
            <tr class="serrva-history-row" data-history-id="${escapeHtml(entry.id)}">
              <td class="serrva-history-muted">${escapeHtml(formatDate(entry.finished_at || entry.started_at))}</td>
              <td class="serrva-history-title">${escapeHtml(entry.title || basename(entry.path))}</td>
              <td>${escapeHtml(trackerText)}</td>
              <td><span class="serrva-history-status ${escapeHtml(entry.status)}">${escapeHtml(statusLabel(entry.status))}</span></td>
              <td>${escapeHtml(entry.mode === "debug" ? "Debug" : "Live")}</td>
              <td>${escapeHtml(entry.group || "-")}</td>
              <td>${escapeHtml(entry.source || "-")}</td>
              <td class="serrva-history-muted">${escapeHtml(durationText(entry))}</td>
            </tr>
            ${detailsOpen ? `
              <tr class="serrva-history-details"><td colspan="8">
                <div class="serrva-history-details-grid">
                  <div><strong>Path:</strong> <code>${escapeHtml(entry.path || "-")}</code></div>
                  <div><strong>Arguments:</strong> <code>${escapeHtml(entry.args || "-")}</code></div>
                  <div><strong>Final title(s):</strong> <code>${escapeHtml(finalTitles)}</code></div>
                  <div><strong>Media:</strong> ${escapeHtml([entry.resolution, entry.source, entry.type].filter(Boolean).join(" / ") || "-")}</div>
                  <div><strong>Exit code:</strong> ${escapeHtml(entry.exit_code ?? "-")}</div>
                  <div><strong>Session:</strong> <code>${escapeHtml(entry.id)}</code></div>
                </div>
                ${entry.output_excerpt ? `<details><summary style="margin-top:10px;cursor:pointer;color:#c4b5fd">Execution output excerpt</summary><div class="serrva-history-output">${escapeHtml(entry.output_excerpt)}</div></details>` : ""}
              </td></tr>
            ` : ""}
          `;
        })
        .join("");

      tableWrap.innerHTML = `
        <table class="serrva-history-table">
          <thead><tr><th>Time</th><th>Title</th><th>Tracker</th><th>Status</th><th>Mode</th><th>Group</th><th>Source</th><th>Duration</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      `;
    };

    const open = () => {
      overlay.classList.add("open");
      render();
    };
    const close = () => overlay.classList.remove("open");

    button.addEventListener("click", open);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
      const action = event.target?.closest?.("[data-history-action]")?.getAttribute("data-history-action");
      if (action === "close") close();
      if (action === "clear") {
        if (window.confirm("Clear all saved Web UI upload history?")) {
          saveHistory([]);
          expandedId = "";
          render();
        }
      }
      if (action === "export") {
        const blob = new Blob([JSON.stringify(loadHistory(), null, 2)], { type: "application/json" });
        const href = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = `upload-assistant-history-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(href), 1000);
      }
      const row = event.target?.closest?.(".serrva-history-row");
      if (row) {
        const id = row.getAttribute("data-history-id") || "";
        expandedId = expandedId === id ? "" : id;
        render();
      }
    });

    overlay.querySelectorAll("[data-history-filter]").forEach((control) => {
      control.addEventListener("input", render);
      control.addEventListener("change", render);
    });
    window.addEventListener(HISTORY_EVENT, render);
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && overlay.classList.contains("open")) close();
    });

    render();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installUi, { once: true });
  } else {
    installUi();
  }
})();
