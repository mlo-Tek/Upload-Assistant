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
