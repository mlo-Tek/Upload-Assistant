from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_serrva_webui_stylesheet_is_loaded() -> None:
    index = (ROOT / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "css/serrva.css" in index


def test_expanded_execution_output_has_large_desktop_viewport() -> None:
    css = (ROOT / "web_ui" / "static" / "css" / "serrva.css").read_text(encoding="utf-8")

    assert 'button[title="Collapse output"]' in css
    assert "#rich-output:not(.hidden)" in css
    assert "52vh" in css
    assert "overflow-y: auto" in css


def test_serrva_config_fix_loads_before_config_app() -> None:
    config_template = (ROOT / "web_ui" / "templates" / "config.html").read_text(encoding="utf-8")

    shared_index = config_template.index("js/shared_utils.js")
    fix_index = config_template.index("js/serrva_config_fixes.js")
    app_index = config_template.index("js/config_app.js")

    assert shared_index < fix_index < app_index


def test_image_host_dropdown_fallback_includes_supported_hosts() -> None:
    script = (ROOT / "web_ui" / "static" / "js" / "serrva_config_fixes.js").read_text(encoding="utf-8")

    assert "/api/config_options" in script
    assert "Available image hosts:" in script
    for host in ("ptscreens", "imgbb", "imgbox"):
        assert f'"{host}"' in script


def test_serrva_helpers_load_before_app() -> None:
    index = (ROOT / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")

    shared_index = index.index("js/shared_utils.js")
    search_fix_index = index.index("js/serrva_browse_search.js")
    history_index = index.index("js/serrva_upload_history.js")
    app_index = index.index("js/app.js")

    assert shared_index < search_fix_index < history_index < app_index


def test_optimized_browse_search_is_bounded_cached_and_breadth_first() -> None:
    script = (ROOT / "web_ui" / "static" / "js" / "serrva_browse_search.js").read_text(encoding="utf-8")

    assert 'parsed.pathname === "/api/browse_search"' in script
    assert 'originalApiFetch("/api/browse_roots")' in script
    assert "/api/browse?path=" in script
    assert "MAX_DEPTH = 3" in script
    assert "MAX_REQUESTS = 8" in script
    assert "BATCH_SIZE = 3" in script
    assert "BROWSE_CACHE_TTL_MS" in script
    assert "browseCache = new Map()" in script
    assert "cachedBrowseRequest" in script
    assert "depthOrder" in script
    assert "queue.push(...next)" in script


def test_recent_upload_history_observes_execute_stream_and_persists_entries() -> None:
    script = (ROOT / "web_ui" / "static" / "js" / "serrva_upload_history.js").read_text(encoding="utf-8")

    assert 'parsedUrl.pathname !== "/api/execute"' in script
    assert "response.clone()" in script
    assert "ua_serrva_upload_history_v1" in script
    assert "MAX_ENTRIES = 250" in script
    assert "Group Tag" in script
    assert "Tracker Processing Summary" not in script  # parsing stays format-focused, not tracker-specific UI text
    assert "extractTrackerResults" in script


def test_recent_upload_history_has_filters_details_and_export() -> None:
    script = (ROOT / "web_ui" / "static" / "js" / "serrva_upload_history.js").read_text(encoding="utf-8")

    for label in ("Recent Uploads", "All statuses", "Dry Run", "Skipped / Dupe", "Last 250", "Export JSON"):
        assert label in script
    assert "Execution output excerpt" in script
    assert "tracker_titles" in script
    assert "output_excerpt" in script
