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
