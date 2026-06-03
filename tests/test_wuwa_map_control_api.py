from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer.js"
LITE_SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer_lite.js"


def read_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def read_lite_script() -> str:
    return LITE_SCRIPT.read_text(encoding="utf-8")


def test_userscript_exposes_map_control_api():
    text = read_script()

    assert "window.__WuwaMapControl" in text
    assert "function installMapControlApi()" in text
    assert "function handleMapControlCommand(command)" in text
    assert "function jumpToGameViaControl(x, y, options = {})" in text
    assert "function jumpToLatLngViaControl(lat, lng, options = {})" in text
    assert "function zoomViaControl(delta, options = {})" in text


def test_lite_userscript_exposes_map_control_api():
    text = read_lite_script()

    assert "installMapControlApi();" in text
    assert "window.__WuwaMapControl" in text
    assert "function installMapControlApi()" in text
    assert "function handleMapControlCommand(command)" in text
    assert "function jumpToGameViaControl(x, y, options = {})" in text
    assert "function jumpToLatLngViaControl(lat, lng, options = {})" in text
    assert "function zoomViaControl(delta, options = {})" in text


def test_userscripts_expose_map_recapture_control():
    for text in (read_script(), read_lite_script()):
        assert "function recaptureMapViaControl()" in text
        assert "recaptureMap: recaptureMapViaControl" in text
        assert "cmd.type === 'recaptureMap'" in text
        assert "installMapControlApi();\n    interceptMap();" in text


def test_tracking_commands_pause_while_point_popup_is_open():
    text = read_script()

    assert "function shouldPauseTrackingMove()" in text
    assert "STATE.toggles.pauseTrackingWhenPopupOpen" in text
    assert "isPointPopupOpenForControl()" in text
    assert "point_popup_open" in text


def test_sidebar_has_default_enabled_pause_tracking_toggle():
    text = read_script()

    assert "pauseTrackingWhenPopupOpen: getStore('SM_PAUSE_TRACKING_WHEN_POPUP_OPEN', true)" in text
    assert 'id="sm-pause-tracking-popup"' in text
    assert 'id="sm-pause-tracking-popup-row"' in text
    assert "弹窗打开时暂停追踪" in text
    assert "SM_PAUSE_TRACKING_WHEN_POPUP_OPEN" in text


def test_pause_tracking_toggle_has_explicit_click_and_keyboard_handler():
    text = read_script()

    assert "function setPauseTrackingWhenPopupOpen(checked)" in text
    assert "pauseTrackingRow.onclick" in text
    assert "pauseTrackingRow.onkeydown" in text
    assert "setPauseTrackingWhenPopupOpen(!pauseTrackingToggle.checked)" in text


def test_jump_to_game_uses_latlng_array_returned_by_game_to_latlng():
    text = read_script()

    assert "const latLng = gameToLatLng(x, y);" in text
    assert "return jumpToLatLngViaControl(latLng[0], latLng[1], options);" in text
    assert "latLng.lat" not in text
    assert "latLng.lng" not in text


def test_smart_undo_uses_successful_mark_history():
    text = read_script()

    assert "SMART_MARK_HISTORY_LIMIT = 100" in text
    assert "smartMarkHistory: []" in text
    assert "function rememberSmartMark(target)" in text
    assert "function undoLastSmartMark()" in text
    assert "rememberSmartMark(target);" in text
    assert "btnUndo.onclick = () => undoLastSmartMark();" in text
    assert "btnUndo.onclick = () => handleSmartAction(false);" not in text
