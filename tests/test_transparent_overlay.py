from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = PROJECT_ROOT / "src" / "transparent_overlay.py"
MAIN_WINDOW = PROJECT_ROOT / "src" / "ui" / "main_window.py"


def test_transparent_overlay_draws_unified_svg_marker_in_python_overlay():
    text = OVERLAY.read_text(encoding="utf-8")

    assert "def set_heading_degrees" in text
    assert "def clear_heading" in text
    assert "_draw_player_marker" in text
    assert "QSvgRenderer" in text
    assert "PLAYER_MARKER_SVG_TEMPLATE" in text
    assert ".render(" in text


def test_overlay_marker_preserves_provided_svg_geometry_and_single_color():
    text = OVERLAY.read_text(encoding="utf-8")

    assert "heading_degrees" in text
    assert '<circle cx="50" cy="64" r="16" fill="{fill}">' in text
    assert '<path d="M 63.44,50.56 A 19,19 0 0,1 63.44,77.44 L 83,64 Z" fill="{fill}">' in text
    assert "east_reference_degrees = 90.0" in text
    assert "fill = QColor(self.circle_color).name()" in text
    assert ".replace(\"{fill}\", fill)" in text
    assert ".darker(" not in text
    assert "arcTo" not in text


def test_overlay_geometry_is_event_driven_without_high_frequency_timer():
    text = OVERLAY.read_text(encoding="utf-8")

    assert "def eventFilter" in text
    assert "self.update_overlay_geometry()" in text
    assert "position_timer.start(50)" not in text
    assert "timeout.connect(self.update_overlay_geometry)" not in text


def test_main_window_raises_python_overlay_after_web_page_reload():
    text = MAIN_WINDOW.read_text(encoding="utf-8")
    load_finished = text[text.index("def _on_web_load_finished") : text.index("def _install_tile_metadata_update_listener")]

    assert "self._refresh_python_overlay_after_web_load()" in load_finished
    assert "def _refresh_python_overlay_after_web_load" in text
    assert "self._overlay_manager.show_overlay()" in text
