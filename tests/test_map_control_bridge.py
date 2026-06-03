from pathlib import Path

from src.core.map_control_bridge import build_map_control_command


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_map_control_command_calls_userscript_api_only():
    js = build_map_control_command(
        {
            "type": "jumpToGame",
            "x": 1234,
            "y": -5678,
            "source": "tracking",
        }
    )

    assert "window.__WuwaMapControl" in js
    assert "handleCommand" in js
    assert '"jumpToGame"' in js
    assert '"tracking"' in js
    assert "discoveredMap.setView" not in js
    assert "window.map.setView" not in js


def test_build_map_control_command_returns_structured_failure_when_api_missing():
    js = build_map_control_command({"type": "zoom", "delta": 1, "source": "manual"})

    assert "map_control_api_missing" in js
    assert "ok: false" in js
    assert "reason" in js
    assert "JSON.stringify" in js


def test_main_window_tracking_jump_uses_userscript_control_api():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "build_map_control_command" in text
    assert '"type": "jumpToGame"' in text
    assert '"source": "tracking"' in text
    assert "discoveredMap.setView" not in text
    assert "window.map) { window.map.setView" not in text


def test_main_window_zoom_hotkeys_use_userscript_control_api():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert '"type": "zoom"' in text
    assert '"source": "manual"' in text
    assert "map.zoomIn" not in text
    assert "map.zoomOut" not in text


def test_calibration_finish_refreshes_userscript_runtime_payload():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    marker = "def _on_calibration_finished(self, matrix):"
    start = text.index(marker)
    end = text.index("    def _jump_to_coordinates", start)
    method_text = text[start:end]

    assert "self._inject_kmp_runtime()" in method_text


def test_main_window_recapture_uses_userscript_control_api():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    marker = "def _recapture_map(self):"
    start = text.index(marker)
    end = text.index("    def _start_ocr", start)
    method_text = text[start:end]

    assert "build_map_control_command" in method_text
    assert '"type": "recaptureMap"' in method_text
    assert "triggerCapture" not in method_text
