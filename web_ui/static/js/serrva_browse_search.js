// Serrva-specific File Browser search optimization.
//
// The upstream /api/browse_search endpoint recursively walks every configured
// root with os.walk(). On large media/torrent trees this can take minutes before
// a shallow match is reached. Replace only that Web UI request with a bounded
// breadth-first search built from the existing /api/browse_roots and /api/browse
// endpoints. Movie/TV libraries are prioritized so common searches are reached
// before unrelated media roots or torrent trees.
//
// Keep successful browse responses briefly cached as well. The Web UI has a
// conservative global request limiter and the bounded search otherwise burns
// through that allowance quickly when a user tries several search terms in a
// row, which can make the File Browser appear empty until the limiter resets.
(() => {
  const originalApiFetch = window.uaApiFetch;
  if (typeof originalApiFetch !== "function") return;

  const MAX_RESULTS = 100;
  const MAX_DEPTH = 3;
  const MAX_REQUESTS = 8;
  const BATCH_SIZE = 3;
  const BROWSE_CACHE_TTL_MS = 2 * 60 * 1000;
  const ROOTS_CACHE_TTL_MS = 2 * 60 * 1000;
  const MAX_CACHE_ENTRIES = 96;
  let searchGeneration = 0;
  let rootsCache = null;
  const browseCache = new Map();

  const jsonResponse = (data, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { "content-type": "application/json" },
    });

  const trimCache = () => {
    while (browseCache.size > MAX_CACHE_ENTRIES) {
      const oldestKey = browseCache.keys().next().value;
      if (oldestKey === undefined) break;
      browseCache.delete(oldestKey);
    }
  };

  const cacheKeyForBrowseUrl = (url) => {
    try {
      const parsed = new URL(String(url), window.location.origin);
      if (parsed.pathname !== "/api/browse") return "";
      return `${parsed.pathname}?${parsed.searchParams.toString()}`;
    } catch (_error) {
      return "";
    }
  };

  const cachedBrowseRequest = async (url, options = {}) => {
    const method = String(options?.method || "GET").toUpperCase();
    if (method !== "GET") return originalApiFetch(url, options);

    const key = cacheKeyForBrowseUrl(url);
    const now = Date.now();
    if (key) {
      const cached = browseCache.get(key);
      if (cached && now - cached.at < BROWSE_CACHE_TTL_MS) {
        // Refresh insertion order so frequently used media roots stay cached.
        browseCache.delete(key);
        browseCache.set(key, cached);
        return jsonResponse(cached.data, cached.status);
      }
      if (cached) browseCache.delete(key);
    }

    const response = await originalApiFetch(url, options);
    if (!key || !response.ok) return response;

    try {
      const data = await response.clone().json();
      browseCache.set(key, { at: now, status: response.status, data });
      trimCache();
    } catch (_error) {
      // Keep the original response untouched when a future endpoint variant
      // stops returning JSON.
    }
    return response;
  };

  const getBrowseRoots = async () => {
    const now = Date.now();
    if (rootsCache && now - rootsCache.at < ROOTS_CACHE_TTL_MS) {
      return jsonResponse(rootsCache.data, rootsCache.status);
    }

    const response = await originalApiFetch("/api/browse_roots");
    if (!response.ok) return response;
    try {
      const data = await response.clone().json();
      rootsCache = { at: now, status: response.status, data };
    } catch (_error) {
      // Return the untouched original response below.
    }
    return response;
  };

  const pathPriority = (path) => {
    const normalized = String(path || "").toLowerCase();
    // Search the actual movie/TV libraries first. The previous ordering treated
    // every /media/* folder equally, so a large number of unrelated library
    // roots could consume the bounded request budget before /media/movies was
    // ever visited.
    if (normalized.includes("/movies")) return 0;
    if (normalized.includes("/tv")) return 0;
    if (normalized.includes("/media/")) return 1;
    if (normalized.endsWith("/media")) return 1;
    if (normalized.includes("/torrents/")) return 3;
    if (normalized.endsWith("/torrents")) return 3;
    return 2;
  };

  const sortQueue = (queue) =>
    queue.sort((a, b) => {
      const depthOrder = Number(a.depth || 0) - Number(b.depth || 0);
      if (depthOrder !== 0) return depthOrder;
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
    const rootsResponse = await getBrowseRoots();
    if (!rootsResponse.ok) return rootsResponse;

    const rootsData = await rootsResponse.json();
    if (!rootsData.success || !Array.isArray(rootsData.items)) {
      return jsonResponse(rootsData, rootsResponse.status);
    }

    const results = [];
    const resultPaths = new Set();
    const visitedFolders = new Set();
    let requests = 0;
    let rateLimited = false;
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
          cachedBrowseRequest(`/api/browse?path=${encodeURIComponent(entry.path)}`)
            .then(async (response) => ({
              entry,
              status: response.status,
              data: response.ok ? await response.json() : null,
            }))
            .catch(() => ({ entry, status: 0, data: null })),
        );
      }

      const resolved = await Promise.all(pending);
      if (generation !== searchGeneration) {
        return jsonResponse({ success: true, items: [], query: needle, count: 0 });
      }

      const next = [];
      for (const { entry, status, data } of resolved) {
        if (status === 429) rateLimited = true;
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
      rate_limited: rateLimited,
    });
  };

  window.uaApiFetch = async (url, options = {}) => {
    try {
      const parsed = new URL(String(url), window.location.origin);
      if (parsed.pathname === "/api/browse_search") {
        return optimizedBrowseSearch(parsed.searchParams.get("q") || "");
      }
      if (parsed.pathname === "/api/browse") {
        return cachedBrowseRequest(url, options);
      }
      if (parsed.pathname === "/api/browse_roots") {
        return getBrowseRoots();
      }
    } catch (_error) {
      // Fall through to the original request for malformed/relative edge cases.
    }
    return originalApiFetch(url, options);
  };
})();
