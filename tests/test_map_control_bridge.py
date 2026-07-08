from pathlib import Path

from src.core.map_control_bridge import (
    build_map_context_query,
    build_map_control_command,
    build_tile_metadata_update_listener,
    build_tile_metadata_snapshot_query,
)


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


def test_build_map_control_command_returns_exception_diagnostics():
    js = build_map_control_command({"type": "jumpToGame", "x": 1234, "y": 5678, "source": "tracking"})

    assert "try" in js
    assert "catch (e)" in js
    assert "map_control_exception" in js
    assert "message" in js
    assert "stack" in js


def test_build_map_context_query_calls_userscript_api_directly():
    js = build_map_context_query()

    assert "window.__WuwaMapControl" in js
    assert "getMapContext" in js
    assert "map_control_api_missing" in js
    assert "JSON.stringify" in js


def test_build_tile_metadata_snapshot_query_calls_userscript_api_directly():
    js = build_tile_metadata_snapshot_query()

    assert "window.__WuwaMapControl" in js
    assert "getTileMetadataSnapshot" in js
    assert "map_control_api_missing" in js
    assert "JSON.stringify" in js


def test_build_tile_metadata_update_listener_forwards_userscript_event_to_backend():
    js = build_tile_metadata_update_listener()

    assert "wuwaTileMetadataChanged" in js
    assert "notifyTileMetadataChanged" in js
    assert "__wuwaTileMetadataBridgeInstalled" in js
    assert "addEventListener" in js


def test_main_window_tracking_jump_uses_userscript_control_api():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "build_map_control_command" in text
    assert '"type": "jumpToGame"' in text
    assert '"source": "tracking"' in text
    assert "discoveredMap.setView" not in text
    assert "window.map) { window.map.setView" not in text


def test_main_window_tracking_jump_does_not_forward_heading_to_userscript():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    start = text.index("    def _jump_to_coordinates")
    end = text.index("    def _toggle_recording", start)
    method_text = text[start:end]

    assert "latest_heading_candidate" not in method_text
    assert '"headingDegrees"' not in method_text
    assert '"headingConfidence"' not in method_text


def test_main_window_forwards_latest_heading_to_python_overlay():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    start = text.index("    def _on_ocr_coordinates_detected")
    end = text.index("    def _on_ocr_state_changed", start)
    method_text = text[start:end]

    assert "latest_heading_candidate" in method_text
    assert "set_heading_degrees" in method_text
    assert "clear_heading" in method_text


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


def test_main_window_requests_tile_metadata_snapshot_for_python_cache():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    service_text = (PROJECT_ROOT / "src" / "minimap_tile_sync_service.py").read_text(encoding="utf-8")

    assert "build_tile_metadata_snapshot_query" in text
    assert "def _refresh_minimap_tile_cache(self):" in text
    assert "def _on_tile_metadata_snapshot_received(self, result):" in text
    assert "MinimapTileSyncService" in text
    assert "self._minimap_tile_sync_service.submit_snapshot(result)" in text
    assert "download_tile_snapshot_result" in service_text
    assert "tile_root_provider=paths.minimap_tile_cache_dir" in text


def test_main_window_enqueues_downloaded_tiles_for_incremental_indexing():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    service_text = (PROJECT_ROOT / "src" / "minimap_tile_sync_service.py").read_text(encoding="utf-8")

    assert "TileIndexQueue" in text
    assert "def _enqueue_changed_tile_indexes(self, downloaded_tiles)" in service_text
    assert "download_result.downloaded_sizes.keys()" in service_text
    assert "小地图瓦片索引队列" in text
    assert "on_error=self._on_minimap_tile_index_error" in text


def test_main_window_routes_tile_index_errors_to_system_log_without_web_notification():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "def _on_minimap_tile_index_error(self, message):" in text
    assert "小地图瓦片索引失败" in text
    assert "build_map_notification_command" not in text


def test_main_window_shuts_down_tile_index_queue_on_close():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    start = text.index("    def closeEvent(self, event):")
    method_text = text[start:]

    assert "_minimap_tile_sync_service" in method_text
    assert "_minimap_tile_index_queue" in method_text
    assert ".shutdown()" in method_text


def test_main_window_owns_download_and_update_executors():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    start = text.index("    def closeEvent(self, event):")
    method_text = text[start:]

    assert "ThreadPoolExecutor" in text
    assert "self._python_download_executor" in text
    assert "self._update_check_executor" in text
    assert "self._python_download_executor.shutdown" in method_text
    assert "self._update_check_executor.shutdown" in method_text
    assert "threading.Thread" not in text


def test_map_backend_uses_owned_proxy_executor():
    text = (PROJECT_ROOT / "src" / "core" / "map_backend.py").read_text(encoding="utf-8")

    assert "ThreadPoolExecutor" in text
    assert "self._proxy_executor" in text
    assert "def shutdown(self):" in text
    assert "threading.Thread" not in text


def test_main_window_listens_for_tile_metadata_update_notifications():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "build_tile_metadata_update_listener" in text
    assert "tileMetadataChangedSignal.connect" in text
    assert "def _install_tile_metadata_update_listener(self):" in text
    assert "def _on_tile_metadata_changed(self, updated_at: str):" in text
    assert "self._tile_metadata_refresh_pending" in text


def test_main_window_logs_tile_snapshot_and_download_diagnostics():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "小地图瓦片变更通知" in text
    assert "小地图瓦片快照" in text
    assert "standardTiles" in text
    assert "小地图瓦片下载检查" in text
    assert "input_count" in text
    assert "skipped_count" in text
    assert "_system_log_requested" in text


def test_main_window_requeues_stale_sift_indexes_from_tile_snapshot():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    service_text = (PROJECT_ROOT / "src" / "minimap_tile_sync_service.py").read_text(encoding="utf-8")

    assert "def _enqueue_stale_sift_indexes(self, snapshot" in service_text
    assert "enqueue_stale_sift_tiles" in service_text
    assert "小地图SIFT过期索引修复队列" in text


def test_main_window_reconciles_missing_minimap_indexes_from_snapshot():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    service_text = (PROJECT_ROOT / "src" / "minimap_tile_sync_service.py").read_text(encoding="utf-8")

    assert "def _enqueue_missing_indexes(self, snapshot" in service_text
    assert "enqueue_missing_indexes_for_area" in service_text
    assert "小地图索引补偿队列" in text
    assert "小地图索引状态" in text
    assert "health_summary" in text


def test_map_backend_exposes_tile_metadata_changed_signal_and_slot():
    text = (PROJECT_ROOT / "src" / "core" / "map_backend.py").read_text(encoding="utf-8")

    assert "tileMetadataChangedSignal = Signal(str)" in text
    assert "def notifyTileMetadataChanged(self, updated_at: str):" in text
    assert "self.tileMetadataChangedSignal.emit" in text


def test_main_window_updates_ocr_vision_context_from_tile_snapshot():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "map_context_from_js" in text
    assert "build_vision_snapshot" in text
    assert "def _update_ocr_vision_context_from_tile_snapshot(self, result):" in text
    assert "self._ocr_manager.update_vision_context" in text


def test_main_window_only_refreshes_official_tile_metadata_for_official_map():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "from core.map_provider_capabilities import capabilities_for_current_map" in text
    assert "def _current_map_capabilities(self):" in text
    assert "def _supports_official_tile_metadata(self)" in text

    load_finished = text[text.index("def _on_web_load_finished") : text.index("def _refresh_python_overlay_after_web_load")]
    assert "self._supports_official_tile_metadata()" in load_finished
    assert "self._install_tile_metadata_update_listener()" in load_finished
    assert "self._refresh_minimap_tile_cache" in load_finished


def test_main_window_clears_vision_context_when_current_map_is_not_official():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    method = text[text.index("def _refresh_minimap_tile_cache") : text.index("def _on_tile_metadata_snapshot_received")]

    assert "if not self._supports_official_tile_metadata()" in method
    assert "self._clear_ocr_vision_context" in method
    assert "build_tile_metadata_snapshot_query()" in method


def test_main_window_documents_provider_specific_userscript_loading():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "def _provider_user_scripts(self)" in text
    assert "wuwa_map_optimizer.js" in text
    assert "wuwa_map_optimizer_lite.js" in text
    assert "supports_official_ui_cleanup" in text
    assert "supports_local_affine_calibration" in text


def test_lite_userscript_only_matches_local_map_after_aura_removal():
    text = (PROJECT_ROOT / "js" / "wuwa_map_optimizer_lite.js").read_text(encoding="utf-8")

    assert "@match        http://localhost:58427/*" in text
    assert "ghzs" not in text
    assert "ghzs666" not in text


def test_local_map_does_not_submit_official_tile_snapshot_to_sync_service():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    method = text[text.index("def _on_tile_metadata_snapshot_received") : text.index("def _log_tile_metadata_snapshot_summary")]

    assert "if not self._supports_official_tile_metadata()" in method
    assert "self._minimap_tile_sync_service.submit_snapshot(result)" in method
    assert method.index("if not self._supports_official_tile_metadata()") < method.index("self._minimap_tile_sync_service.submit_snapshot(result)")


def test_main_window_does_not_refresh_stitched_resources_for_normal_tile_downloads():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "def _refresh_minimap_stitched_resources(self, changed_area_ids):" in text
    start = text.index("    def _on_tile_metadata_snapshot_received(self, result):")
    end = text.index("    def _refresh_minimap_stitched_resources(self, changed_area_ids):", start)
    method_text = text[start:end]

    assert "self._refresh_minimap_stitched_resources" not in method_text
    assert "missing_stitched_manifest_area_ids" not in method_text


def test_main_window_does_not_notify_userscript_when_minimap_roi_auto_calibration_fails():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "build_map_notification_command" not in text
    assert "def _notify_minimap_roi_auto_calibration_failed(self):" not in text


def test_main_window_resets_coordinate_continuity_when_area_changes():
    text = (PROJECT_ROOT / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    marker = "def _on_url_changed(self, url: QUrl):"
    start = text.index(marker)
    end = text.index("    @Slot(str)\n    def _on_local_map_changed", start)
    method_text = text[start:end]

    assert "reset_coordinate_continuity" in method_text
    assert "area_changed" in method_text
