// Serrva-specific File Browser search optimization.
//
// The upstream /api/browse_search endpoint recursively walks every configured
// root with os.walk(). On large media/torrent trees this can take minutes before
// a shallow match is reached. Replace only that Web UI request with a bounded
// breadth-first search built from the existing /api/browse_roots and /api/browse
// endpoints. Shallow media folders are therefore discovered first and the UI
// remains responsive.
(() => {
  const originalApiFetch = window.uaApiFetch;
  if (typeof originalApiFetch !== "function") return;

  const MAX_RESULTS = 100;
  const MAX_DEPTH = 3;
  const MAX_REQUESTS = 24;
  const BATCH_SIZE = 4;
  let searchGeneration = 0;

  const jsonResponse = (data, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { "content-type": "application/json" },
    });

  const pathPriority = (path) => {
    const normalized = String(path || "").toLowerCase();
    if (normalized.includes("/media/")) return 0;
    if (normalized.endsWith("/media")) return 0;
    if (normalized.includes("/movies")) return 1;
    if (normalized.includes("/tv")) return 1;
    if (normalized.includes("/torrents/")) return 3;
    if (normalized.endsWith("/torrents")) return 3;
    return 2;
  };

  const sortQueue = (queue) =>
    queue.sort((a, b) => {
      const priority = pathPriority(a.path) - pathPriority(b.path);
      if (priority !== 0) return priority;
      return String(a.path || "").localeCompare(String(b.path || ""));
    });

  const optimizedBrowseSearch = async (query) => {
    const needle = String(query || "").trim().toLowerCase();
    if (!needle) {
      return jsonResponse({ success: true, items: [], query: "", count: 0 });
    }

    const generation = ++searchGeneration;
    const rootsResponse = await originalApiFetch("/api/browse_roots");
    if (!rootsResponse.ok) return rootsResponse;

    const rootsData = await rootsResponse.json();
    if (!rootsData.success || !Array.isArray(rootsData.items)) {
      return jsonResponse(rootsData, rootsResponse.status);
    }

    const results = [];
    const resultPaths = new Set();
    const visitedFolders = new Set();
    let requests = 0;
    let queue = rootsData.items
      .filter((item) => item && item.type === "folder" && item.path)
      .map((item) => ({ path: item.path, depth: 0 }));

    const addMatch = (item) => {
      const name = String(item?.name || "").toLowerCase();
      const path = String(item?.path || "");
      if (!path || !name.includes(needle) || resultPaths.has(path)) return;
      resultPaths.add(path);
      results.push(item);
    };

    for (const root of rootsData.items) addMatch(root);

    while (
      queue.length &&
      results.length < MAX_RESULTS &&
      requests < MAX_REQUESTS &&
      generation === searchGeneration
    ) {
      sortQueue(queue);
      const batch = queue.splice(0, Math.min(BATCH_SIZE, MAX_REQUESTS - requests));
      const pending = [];

      for (const entry of batch) {
        if (visitedFolders.has(entry.path)) continue;
        visitedFolders.add(entry.path);
        requests += 1;
        pending.push(
          originalApiFetch(`/api/browse?path=${encodeURIComponent(entry.path)}`)
            .then(async (response) => ({
              entry,
              response,
              data: response.ok ? await response.json() : null,
            }))
            .catch(() => ({ entry, response: null, data: null })),
        );
      }

      const resolved = await Promise.all(pending);
      if (generation !== searchGeneration) {
        return jsonResponse({ success: true, items: [], query: needle, count: 0 });
      }

      const next = [];
      for (const { entry, data } of resolved) {
        if (!data?.success || !Array.isArray(data.items)) continue;
        for (const item of data.items) {
          addMatch(item);
          if (
            results.length < MAX_RESULTS &&
            item?.type === "folder" &&
            item.path &&
            entry.depth < MAX_DEPTH
          ) {
            next.push({ path: item.path, depth: entry.depth + 1 });
          }
        }
      }
      queue.push(...next);
    }

    results.sort((a, b) => {
      const typeOrder = (a.type === "folder" ? 0 : 1) - (b.type === "folder" ? 0 : 1);
      if (typeOrder !== 0) return typeOrder;
      return String(a.name || "").localeCompare(String(b.name || ""));
    });

    const truncated =
      results.length >= MAX_RESULTS ||
      requests >= MAX_REQUESTS ||
      (queue.length > 0 && generation === searchGeneration);

    return jsonResponse({
      success: true,
      items: results.slice(0, MAX_RESULTS),
      query,
      count: Math.min(results.length, MAX_RESULTS),
      truncated,
    });
  };

  window.uaApiFetch = async (url, options = {}) => {
    try {
      const parsed = new URL(String(url), window.location.origin);
      if (parsed.pathname === "/api/browse_search") {
        return optimizedBrowseSearch(parsed.searchParams.get("q") || "");
      }
    } catch (_error) {
      // Fall through to the original request for malformed/relative edge cases.
    }
    return originalApiFetch(url, options);
  };
})();
