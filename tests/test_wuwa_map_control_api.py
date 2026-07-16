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

    assert "globalScope.__WuwaMapControl" in text
    assert "window.__WuwaMapControl" in text
    assert "function installMapControlApi()" in text
    assert "function handleMapControlCommand(command)" in text
    assert "function jumpToGameViaControl(x, y, options = {})" in text
    assert "function jumpToLatLngViaControl(lat, lng, options = {})" in text
    assert "function zoomViaControl(delta, options = {})" in text


def test_userscript_exposes_map_context_api():
    text = read_script()

    assert "getMapContext" in text
    assert "areaId" in text
    assert "coordTransform" in text
    assert "tileProjection" in text
    assert "mapUnitsPerTileX" in text


def test_userscript_exposes_incremental_tile_metadata_api():
    text = read_script()

    assert "getTileMetadataSnapshot" in text
    assert "standardTiles" in text
    assert "layeredTiles" in text
    assert "gravityTiles" in text
    assert "tileBaseUrl" in text


def test_userscripts_parse_current_official_layered_tile_url_shape():
    text = read_script()

    assert (
        "cleanUrl.match(/^(.*)\\/(\\d+)\\/(\\d+)\\/(-?\\d+)\\/(-?\\d+)_(-?\\d+)\\.png$/)"
        in text
    )
    assert "type: 'layered'" in text
    assert "layerId: match[3]" in text
    assert "zLevel: Number(match[4])" in text
    assert "x: Number(match[5])" in text
    assert "y: Number(match[6])" in text


def test_userscript_dispatches_tile_metadata_event_on_page_global_scope():
    text = read_script()

    assert "globalScope.__WuwaTileMetadataUpdatedAt = updatedAt" in text
    assert "globalScope.dispatchEvent(new CustomEvent('wuwaTileMetadataChanged'" in text
    assert "window.dispatchEvent(new CustomEvent('wuwaTileMetadataChanged'" not in text


def test_userscript_deduplicates_and_debounces_tile_metadata_notifications():
    text = read_script()

    assert "notificationTimer: null" in text
    assert "function sameTileMetadata(previous, current)" in text
    assert "if (previous && sameTileMetadata(previous, tile)) return true;" in text
    assert "function scheduleTileMetadataChanged(updatedAt)" in text
    assert "clearTimeout(STATE.tileMetadata.notificationTimer)" in text
    assert "STATE.tileMetadata.notificationTimer = setTimeout" in text
    assert "scheduleTileMetadataChanged(updatedAt);" in text
    assert "notifyTileMetadataChanged(updatedAt);" not in text[text.index("function observeTileMetadataUrl") : text.index("function getTileMetadataSnapshot")]


def test_userscript_does_not_patch_leaflet_tile_loading_lifecycle():
    text = read_script()

    assert "installTileMetadataGetTileUrlObserver" not in text
    assert "LL.TileLayer.prototype.getTileUrl" not in text
    assert "LL.TileLayer.prototype.createTile" not in text
    assert "observeTileMetadataUrl(this.getTileUrl(coords), coords)" not in text


def test_userscript_does_not_expose_python_controlled_notification_api():
    text = read_script()

    assert "showPythonNotificationViaControl" not in text
    assert "showNotification: showPythonNotificationViaControl" not in text
    assert "cmd.type === 'showNotification'" not in text


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


def test_userscripts_validate_leaflet_pane_before_accepting_map_candidate():
    for text in (read_script(), read_lite_script()):
        assert "function hasUsableMapPane(map)" in text
        assert "if (!hasUsableMapPane(map)) return false;" in text
        assert "if (LL && LL.Map && map instanceof LL.Map) return true;" in text


def test_userscripts_return_structured_failure_when_setview_throws():
    for text in (read_script(), read_lite_script()):
        assert "function setViewViaControl(map, latNum, lngNum)" in text
        assert "map_setview_exception" in text
        assert "STATE.mapInstance = null;" in text
        assert "return setViewViaControl(map, latNum, lngNum);" in text


def test_userscripts_capture_recreated_leaflet_map_instances():
    for text in (read_script(), read_lite_script()):
        assert "function captureMapInstance(map, source)" in text
        assert "captureMapInstance(this, 'constructor')" in text
        assert "if (!STATE.mapInstance) {" not in text
        assert "window.discoveredMap && !STATE.mapInstance" not in text


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


def test_userscripts_do_not_draw_python_overlay_heading_marker():
    for text in (read_script(), read_lite_script()):
        assert "trackingHeadingLayer" not in text
        assert "function updateTrackingHeadingMarker" not in text
        assert "createTrackingHeadingHtml" not in text
        assert "cmd.headingDegrees" not in text
        assert "kmp-tracking-heading" not in text


def test_smart_undo_uses_successful_mark_history():
    text = read_script()

    assert "SMART_MARK_HISTORY_LIMIT = 100" in text
    assert "smartMarkHistory: []" in text
    assert "function rememberSmartMark(target)" in text
    assert "function undoLastSmartMark()" in text
    assert "rememberSmartMark(target);" in text
    assert "btnUndo.onclick = () => undoLastSmartMark();" in text
    assert "btnUndo.onclick = () => handleSmartAction(false);" not in text
