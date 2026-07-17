# -*- coding: utf-8 -*-
import os
import sys
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Any, Dict
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import Qt, QUrl, QTimer, Slot, QStandardPaths, Signal, QRect
from PySide6.QtGui import QIcon, QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QSizePolicy, QMessageBox, QProgressDialog
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from datetime import datetime

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    setTheme, Theme, DotInfoBadge, InfoBadgePosition
)
from .custom_icons import CustomFluentIcon

try:
    from language_manager import tr, get_language_manager
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
    def tr(key, default=None, **kwargs):
        return default if default is not None else key
    def get_language_manager():
        return None

from .interfaces import (
    HomeInterface, NavigationInterface, OCRSettingsInterface,
    MapSettingsInterface, RouteSettingsInterface, HotkeyInterface,
    LogInterface, SettingsInterface, AboutInterface
)
from .components.ocr_preview_overlay import OCRPreviewOverlay
from core import paths

try:
    from core.app_state import AppState
    from core.constants import get_map_urls, DEFAULT_HOTKEYS
    from core.calibration import TransformMatrix
    from core.map_provider_capabilities import capabilities_for_current_map
    from core.route_export_paths import (
        is_route_export_download,
        resolve_route_export_directory,
    )
    from core.map_control_bridge import (
        build_map_control_command,
        build_tile_metadata_update_listener,
        build_tile_metadata_snapshot_query,
    )
    from core.update_provider import HttpUpdateProvider, UpdateResult
    from core.update_downloader import prepare_updater_binary
    from core.utils import get_assets_path
    from core.version import find_version_file, load_version_info
    from core.vision_context import build_vision_snapshot, map_context_from_js
    from minimap_stitched_resources import publish_stitched_resources_from_snapshot
    from minimap_tile_indexer import TileIndexQueue
    from minimap_tile_snapshot import parse_tile_metadata_snapshot_result
    from minimap_tile_sync_service import MinimapTileSyncService
    from minimap_roi import MinimapRoi
except ImportError:
    from ..core.app_state import AppState
    from ..core.constants import get_map_urls, DEFAULT_HOTKEYS
    from ..core.calibration import TransformMatrix
    from ..core.map_provider_capabilities import capabilities_for_current_map
    from ..core.route_export_paths import (
        is_route_export_download,
        resolve_route_export_directory,
    )
    from ..core.map_control_bridge import (
        build_map_control_command,
        build_tile_metadata_update_listener,
        build_tile_metadata_snapshot_query,
    )
    from ..core.update_provider import HttpUpdateProvider, UpdateResult
    from ..core.update_downloader import prepare_updater_binary
    from ..core.utils import get_assets_path
    from ..core.version import find_version_file, load_version_info
    from ..core.vision_context import build_vision_snapshot, map_context_from_js
    from ..minimap_stitched_resources import publish_stitched_resources_from_snapshot
    from ..minimap_tile_indexer import TileIndexQueue
    from ..minimap_tile_snapshot import parse_tile_metadata_snapshot_result
    from ..minimap_tile_sync_service import MinimapTileSyncService
    from ..minimap_roi import MinimapRoi


def build_updater_command(
    updater_path: Path,
    app_root: Path,
    main_exe: str,
    result: UpdateResult,
    wait_pid: int,
) -> list[str]:
    command = [
        str(updater_path),
        "--app-root",
        str(app_root),
        "--main-exe",
        main_exe,
        "--version",
        result.latest_version,
        "--manifest-url",
        result.manifest_url,
        "--wait-pid",
        str(wait_pid),
    ]
    return command


class MainWindow(FluentWindow):
    _update_check_finished = Signal(object, str, str)
    _updater_prepare_finished = Signal(object, str, bool)
    _system_log_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._version_file = find_version_file(self._app_root_for_update())
        self._version_info = load_version_info(self._app_root_for_update())

        self._is_closing = False
        self._managers_initialized = False
        self._server_startup_error: Optional[str] = None
        self._auto_calibration_fetching = False
        self._latest_tile_snapshot_result = None
        self._tile_metadata_refresh_pending = False
        self._auto_calibration_polling_timer = QTimer(self)
        self._auto_calibration_polling_timer.setInterval(1000)
        self._auto_calibration_polling_timer.timeout.connect(self.fetch_auto_calibration)

        self._app_state = AppState(self)
        self._log_version_source()
        from core.settings_manager import SettingsManager
        self._settings = SettingsManager()
        self._minimap_region_calibrator = None
        self._about_nav_item = None
        self._about_nav_badge = None
        self._update_check_in_progress = False
        self._updater_prepare_in_progress = False
        self._updater_prepare_dialog: Optional[QProgressDialog] = None
        self._pending_update_command: Optional[list[str]] = None
        self._last_update_result: Optional[UpdateResult] = None
        self._python_download_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="python-download")
        self._update_check_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update-check")
        self._system_log_requested.connect(self._app_state.append_system_log)
        self._minimap_tile_index_queue = TileIndexQueue(
            paths.minimap_tile_cache_dir(),
            max_workers=1,
            auto_start=True,
            on_error=self._on_minimap_tile_index_error,
        )
        self._minimap_tile_sync_service = MinimapTileSyncService(
            index_queue=self._minimap_tile_index_queue,
            tile_root_provider=paths.minimap_tile_cache_dir,
            on_summary=self._on_minimap_tile_sync_summary,
        )
        self._update_provider = HttpUpdateProvider(
            latest_url=self._version_info.update_base_url,
            artifact_key=self._get_update_artifact_key(),
        )
        self._update_check_finished.connect(self._on_update_check_finished)
        self._updater_prepare_finished.connect(self._on_updater_prepare_finished)

        # 应用保存的主题设置
        self._apply_saved_theme()

        self._init_window_properties()
        self._init_managers()
        self._init_webview()
        self._init_interfaces()
        self._init_navigation()
        self._connect_signals()
        self._retranslate_ui()

        QTimer.singleShot(100, self._post_init)

    def _get_update_artifact_key(self) -> str:
        return "windows-x64-v2"

    def _log_version_source(self):
        version_file = str(self._version_file) if self._version_file else "未找到"
        self._app_state.append_system_log(
            f"当前版本: v{self._version_info.version}，版本文件: {version_file}",
            "INFO",
        )

    def _apply_saved_theme(self):
        """应用保存的主题设置"""
        from core.settings_manager import SettingsManager
        from qfluentwidgets import setTheme, Theme

        settings = SettingsManager()
        theme_mode = settings.get("appearance.theme", "auto")

        if theme_mode == "light":
            setTheme(Theme.LIGHT)
        elif theme_mode == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)

        # 应用主题后更新所有自定义组件
        QTimer.singleShot(200, lambda: self._on_theme_changed(theme_mode))

    def _init_window_properties(self):
        self.setWindowTitle("呜呜大地图")
        self.resize(900, 713)
        self.setMinimumSize(900, 713)

        # Set navigation expand width to 150px
        self.navigationInterface.setExpandWidth(150)

        # Hide the return button in navigation bar
        self.navigationInterface.setReturnButtonVisible(False)

        icon_path = get_assets_path("ico.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 隐藏标题栏左侧应用图标（保留窗口/任务栏图标）
        if hasattr(self, "titleBar") and hasattr(self.titleBar, "iconLabel"):
            self.titleBar.iconLabel.hide()
    
    def _init_managers(self):
        self._ocr_manager = None
        self._route_recorder = None
        self._hotkey_manager = None
        self._server_manager = None
        self._overlay_manager = None
        self._separated_map_window = None
        self._gm_manager = None
        self._log_manager = None
        self._resource_probe = None
        self._ocr_preview_overlay = None
        
        # Initialize OCR preview overlay early
        self._ocr_preview_overlay = OCRPreviewOverlay(self)
        
        try:
            from server_manager import LocalServerManager
            self._server_manager = LocalServerManager()
            started = self._server_manager.start_servers()
            if not started:
                self._server_startup_error = getattr(
                    self._server_manager,
                    "last_error",
                    "本地地图服务启动失败"
                )
        except ImportError:
            print("Server manager not available")

        try:
            from core.log_manager import LogManager
            self._log_manager = LogManager()
            self._app_state.set_log_manager(self._log_manager)
        except Exception as e:
            print(f"Log manager not available: {e}")
            self._log_manager = None

        try:
            from core.resource_probe import ResourceProbe
            self._resource_probe = ResourceProbe(self._settings, self._log_manager)
            self._app_state.set_resource_probe(self._resource_probe)
            if self._resource_probe.enabled:
                self._app_state.append_system_log("资源诊断计数已启用", "INFO")
        except Exception as e:
            print(f"Resource probe not available: {e}")
            self._resource_probe = None
        
        try:
            from ocr_manager import OCRManager
            self._ocr_manager = OCRManager(self)
            if self._log_manager and hasattr(self._ocr_manager, 'set_log_manager'):
                self._ocr_manager.set_log_manager(self._log_manager)
            self._ocr_manager.coordinates_detected.connect(self._on_ocr_coordinates_detected)
            self._ocr_manager.state_changed.connect(self._on_ocr_state_changed)
            self._ocr_manager.error_occurred.connect(self._on_ocr_error)
            try:
                self._ocr_manager.ocr_region_source_changed.connect(
                    self._on_ocr_region_source_changed
                )
            except Exception:
                pass
            try:
                self._ocr_manager.minimap_roi_locked.connect(self._on_minimap_roi_locked)
            except Exception:
                pass
        except ImportError:
            print("OCR manager not available")
        
        try:
            from route_recorder import RouteRecorder
            self._route_recorder = RouteRecorder(self)
            self._route_recorder.recording_started.connect(self._on_recording_started)
            self._route_recorder.recording_stopped.connect(self._on_recording_stopped)
            self._route_recorder.point_recorded.connect(self._on_point_recorded)
            self._route_recorder.error_occurred.connect(self._on_recording_error)
        except ImportError:
            print("Route recorder not available")
        
        try:
            from hotkey_manager import GlobalHotkeyManager
            self._hotkey_manager = GlobalHotkeyManager()
            self._hotkey_manager.hotkey_triggered.connect(self._on_hotkey_triggered)
        except ImportError:
            print("Hotkey manager not available")
        
        try:
            from greasemonkey_manager import GreasemonkeyManager
            self._gm_manager = GreasemonkeyManager()
        except ImportError:
            print("Greasemonkey manager not available")

        self._managers_initialized = True
    
    def _init_webview(self):
        self._web_profile = QWebEngineProfile("WutheringWavesNavigator", self)
        try:
            from core import paths
            profile_path = paths.cache_dir("web_profile")
            os.makedirs(profile_path, exist_ok=True)
            self._web_profile.setPersistentStoragePath(str(profile_path))
            self._web_profile.setCachePath(str(profile_path / "cache"))
            print(f"WebProfile设置完成: {profile_path}")
        except Exception as e:
            print(f"WebProfile设置失败: {e}")
        self._web_profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self._connect_web_download_handler()

        self._web_page = QWebEnginePage(self._web_profile, self)
        self._web_view = QWebEngineView()
        self._web_view.setPage(self._web_page)
        self._web_view.urlChanged.connect(self._on_url_changed)
        self._web_view.loadFinished.connect(self._on_web_load_finished)

        self._web_channel = QWebChannel(self._web_page)
        self._web_page.setWebChannel(self._web_channel)

        try:
            from core.map_backend import MapBackend
            self._backend = MapBackend(self)
            self._web_channel.registerObject("backend", self._backend)
            self._backend.statusUpdated.connect(self._on_map_status_updated)
            self._backend.localMapChangedSignal.connect(self._on_local_map_changed)
            self._backend.proxyResponse.connect(self._deliver_proxy_response_via_js)
            self._backend.tileMetadataChangedSignal.connect(self._on_tile_metadata_changed)
        except ImportError:
            self._backend = None
            print("MapBackend not available")

        # 注入Greasemonkey脚本（包括用户脚本）
        if self._gm_manager:
            # 清除旧脚本防止重复
            self._web_profile.scripts().clear()

            user_scripts = self._provider_user_scripts()

            # 获取标准脚本 + 用户脚本
            scripts = self._gm_manager.get_standard_scripts(user_scripts=user_scripts)

            # 注入所有脚本
            for script in scripts:
                self._web_profile.scripts().insert(script)

            print(f"✅ 已成功注册 {len(scripts)} 个注入脚本到 WebProfile")

    def _provider_user_scripts(self) -> list[str]:
        """Return scripts for supported map providers; @match keeps URL-level isolation."""
        supported_caps = [
            capabilities_for_current_map("online", "official_map"),
            capabilities_for_current_map("local", self._app_state.current_map_provider),
        ]
        script_names = []
        for caps in supported_caps:
            if caps.supports_official_ui_cleanup and caps.uses_full_userscript:
                script_names.append("wuwa_map_optimizer.js")
            if caps.supports_local_affine_calibration and caps.uses_lite_userscript:
                script_names.append("wuwa_map_optimizer_lite.js")

        user_scripts = []
        for script_name in dict.fromkeys(script_names):
            user_script_path = paths.resource_root() / "js" / script_name
            if os.path.exists(user_script_path):
                user_scripts.append(str(user_script_path))
                print(f"✓ 发现用户脚本: {user_script_path}")
            else:
                print(f"⚠ 未发现用户脚本: {user_script_path}")
        return user_scripts

    def _build_kmp_runtime_payload(self) -> Dict[str, Any]:
        """Build userscript runtime payload: token/mapKey/matrix/user."""
        mode = self._app_state.current_mode

        # Map key must match calibration storage key format exactly
        map_key = None
        try:
            if mode == "online":
                map_key = self._app_state.calibration_manager.get_map_key(
                    "online",
                    self._app_state.current_map_provider,
                    self._app_state.current_area_id,
                )
            else:
                map_key = self._app_state.calibration_manager.get_map_key(
                    "local",
                    self._app_state.current_local_map or "default",
                )
        except Exception:
            map_key = None

        matrix_payload = None
        matrix = self._app_state.transform_matrix
        if matrix:
            # Lite script transform formula:
            #   lng = jsonX * scaleX + offsetX
            #   lat = -jsonY * scaleY + offsetY
            # and json = game * 100
            matrix_payload = {
                "mapKey": map_key,
                "scaleX": float(matrix.d) / 100.0,
                "scaleY": float(-matrix.b) / 100.0,
                "offsetX": float(matrix.f),
                "offsetY": float(matrix.c),
                "source": "python_app_state",
            }

        # Token / user data from settings (optional)
        token = None
        for key in ("map.user_token", "api.token", "wuwuddt.token", "account.token", "token"):
            v = self._settings.get(key, None)
            if isinstance(v, str) and v.strip():
                token = v.strip()
                break

        user_payload = None
        for key in ("map.user_info", "account.user", "wuwuddt.user"):
            v = self._settings.get(key, None)
            if isinstance(v, dict):
                user_id = v.get("userId") or v.get("user_id")
                user_name = v.get("userName") or v.get("user_name") or ""
                if user_id:
                    user_payload = {"userId": str(user_id), "userName": str(user_name)}
                    break
        if user_payload is None:
            user_id = self._settings.get("map.user_id", None)
            if user_id is not None and str(user_id).strip():
                user_payload = {
                    "userId": str(user_id).strip(),
                    "userName": str(self._settings.get("map.user_name", "") or ""),
                }

        return {
            "token": token,
            "user": user_payload,
            "mode": mode,
            "mapKey": map_key,
            "matrix": matrix_payload,
            "ts": int(datetime.now().timestamp() * 1000),
        }

    def _inject_kmp_runtime(self):
        if not self._web_view or not self._web_view.page():
            return
        payload = self._build_kmp_runtime_payload()
        payload_json = json.dumps(payload, ensure_ascii=False)
        js = f"""
        (function() {{
            try {{
                window.__KMP_RUNTIME = {payload_json};
                // 兼容旧逻辑：同步一份到 localStorage，避免脚本冷启动拿不到
                if (window.__KMP_RUNTIME && window.__KMP_RUNTIME.matrix) {{
                    localStorage.setItem('SM_COORD_TRANSFORM_V1', JSON.stringify(window.__KMP_RUNTIME.matrix));
                }}
                if (window.__KMP_RUNTIME && window.__KMP_RUNTIME.user) {{
                    localStorage.setItem('AKI_MAP_USER_INFO', JSON.stringify(window.__KMP_RUNTIME.user));
                }}
            }} catch (e) {{}}
        }})();
        """
        self._web_view.page().runJavaScript(js)

        try:
            m = payload.get("matrix")
            mk = payload.get("mapKey")
            mmk = m.get("mapKey") if isinstance(m, dict) else None
            status = "有矩阵" if isinstance(m, dict) else "无矩阵"
            self._app_state.append_system_log(f"Lite运行时注入: mapKey={mk}, matrixKey={mmk}, {status}", "INFO")
        except Exception:
            pass

    @Slot(bool)
    def _on_web_load_finished(self, ok: bool):
        if not ok:
            return
        self._refresh_python_overlay_after_web_load()
        self._inject_kmp_runtime()
        if self._supports_official_tile_metadata():
            self._install_tile_metadata_update_listener()
            QTimer.singleShot(1000, self._refresh_minimap_tile_cache)
        else:
            self._clear_ocr_vision_context()

    def _refresh_python_overlay_after_web_load(self):
        """Keep the Python-drawn center marker above QWebEngine after page reloads."""
        if not self._overlay_manager:
            return
        self._overlay_manager.show_overlay()
        QTimer.singleShot(300, self._overlay_manager.show_overlay)

    def _current_map_capabilities(self):
        return capabilities_for_current_map(
            self._app_state.current_mode,
            self._app_state.current_map_provider,
        )

    def _supports_official_tile_metadata(self) -> bool:
        return bool(self._current_map_capabilities().supports_official_tile_metadata)

    def _supports_minimap_visual_location(self) -> bool:
        return bool(self._current_map_capabilities().supports_minimap_visual_location)

    def _clear_ocr_vision_context(self):
        self._latest_tile_snapshot_result = None
        if self._ocr_manager and hasattr(self._ocr_manager, "update_vision_context"):
            self._ocr_manager.update_vision_context(None)

    def _install_tile_metadata_update_listener(self):
        if not self._web_view or not self._web_view.page():
            return
        js = build_tile_metadata_update_listener()
        self._web_view.page().runJavaScript(js)

    @Slot(str)
    def _on_tile_metadata_changed(self, updated_at: str):
        if not self._supports_official_tile_metadata():
            return
        if self._tile_metadata_refresh_pending:
            return
        self._tile_metadata_refresh_pending = True
        QTimer.singleShot(500, self._refresh_minimap_tile_cache_from_notification)

    def _refresh_minimap_tile_cache_from_notification(self):
        self._tile_metadata_refresh_pending = False
        self._refresh_minimap_tile_cache()

    def _refresh_minimap_tile_cache(self):
        if not self._supports_official_tile_metadata():
            self._clear_ocr_vision_context()
            return
        if not self._web_view or not self._web_view.page():
            return
        js = build_tile_metadata_snapshot_query()
        self._web_view.page().runJavaScript(js, self._on_tile_metadata_snapshot_received)

    def _on_tile_metadata_snapshot_received(self, result):
        if not self._supports_official_tile_metadata():
            self._clear_ocr_vision_context()
            return
        if not result:
            self._app_state.append_system_log("小地图瓦片快照: 无结果", "WARNING")
            return
        self._latest_tile_snapshot_result = result
        self._log_tile_metadata_snapshot_summary(result)
        self._update_ocr_vision_context_from_tile_snapshot(result)
        self._minimap_tile_sync_service.submit_snapshot(result)

    def _log_tile_metadata_snapshot_summary(self, result):
        try:
            snapshot = parse_tile_metadata_snapshot_result(result)
            if snapshot is None:
                self._app_state.append_system_log("小地图瓦片快照: 解析失败", "WARNING")
                return
            parts = []
            for field, label in (
                ("standardTiles", "standard"),
                ("layeredTiles", "layered"),
                ("gravityTiles", "gravity"),
            ):
                tiles = snapshot.get(field, []) or []
                if tiles:
                    xs = [int(tile.get("x")) for tile in tiles if tile.get("x") is not None]
                    ys = [int(tile.get("y")) for tile in tiles if tile.get("y") is not None]
                    area_ids = sorted({str(tile.get("regionId")) for tile in tiles if tile.get("regionId") is not None})
                    x_range = f"{min(xs)}..{max(xs)}" if xs else "n/a"
                    y_range = f"{min(ys)}..{max(ys)}" if ys else "n/a"
                    area_text = ",".join(area_ids[:5])
                    if len(area_ids) > 5:
                        area_text += f"+{len(area_ids) - 5}"
                    parts.append(f"{label}={len(tiles)} area={area_text or 'n/a'} x={x_range} y={y_range}")
                else:
                    parts.append(f"{label}=0")
            self._app_state.append_system_log(f"小地图瓦片快照: {'; '.join(parts)}", "INFO")
        except Exception as exc:
            self._app_state.append_system_log(f"小地图瓦片快照日志失败: {exc}", "WARNING")

    def _update_ocr_vision_context_from_tile_snapshot(self, result):
        if not self._ocr_manager:
            return
        try:
            envelope = json.loads(result) if isinstance(result, str) else result
            if not isinstance(envelope, dict) or not envelope.get("ok"):
                return
            data = envelope.get("data")
            if not isinstance(data, dict):
                return
            context = map_context_from_js(data.get("mapContext"))
            if context is None:
                return
            self._ocr_manager.update_vision_context(
                build_vision_snapshot(context, paths.minimap_tile_cache_dir())
            )
        except Exception as e:
            self._app_state.append_system_log(f"小地图视觉上下文更新失败: {e}", "ERROR")

    def _on_minimap_tile_sync_summary(self, summary):
        if getattr(summary, "error", None):
            self._append_system_log_threadsafe(f"小地图瓦片缓存更新失败: {summary.error}", "ERROR")
            return

        changed = list(getattr(summary, "changed_area_ids", ()) or ())
        failures = int(getattr(summary, "failure_count", 0) or 0)
        downloaded = int(getattr(summary, "downloaded_count", 0) or 0)
        pending = int(getattr(summary, "index_pending_count", 0) or 0)
        self._append_system_log_threadsafe(
            (
                "小地图瓦片下载检查: "
                f"输入{int(getattr(summary, 'input_count', 0) or 0)}个, "
                f"跳过{int(getattr(summary, 'skipped_count', 0) or 0)}个, "
                f"下载{downloaded}个, 失败{failures}个, 区域{changed}"
            ),
            "INFO" if not failures else "WARNING",
        )
        if downloaded or failures:
            self._append_system_log_threadsafe(
                f"小地图瓦片缓存更新: 下载{downloaded}个, 失败{failures}个, 区域{changed}",
                "INFO" if not failures else "WARNING",
            )
        queued_tiles = int(getattr(summary, "index_queued_tiles", 0) or 0)
        if queued_tiles:
            self._append_system_log_threadsafe(
                f"小地图瓦片索引队列: 新增{queued_tiles}个瓦片, 待处理{pending}项",
                "INFO",
            )
        stale_tiles = int(getattr(summary, "stale_queued_tiles", 0) or 0)
        if stale_tiles:
            self._append_system_log_threadsafe(
                f"小地图SIFT过期索引修复队列: 新增{stale_tiles}个瓦片, 待处理{pending}项",
                "INFO",
            )
        missing_items = int(getattr(summary, "missing_queued_items", 0) or 0)
        if missing_items:
            self._append_system_log_threadsafe(
                f"小地图索引补偿队列: 新增{missing_items}项, 待处理{pending}项",
                "INFO",
            )
        for area_id in changed:
            index_summary = self._minimap_tile_index_queue.health_summary(area_id)
            self._append_system_log_threadsafe(
                (
                    f"小地图索引状态: 区域{area_id} "
                    f"tiles={index_summary.get('tiles', 0)} "
                    f"rough_ready={index_summary.get('rough_ready', 0)} "
                    f"sift_ready={index_summary.get('sift_ready', 0)} "
                    f"rough_missing={index_summary.get('rough_missing', 0)} "
                    f"sift_missing={index_summary.get('sift_missing', 0)} "
                    f"failed={index_summary.get('failed', 0)}"
                ),
                "INFO",
            )

    def _append_system_log_threadsafe(self, message: str, level: str = "INFO"):
        self._system_log_requested.emit(str(message), str(level))

    def _on_minimap_tile_index_error(self, message):
        QTimer.singleShot(
            0,
            lambda: self._app_state.append_system_log(f"小地图瓦片索引失败: {message}", "WARNING"),
        )

    def _refresh_minimap_stitched_resources(self, changed_area_ids):
        snapshot = parse_tile_metadata_snapshot_result(self._latest_tile_snapshot_result)
        if snapshot is None:
            return
        context = map_context_from_js(snapshot.get("mapContext"))
        if context is None:
            return
        manifests = publish_stitched_resources_from_snapshot(
            snapshot,
            context=context,
            cache_root=paths.minimap_tile_cache_dir(),
            output_root=paths.minimap_tile_cache_dir(),
            changed_area_ids={str(area_id) for area_id in changed_area_ids},
        )
        if manifests:
            count = len(manifests)
            QTimer.singleShot(
                0,
                lambda: self._app_state.append_system_log(
                    f"小地图匹配资源已刷新: {context.area_id}，{count}个候选",
                    "INFO",
                ),
            )

    def _connect_web_download_handler(self):
        try:
            self._web_profile.downloadRequested.connect(self._on_web_download_requested)
        except Exception as e:
            print(f"下载处理器连接失败: {e}")

    def _on_web_download_requested(self, download_item):
        try:
            url = download_item.url().toString() if download_item and download_item.url() else ""
            destination = self._build_download_target_path(url, download_item)

            if self._should_use_python_download(url):
                download_item.cancel()
                self._app_state.append_system_log(f"下载已切换到Python代理: {url}", "INFO")
                self._start_python_download(url, destination)
                return

            # 非代理域名保持Qt默认下载流程（静默下载）
            save_dir = os.path.dirname(destination)
            save_name = os.path.basename(destination)
            download_item.setDownloadDirectory(save_dir)
            download_item.setDownloadFileName(save_name)
            if hasattr(download_item, "finished"):
                download_item.finished.connect(
                    lambda: self._on_qt_download_done(download_item, save_name)
                )
            download_item.accept()
            self._app_state.append_system_log(f"已交给浏览器下载器: {save_name}", "INFO")
        except Exception as e:
            self._app_state.append_system_log(f"下载接管失败，回退默认下载: {e}", "ERROR")
            try:
                download_item.accept()
            except Exception:
                pass

    def _on_qt_download_done(self, download_item, save_name: str):
        try:
            state_name = ""
            if hasattr(download_item, "state"):
                state = download_item.state()
                state_name = str(getattr(state, "name", state)).lower()
            if "cancel" in state_name or "interrupt" in state_name:
                return
            self._show_web_download_toast(f"✅ 下载完成: {save_name}")
        except Exception:
            # 不影响主流程
            pass

    def _should_use_python_download(self, url: str) -> bool:
        if not url:
            return False
        url_str = str(url)
        return (
            "wuwuddt.com" in url_str
            or "api.wuwuddt.com" in url_str
            or ".oss-cn-" in url_str
            or ".aliyuncs.com" in url_str
        )

    def _build_download_target_path(self, url: str, download_item) -> str:
        suggested_name = "download.bin"
        try:
            candidate = download_item.downloadFileName()
            if candidate:
                suggested_name = candidate
        except Exception:
            pass

        if (not suggested_name or suggested_name == "download.bin") and url:
            try:
                parsed = urlparse(url)
                from_path = os.path.basename(parsed.path)
                if from_path:
                    suggested_name = from_path
            except Exception:
                pass

        suggested_name = self._sanitize_filename(suggested_name)
        if is_route_export_download(url, suggested_name):
            download_dir = str(resolve_route_export_directory(self._settings))
        else:
            download_dir = self._get_download_dir()
        return self._ensure_unique_path(os.path.join(download_dir, suggested_name))

    def _get_download_dir(self) -> str:
        path = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not path:
            path = str(paths.runtime_dir("downloads"))
        os.makedirs(path, exist_ok=True)
        return path

    def _sanitize_filename(self, name: str) -> str:
        invalid = '<>:"/\\|?*'
        safe = "".join("_" if ch in invalid else ch for ch in (name or "download.bin"))
        safe = safe.strip().strip('.')
        return safe or "download.bin"

    def _ensure_unique_path(self, path: str) -> str:
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        index = 1
        while True:
            candidate = f"{base}({index}){ext}"
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _start_python_download(self, url: str, destination: str):
        self._python_download_executor.submit(self._run_python_download, url, destination)

    def _run_python_download(self, url: str, destination: str):
        try:
            import requests

            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(destination, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)

            QTimer.singleShot(
                0,
                lambda: self._on_python_download_done(destination),
            )
        except Exception as e:
            QTimer.singleShot(
                0,
                lambda: self._app_state.append_system_log(
                    f"Python代理下载失败: {e}", "ERROR"
                ),
            )

    def _on_python_download_done(self, destination: str):
        self._app_state.append_system_log(f"Python代理下载完成: {destination}", "INFO")
        self._show_web_download_toast(f"✅ 下载完成: {os.path.basename(destination)}")

    def _show_web_download_toast(self, message: str):
        if not self._web_view or not self._web_view.page():
            return

        msg_json = json.dumps(message)
        js = f"""
        (function() {{
            try {{
                if (typeof window.__gm_show_download_toast === 'function') {{
                    window.__gm_show_download_toast({msg_json});
                    return;
                }}

                var old = document.getElementById('__ww_download_toast_fallback');
                if (old && old.parentNode) old.parentNode.removeChild(old);

                var el = document.createElement('div');
                el.id = '__ww_download_toast_fallback';
                el.textContent = {msg_json};
                el.style.cssText = [
                    'position:fixed','right:16px','bottom:16px','z-index:2147483647',
                    'padding:10px 14px','border-radius:10px','background:rgba(28,28,32,.92)',
                    'color:#fff','font-size:13px','box-shadow:0 6px 20px rgba(0,0,0,.28)'
                ].join(';');
                el.addEventListener('mouseenter', function() {{
                    if (el && el.parentNode) el.parentNode.removeChild(el);
                }});
                (document.body || document.documentElement).appendChild(el);
                setTimeout(function() {{
                    if (el && el.parentNode) el.parentNode.removeChild(el);
                }}, 2000);
            }} catch (e) {{}}
        }})();
        """
        self._web_view.page().runJavaScript(js)
    
    def _init_interfaces(self):
        # 1. Home
        self._home_interface = HomeInterface(self._app_state, self)
        self._home_interface.setObjectName("homeInterface")
        
        # 2. Navigation (compact control panel)
        self._navigation_interface = NavigationInterface(self)
        self._navigation_interface.setObjectName("navigationInterface")
        
        # 3. OCR Settings
        self._ocr_settings_interface = OCRSettingsInterface(self)
        self._ocr_settings_interface.setObjectName("ocrSettingsInterface")
        
        # 4. Map Settings
        self._map_settings_interface = MapSettingsInterface(self)
        self._map_settings_interface.setObjectName("mapSettingsInterface")
        
        # 5. Route Settings
        self._route_settings_interface = RouteSettingsInterface(self)
        self._route_settings_interface.setObjectName("routeSettingsInterface")
        
        # 6. Hotkey
        self._hotkey_interface = HotkeyInterface(self._app_state, self)
        self._hotkey_interface.setObjectName("hotkeyInterface")
        
        # 7. Log
        self._log_interface = LogInterface(self._log_manager, self)
        self._log_interface.setObjectName("logInterface")
        
        # 8. Settings
        self._settings_interface = SettingsInterface(self._app_state, self)
        self._settings_interface.setObjectName("settingsInterface")
        if self._ocr_manager:
            self._settings_interface.set_gpu_configuration(self._ocr_manager.ocr_config)
            self._settings_interface.set_ocr_running(self._app_state.ocr_running)
        
        # 9. About
        self._about_interface = AboutInterface(self)
        self._about_interface.setObjectName("aboutInterface")
    
    def _init_navigation(self):
        # TOP section - main features
        self._navigation_i18n = [
            (self._home_interface, "nav_home", "首页"),
            (self._navigation_interface, "nav_navigation", "导航"),
            (self._ocr_settings_interface, "nav_ocr_settings", "识别设置"),
            (self._map_settings_interface, "nav_map_settings", "地图设置"),
            (self._route_settings_interface, "nav_route_recording", "路线录制"),
            (self._hotkey_interface, "nav_hotkeys", "快捷键"),
            (self._log_interface, "nav_logs", "日志"),
            (self._settings_interface, "nav_settings", "设置"),
            (self._about_interface, "nav_about", "关于"),
        ]

        self.addSubInterface(self._home_interface, FIF.HOME, tr("nav_home", "首页"))
        self.addSubInterface(self._navigation_interface, FIF.SEND, tr("nav_navigation", "导航"))
        self.addSubInterface(self._ocr_settings_interface, CustomFluentIcon.OCR_SETTINGS, tr("nav_ocr_settings", "识别设置"))
        self.addSubInterface(self._map_settings_interface, CustomFluentIcon.MAP_SETTINGS, tr("nav_map_settings", "地图设置"))
        self.addSubInterface(self._route_settings_interface, CustomFluentIcon.ROUTE_RECORDING, tr("nav_route_recording", "路线录制"))
        self.addSubInterface(self._hotkey_interface, CustomFluentIcon.HOTKEY, tr("nav_hotkeys", "快捷键"))
        self.addSubInterface(self._log_interface, FIF.DOCUMENT, tr("nav_logs", "日志"))
        
        self.navigationInterface.addSeparator()
        
        # BOTTOM section
        self.addSubInterface(
            self._settings_interface, FIF.SETTING, tr("nav_settings", "设置"),
            position=NavigationItemPosition.BOTTOM
        )
        self._about_nav_item = self.addSubInterface(
            self._about_interface, FIF.INFO, tr("nav_about", "关于"),
            position=NavigationItemPosition.BOTTOM
        )
        self._relax_navigation_min_height()

    def _set_navigation_item_text(self, interface, text: str):
        route_key = interface.objectName()
        try:
            item = self.navigationInterface.widget(route_key)
        except Exception:
            return

        if hasattr(item, "setText"):
            item.setText(text)
        if hasattr(item, "setToolTip"):
            item.setToolTip(text)

    def _retranslate_ui(self):
        self.setWindowTitle(tr("app_title", "呜呜大地图"))

        for interface, key, default in getattr(self, "_navigation_i18n", []):
            self._set_navigation_item_text(interface, tr(key, default))

        for interface in (
            self._home_interface,
            self._navigation_interface,
            self._ocr_settings_interface,
            self._map_settings_interface,
            self._route_settings_interface,
            self._hotkey_interface,
            self._log_interface,
            self._settings_interface,
            self._about_interface,
        ):
            retranslate = getattr(interface, "retranslate_ui", None)
            if callable(retranslate):
                retranslate()
    
    def _connect_signals(self):
        # Navigation Interface signals
        self._navigation_interface.ocr_start_requested.connect(self._start_ocr)
        self._navigation_interface.ocr_stop_requested.connect(self._stop_ocr)
        self._navigation_interface.ocr_calibrate_requested.connect(self._setup_ocr_region)
        self._navigation_interface.map_source_changed.connect(self._on_provider_changed)
        self._navigation_interface.map_calibrate_requested.connect(self._open_calibration)
        self._navigation_interface.map_recapture_requested.connect(self._recapture_map)
        self._navigation_interface.dot_size_changed.connect(self._on_dot_size_changed)
        self._navigation_interface.route_start_requested.connect(self._start_recording)
        self._navigation_interface.route_stop_requested.connect(self._stop_recording)
        self._navigation_interface.window_topmost_changed.connect(self._toggle_map_topmost)
        self._navigation_interface.window_passthrough_changed.connect(self._toggle_map_passthrough)
        self._navigation_interface.window_frameless_changed.connect(self._toggle_map_frameless)
        self._navigation_interface.window_opacity_changed.connect(self._on_opacity_changed)
        self._navigation_interface.main_topmost_changed.connect(self._toggle_main_topmost)

        # Connect AppState signals to Navigation Interface UI updates
        if self._app_state:
            self._app_state.map_status_updated.connect(self._navigation_interface.update_map_status)
            self._app_state.coordinates_detected.connect(self._navigation_interface.update_coordinates)
            self._app_state.ocr_state_changed.connect(
                lambda state: self._navigation_interface.update_ocr_status(state != "STOPPED")
            )
            self._app_state.ocr_state_changed.connect(self._on_ocr_running_changed)
            # Keep Lite runtime in sync with app state changes
            self._app_state.mode_changed.connect(lambda _v: self._inject_kmp_runtime())
            self._app_state.map_provider_changed.connect(lambda _v: self._inject_kmp_runtime())
            self._app_state.local_map_changed.connect(lambda _v: self._inject_kmp_runtime())
            self._app_state.area_id_changed.connect(lambda _v: self._inject_kmp_runtime())
            self._app_state.calibration_updated.connect(lambda _v: self._inject_kmp_runtime())
            self._app_state.mode_changed.connect(lambda _v: self._refresh_calibration_status_display())
            self._app_state.map_provider_changed.connect(lambda _v: self._refresh_calibration_status_display())
            self._app_state.local_map_changed.connect(lambda _v: self._refresh_calibration_status_display())
            self._app_state.area_id_changed.connect(lambda _v: self._refresh_calibration_status_display())
            self._app_state.calibration_updated.connect(lambda _v: self._refresh_calibration_status_display())
            try:
                self._app_state.area_id_changed.connect(self._navigation_interface.update_area_id)
            except Exception:
                pass
            try:
                self._app_state.ocr_area_source_changed.connect(
                    self._navigation_interface.update_ocr_region_source
                )
            except Exception:
                pass
            try:
                self._app_state.ocr_region_changed.connect(
                    self._navigation_interface.update_ocr_region
                )
            except Exception:
                pass

        # OCR Settings signals
        self._ocr_settings_interface.settings_changed.connect(self._reload_ocr_config)
        self._ocr_settings_interface.auto_detect_toggled.connect(self._on_ocr_auto_detect_toggled)
        self._ocr_settings_interface.window_select_requested.connect(self._setup_ocr_region)
        self._ocr_settings_interface.minimap_manual_calibration_requested.connect(self._setup_minimap_region)
        self._ocr_settings_interface.minimap_auto_calibration_toggled.connect(self._on_minimap_auto_calibration_toggled)
        
        # Connect OCR preview hover signals
        self._ocr_settings_interface.preview_hover_enter.connect(self._show_ocr_preview)
        self._ocr_settings_interface.preview_hover_leave.connect(self._hide_ocr_preview)
        if self._ocr_manager:
            try:
                self._ocr_manager.auto_window_status_changed.connect(
                    self._ocr_settings_interface.update_auto_window_status
                )
            except Exception:
                pass
            try:
                self._ocr_manager.auto_window_status_changed.connect(
                    self._on_auto_window_status
                )
            except Exception:
                pass
        
        # Map Settings signals
        self._map_settings_interface.map_source_changed.connect(self._on_provider_changed)
        self._map_settings_interface.calibration_requested.connect(self._open_calibration)
        self._map_settings_interface.auto_calibration_toggled.connect(self._on_auto_calibration_toggled)

        # Route Settings signals - 内嵌式路线列表
        self._route_settings_interface.view_detail_requested.connect(self._view_route_detail)
        self._route_settings_interface.export_route_requested.connect(self._export_route)
        self._route_settings_interface.delete_route_requested.connect(self._delete_route)

        # Hotkey Interface - 内嵌式设计，不再使用弹窗
        self._hotkey_interface.hotkeys_changed.connect(self._apply_hotkeys)
        
        try:
            self._log_interface.detailed_ocr_logging_toggled.connect(
                self._on_detailed_ocr_logging_toggled
            )
        except Exception:
            pass

        # Settings Interface
        self._settings_interface.language_changed.connect(self._on_language_changed)
        self._settings_interface.theme_changed.connect(self._on_theme_changed)
        self._settings_interface.gpu_acceleration_changed.connect(
            self._on_gpu_acceleration_changed
        )
        self._settings_interface.gpu_adapter_changed.connect(
            self._on_gpu_adapter_changed
        )
        if self._ocr_manager:
            self._ocr_manager.gpu_acceleration_failed.connect(
                self._on_gpu_acceleration_failed
            )
        try:
            self._settings_interface.log_settings_changed.connect(
                self._on_log_settings_changed
            )
        except Exception:
            pass

        # About Interface
        self._about_interface.check_update_requested.connect(self._on_check_update_requested)
        self._about_interface.start_update_requested.connect(self._on_start_update_requested)
        self._about_interface.open_download_requested.connect(self._on_open_update_download_requested)

        # 页面切换时控制日志自动刷新生命周期
        self._connect_log_page_lifecycle()

    def _relax_navigation_min_height(self):
        """避免导航栏的最小高度限制主窗口缩放"""
        try:
            nav = self.navigationInterface
            nav.setMinimumHeight(0)
            nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            panel = getattr(nav, "panel", None)
            if panel:
                panel.setMinimumHeight(0)
                panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        except Exception as e:
            print(f"放宽导航栏最小高度失败: {e}")
    
    def _post_init(self):
        if self._server_startup_error:
            self._app_state.append_system_log(self._server_startup_error, "ERROR")
            QMessageBox.warning(
                self,
                "本地地图服务启动失败",
                f"{self._server_startup_error}\n\n请关闭占用 58427 端口的程序后重启应用。"
            )

        self._load_current_map()
        self._auto_separate_map()
        self._home_interface.update_status()
        self._update_auto_calibration_availability()

        if self._hotkey_manager:
            # 从设置中加载并注册快捷键，再同步到界面
            saved_hotkeys = self._settings.get("global_hotkeys.hotkeys", DEFAULT_HOTKEYS.copy())
            if not isinstance(saved_hotkeys, dict):
                saved_hotkeys = DEFAULT_HOTKEYS.copy()

            merged_hotkeys = DEFAULT_HOTKEYS.copy()
            merged_hotkeys.update({k: v for k, v in saved_hotkeys.items() if k in DEFAULT_HOTKEYS})

            self._apply_hotkeys(merged_hotkeys)
            self._hotkey_interface.load_hotkeys(merged_hotkeys)

        # 设置路线记录器并加载路线列表
        if self._route_recorder:
            self._route_settings_interface.set_route_recorder(self._route_recorder)
            if self._navigation_interface:
                self._navigation_interface.update_route_status(False, 0)

        # 自动检测游戏窗口并设置默认OCR区域（受OCR设置开关控制）
        if self._ocr_manager and hasattr(self._ocr_manager, 'start_auto_window_detect'):
            if self._ocr_settings_interface and self._ocr_settings_interface.is_auto_detect_enabled():
                self._ocr_manager.start_auto_window_detect()
            elif hasattr(self._ocr_manager, 'stop_auto_window_detect'):
                self._ocr_manager.stop_auto_window_detect()

        if self._ocr_manager and hasattr(self._ocr_manager, 'set_detailed_ocr_logging'):
            try:
                enabled = bool(self._settings.get("logging.detailed_ocr_enabled", False))
                self._ocr_manager.set_detailed_ocr_logging(enabled)
            except Exception:
                pass
        self._sync_ocr_area_source_from_config()

        # 初始化透明覆盖层（中心圆点）
        self._setup_overlay_manager()

        # 系统启动完成日志
        self._app_state.append_system_log("=== 呜呜大地图系统启动完成 ===", "INFO")
        self._app_state.append_system_log("提示：请点击「启动 OCR」开始坐标识别", "INFO")
        # 启动后自动检查更新（异步，不阻塞UI）
        self._check_update_async(trigger="startup")
        # 初始化日志页激活状态
        self._sync_log_page_active_state()

    def _connect_log_page_lifecycle(self):
        try:
            stacked = getattr(self, "stackedWidget", None)
            if stacked is not None and hasattr(stacked, "currentChanged"):
                stacked.currentChanged.connect(self._sync_log_page_active_state)
        except Exception:
            pass

    def _sync_log_page_active_state(self, *_):
        try:
            stacked = getattr(self, "stackedWidget", None)
            is_log_active = bool(stacked is not None and stacked.currentWidget() is self._log_interface)
            self._log_interface.set_page_active(is_log_active)
        except Exception:
            pass

    def _on_check_update_requested(self):
        self._check_update_async(trigger="manual")

    def _check_update_async(self, trigger: str):
        if self._update_check_in_progress:
            self._app_state.append_system_log("更新检查进行中，已忽略重复请求", "INFO")
            return

        self._update_check_in_progress = True
        if self._about_interface:
            self._about_interface.set_update_checking()
        self._app_state.append_system_log(
            f"开始检查更新（来源: {'启动自动检查' if trigger == 'startup' else '手动检查'}）",
            "INFO"
        )

        self._update_check_executor.submit(self._run_update_check_thread, trigger)

    def _run_update_check_thread(self, trigger: str):
        try:
            result = self._update_provider.check(self._version_info.version)
            error_message = ""
        except Exception as e:
            result = None
            error_message = str(e)
        self._update_check_finished.emit(result, error_message, trigger)

    @Slot(object, str, str)
    def _on_update_check_finished(self, result, error_message: str, trigger: str):
        self._update_check_in_progress = False
        if result is None:
            reason = error_message or "未知错误"
            if self._about_interface:
                self._about_interface.set_update_failed(reason)
            self._app_state.append_system_log(
                f"更新检查失败: {reason}",
                "ERROR"
            )
            return
        self._on_update_check_result(result, trigger)

    def _on_update_check_result(self, result: UpdateResult, trigger: str):
        self._last_update_result = result
        checked_text = self._format_update_checked_at(result)
        if result.error_message:
            self._set_update_badges_visible(False)
            if self._about_interface:
                self._about_interface.set_update_failed(result.error_message)
            self._app_state.append_system_log(f"更新检查失败: {result.error_message}", "ERROR")
            return
        if result.has_update:
            self._set_update_badges_visible(True)
            can_auto_update = result.update_mode == "file" and getattr(sys, "frozen", False)
            if result.update_mode == "file" and not can_auto_update:
                self._app_state.append_system_log("源码运行模式不支持自动文件更新，请使用下载页手动更新", "WARNING")
            if self._about_interface:
                if result.update_mode == "full":
                    self._about_interface.set_update_full_required(
                        result.latest_version,
                        "当前版本需要下载安装完整新版",
                        checked_text
                    )
                else:
                    mode_text = self._update_mode_text(result.update_mode)
                    if result.update_mode == "file" and not can_auto_update:
                        mode_text = "打开下载页"
                    self._about_interface.set_update_available(
                        result.latest_version,
                        mode_text,
                        self._format_update_size(result.artifact_size),
                        checked_text,
                        can_auto_update=can_auto_update,
                        release_notes=result.release_notes,
                    )
            self._app_state.append_system_log(
                f"发现新版本: v{result.latest_version}（当前 v{result.current_version}）",
                "INFO"
            )
            self._show_update_dialog(result)
        else:
            self._set_update_badges_visible(False)
            if self._about_interface:
                self._about_interface.set_update_no_update(checked_text)
            self._app_state.append_system_log("当前已是最新版本", "INFO")

    def _format_update_checked_at(self, result: UpdateResult) -> str:
        try:
            return result.checked_at.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    def _format_update_size(self, size: int) -> str:
        if size <= 0:
            return "-"
        mb = size / (1024 * 1024)
        if mb >= 1:
            return f"{mb:.1f} MB"
        return f"{size / 1024:.1f} KB"

    def _update_mode_text(self, mode: str) -> str:
        if mode == "file":
            return "自动更新"
        if mode == "full":
            return "手动下载安装"
        return "打开下载页"

    def _set_update_badges_visible(self, visible: bool):
        if self._about_interface:
            self._about_interface.set_update_badge_visible(visible)

        if visible:
            if self._about_nav_item and self._about_nav_badge is None:
                self._about_nav_badge = DotInfoBadge.attension(
                    parent=self,
                    target=self._about_nav_item,
                    position=InfoBadgePosition.NAVIGATION_ITEM
                )
            if self._about_nav_badge is not None:
                self._about_nav_badge.show()
        elif self._about_nav_badge is not None:
            self._about_nav_badge.hide()

    def _show_update_dialog(self, result: UpdateResult):
        if result.update_mode == "file" and getattr(sys, "frozen", False):
            self._show_file_update_dialog(result)
        else:
            self._show_full_update_dialog(result)

    def _show_file_update_dialog(self, result: UpdateResult):
        notes = result.release_notes.strip() if result.release_notes else "暂无更新说明"
        text = (
            f"发现新版本 v{result.latest_version}\n\n"
            f"更新内容：\n{notes}\n\n"
            f"是否立即更新？"
        )

        msg = QMessageBox(self)
        msg.setWindowTitle("发现新版本")
        msg.setText(text)
        later_btn = msg.addButton("稍后", QMessageBox.RejectRole)
        update_btn = msg.addButton("立即更新", QMessageBox.AcceptRole)
        msg.exec()

        if msg.clickedButton() == update_btn:
            self._start_file_update(result)
        elif msg.clickedButton() == later_btn:
            self._app_state.append_system_log("已关闭更新弹窗（保留红点提示）", "INFO")

    def _show_full_update_dialog(self, result: UpdateResult):
        notes = result.release_notes.strip() if result.release_notes else "暂无更新说明"
        text = (
            f"发现新版本 v{result.latest_version}\n\n"
            f"更新内容：\n{notes}\n\n"
            f"是否打开下载页面？"
        )

        msg = QMessageBox(self)
        msg.setWindowTitle("发现新版本")
        msg.setText(text)
        later_btn = msg.addButton("稍后", QMessageBox.RejectRole)
        download_btn = msg.addButton("打开下载页", QMessageBox.AcceptRole)
        msg.exec()

        if msg.clickedButton() == download_btn:
            self._open_update_download_url(result)
        elif msg.clickedButton() == later_btn:
            self._app_state.append_system_log("已关闭更新弹窗（保留红点提示）", "INFO")

    def _on_start_update_requested(self):
        if (
            self._last_update_result
            and self._last_update_result.has_update
            and self._last_update_result.update_mode == "file"
        ):
            self._start_file_update(self._last_update_result)
        else:
            self._app_state.append_system_log("当前没有可自动更新的版本", "INFO")

    def _on_open_update_download_requested(self):
        if self._last_update_result:
            self._open_update_download_url(self._last_update_result)
        else:
            QDesktopServices.openUrl(QUrl(self._version_info.update_base_url or "https://wuwuddt.com"))

    def _open_update_download_url(self, result: UpdateResult):
        target_url = (
            result.download_url
            or result.installer_url
            or self._version_info.update_base_url
            or "https://wuwuddt.com"
        )
        QDesktopServices.openUrl(QUrl(target_url))
        self._app_state.append_system_log(f"已打开下载页面: {target_url}", "INFO")

    def _app_root_for_update(self) -> Path:
        return paths.app_root()

    def _main_exe_name_for_update(self) -> str:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).name
        return "WutheringWaves-Navigator-Smart.exe"

    def _updater_exe_path(self) -> Path:
        return self._app_root_for_update() / "WutheringWaves-Updater.exe"

    def _update_apply_lock_path(self) -> Path:
        return self._app_root_for_update() / ".update" / "apply.lock"

    def _start_file_update(self, result: UpdateResult):
        if not getattr(sys, "frozen", False):
            self._app_state.append_system_log("源码运行模式不支持自动文件更新，已打开下载页", "WARNING")
            QMessageBox.warning(self, "无法自动更新", "源码运行模式不支持自动文件更新，请打开下载页手动下载。")
            self._open_update_download_url(result)
            return
        if not result.manifest_url:
            QMessageBox.warning(self, "无法自动更新", "更新信息不完整，请打开下载页手动下载。")
            self._open_update_download_url(result)
            return
        if not result.updater_url or len(result.updater_sha256) != 64:
            QMessageBox.warning(
                self,
                tr("update_auto_unavailable_title", "无法自动更新"),
                tr(
                    "update_updater_metadata_incomplete",
                    "更新器信息不完整，请打开下载页手动下载。",
                ),
            )
            self._open_update_download_url(result)
            return
        lock_path = self._update_apply_lock_path()
        if lock_path.exists():
            QMessageBox.information(self, "更新正在应用", "更新器已经在运行，请稍等。")
            self._app_state.append_system_log(f"更新器锁已存在: {lock_path}", "INFO")
            return
        if self._updater_prepare_in_progress:
            self._app_state.append_system_log(
                tr(
                    "update_updater_prepare_duplicate",
                    "更新器准备中，已忽略重复请求",
                ),
                "INFO",
            )
            return

        self._updater_prepare_in_progress = True
        self._show_updater_prepare_dialog()
        self._app_state.append_system_log(
            tr("update_updater_preparing", "正在校验并准备更新器"),
            "INFO",
        )
        try:
            self._update_check_executor.submit(self._run_updater_prepare_thread, result)
        except Exception as exc:
            self._updater_prepare_in_progress = False
            self._close_updater_prepare_dialog()
            message = tr(
                "update_updater_prepare_failed",
                "准备更新器失败: {error}",
                error=exc,
            )
            QMessageBox.warning(
                self,
                tr("update_apply_unavailable_title", "无法应用更新"),
                message,
            )
            self._app_state.append_system_log(message, "ERROR")

    def _show_updater_prepare_dialog(self):
        dialog = QProgressDialog(
            tr("update_updater_prepare_detail", "正在下载并校验更新器，请稍候。"),
            None,
            0,
            0,
            self,
        )
        dialog.setWindowTitle(tr("update_updater_prepare_title", "正在准备更新"))
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.show()
        self._updater_prepare_dialog = dialog

    def _close_updater_prepare_dialog(self):
        if self._updater_prepare_dialog is not None:
            self._updater_prepare_dialog.close()
            self._updater_prepare_dialog.deleteLater()
            self._updater_prepare_dialog = None

    def _run_updater_prepare_thread(self, result: UpdateResult):
        try:
            replaced = prepare_updater_binary(
                updater_path=self._updater_exe_path(),
                updater_url=result.updater_url,
                updater_sha256=result.updater_sha256,
                staging_dir=self._app_root_for_update() / ".update" / "bootstrap",
            )
            error_message = ""
        except Exception as exc:
            replaced = False
            error_message = str(exc)
        self._updater_prepare_finished.emit(result, error_message, replaced)

    @Slot(object, str, bool)
    def _on_updater_prepare_finished(self, result: UpdateResult, error_message: str, replaced: bool):
        self._updater_prepare_in_progress = False
        self._close_updater_prepare_dialog()
        if error_message:
            message = tr(
                "update_updater_update_failed",
                "更新器更新失败: {error}",
                error=error_message,
            )
            QMessageBox.warning(
                self,
                tr("update_apply_unavailable_title", "无法应用更新"),
                message,
            )
            self._app_state.append_system_log(message, "ERROR")
            return
        if replaced:
            self._app_state.append_system_log(
                tr("update_updater_updated", "更新器已更新并通过哈希校验"),
                "INFO",
            )
        else:
            self._app_state.append_system_log(
                tr(
                    "update_updater_already_current",
                    "当前更新器已是目标版本",
                ),
                "INFO",
            )
        self._launch_file_updater(result)

    def _launch_file_updater(self, result: UpdateResult):
        updater = self._updater_exe_path()
        if not updater.exists():
            QMessageBox.warning(self, "无法应用更新", "未找到更新器，请打开下载页手动下载新版。")
            self._app_state.append_system_log(f"未找到更新器: {updater}", "ERROR")
            return
        args = build_updater_command(
            updater_path=updater,
            app_root=self._app_root_for_update(),
            main_exe=self._main_exe_name_for_update(),
            result=result,
            wait_pid=os.getpid(),
        )
        self._pending_update_command = args
        if self.close():
            return

        self._pending_update_command = None
        message = tr(
            "update_updater_close_failed",
            "主程序未能关闭，更新未启动。",
        )
        QMessageBox.warning(
            self,
            tr("update_apply_unavailable_title", "无法应用更新"),
            message,
        )
        self._app_state.append_system_log(message, "ERROR")

    def take_pending_update_command(self) -> Optional[list[str]]:
        command = self._pending_update_command
        self._pending_update_command = None
        return command

    def _setup_overlay_manager(self):
        """设置透明覆盖层管理器（中心圆点）"""
        try:
            from transparent_overlay import OverlayManager

            # 创建覆盖层管理器
            self._overlay_manager = OverlayManager(self._web_view, self._resource_probe)

            # 设置初始圆点大小（从导航界面获取）
            if self._navigation_interface:
                initial_percent = 50.0
                if hasattr(self._navigation_interface, 'get_dot_size_percent'):
                    initial_percent = float(self._navigation_interface.get_dot_size_percent())
                elif hasattr(self._navigation_interface, 'dot_size_slider'):
                    raw_value = float(self._navigation_interface.dot_size_slider.value())
                    initial_percent = raw_value / 10.0 if raw_value > 200 else raw_value

                initial_radius_px = initial_percent / 10.0  # 50.0% -> 5.0px
                self._overlay_manager.set_circle_radius(initial_radius_px)

            # Z轴颜色映射默认启用（符合新UI设计 - 没有开关，默认启用）
            self._overlay_manager.set_z_color_mapping(True)

            # 显示覆盖层（默认可见）
            self._overlay_manager.show_overlay()

            print("透明覆盖层初始化成功")
        except ImportError:
            print("Transparent overlay module not available")
            self._overlay_manager = None
        except Exception as e:
            print(f"透明覆盖层初始化失败: {e}")
            import traceback
            traceback.print_exc()
            self._overlay_manager = None
    
    def _load_current_map(self):
        mode = self._app_state.current_mode
        if mode == "online":
            lang = "zh_CN"
            if LANGUAGE_AVAILABLE:
                lm = get_language_manager()
                if lm:
                    lang = lm.get_current_language()

            urls = get_map_urls(lang)
            provider = self._app_state.current_map_provider
            url = urls.get(provider, urls["official_map"])
            self._app_state.current_url = url
            self._web_view.setUrl(QUrl(url))
        else:
            local_url = "http://localhost:58427/index.html"
            self._app_state.current_url = local_url
            self._web_view.setUrl(QUrl(local_url))

        # 延迟加载校准数据，确保地图已加载
        QTimer.singleShot(500, self._load_or_fetch_calibration_for_current_map)
    
    def _auto_separate_map(self):
        try:
            from separated_map_window import SeparatedMapWindow
            self._separated_map_window = SeparatedMapWindow(self._web_view, self)
            self._separated_map_window.window_closed.connect(self._on_map_window_closed)
            self._separated_map_window.show_with_geometry_memory(self.geometry(), self._load_map_window_geometry())
            self._apply_map_window_flags()
        except ImportError:
            print("Separated map window not available")

    def _remember_map_window_geometry_enabled(self) -> bool:
        return bool(self._settings.get("window.remember_map_window_geometry", True))

    def _load_map_window_geometry(self) -> Optional[QRect]:
        if not self._remember_map_window_geometry_enabled():
            return None

        data = self._settings.get("window.map_window_geometry", None)
        if not isinstance(data, dict):
            return None

        try:
            return QRect(
                int(data["x"]),
                int(data["y"]),
                int(data["width"]),
                int(data["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _save_map_window_geometry(self):
        if not self._separated_map_window:
            return
        if not self._remember_map_window_geometry_enabled():
            return

        geometry = self._separated_map_window.geometry()
        self._settings.set("window.map_window_geometry",
            {
                "x": int(geometry.x()),
                "y": int(geometry.y()),
                "width": int(geometry.width()),
                "height": int(geometry.height()),
            },
            save=True,
        )
    
    @Slot(float, float, int)
    def _on_map_status_updated(self, lat: float, lng: float, zoom: int):
        self._app_state.update_map_status(lat, lng, zoom)

    @Slot(QUrl)
    def _on_url_changed(self, url: QUrl):
        """Handle URL changes to track area_id for online maps."""
        url_string = url.toString()
        self._app_state.current_url = url_string

        if self._app_state.current_mode != 'online':
            return

        new_area_id = None

        if "kurobbs.com" in url_string:
            parsed_url = urlparse(url_string)
            query_params = parse_qs(parsed_url.query)
            new_area_id = query_params.get('state', [None])[0] or "8"
        if not new_area_id:
            return

        if self._app_state.current_area_id != new_area_id:
            self._app_state.append_system_log(
                f"检测到区域切换: {self._app_state.current_area_id} -> {new_area_id}", "INFO"
            )
            if self._ocr_manager and hasattr(self._ocr_manager, "reset_coordinate_continuity"):
                self._ocr_manager.reset_coordinate_continuity("area_changed")
            self._app_state.current_area_id = new_area_id
            self._recapture_map()
            QTimer.singleShot(1000, self._load_or_fetch_calibration_for_current_map)
    
    @Slot(str)
    def _on_local_map_changed(self, map_name: str):
        """接收来自JS的本地地图切换通知"""
        self._app_state.current_local_map = map_name
        # 触发重新捕获
        self._recapture_map()
        # 延迟加载校准数据，确保地图已切换完成
        QTimer.singleShot(1000, self._load_or_fetch_calibration_for_current_map)

    def _deliver_proxy_response_via_js(self, req_id: str, status: int, text: str, headers: str):
        """通过 runJavaScript 直接调用 JS 的 _handleProxyResponse，绕过 QWebChannel 信号"""
        try:
            # 转义字符串中的特殊字符
            import json
            req_id_escaped = json.dumps(req_id)
            text_escaped = json.dumps(text)
            headers_escaped = json.dumps(headers)

            js_code = f"if(window._handleProxyResponse) {{ window._handleProxyResponse({req_id_escaped}, {status}, {text_escaped}, {headers_escaped}); }}"

            if self._web_page:
                self._web_page.runJavaScript(js_code)
                print(f"[Proxy] Delivered response to JS via runJavaScript for {req_id}")
        except Exception as e:
            print(f"[Proxy] Error delivering response via JS: {e}")
    
    @Slot(str)
    def _on_mode_changed(self, mode: str):
        self._app_state.current_mode = mode
        self._app_state.reset_auto_calibration_cache()
        self._update_auto_calibration_availability()
        self._load_current_map()
    
    @Slot(str)
    def _on_provider_changed(self, provider: str):
        """处理地图源切换（包括模式切换和provider切换）"""
        # 'local' 是模式切换，其他是provider切换
        if provider == "local":
            self._app_state.current_mode = "local"
            self._app_state.append_system_log("切换到本地地图模式", "INFO")
        else:
            self._app_state.current_mode = "online"
            # 映射UI发送的简短名称到实际的provider key
            provider_map = {
                "official": "official_map",
            }
            actual_provider = provider_map.get(provider, provider)
            if actual_provider != "official_map":
                actual_provider = "official_map"
            self._app_state.current_map_provider = actual_provider

            # 用户友好的提供商名称
            provider_names = {
                "official_map": "库街区",
            }
            provider_name = provider_names.get(actual_provider, actual_provider)
            self._app_state.append_system_log(f"切换到在线地图: {provider_name}", "INFO")

        self._app_state.reset_auto_calibration_cache()
        self._update_auto_calibration_availability()
        self._load_current_map()

    @Slot(bool)
    def _on_auto_calibration_toggled(self, enabled: bool):
        if enabled:
            self._app_state.append_system_log("自动校准已开启", "INFO")
            self._load_or_fetch_calibration_for_current_map()
        else:
            self._app_state.append_system_log("自动校准已关闭", "INFO")
            if self._auto_calibration_polling_timer.isActive():
                self._auto_calibration_polling_timer.stop()
                self._auto_calibration_fetching = False
            self._app_state.load_calibration_for_current_map()

    def _is_auto_calibration_available(self) -> bool:
        return (
            self._app_state.current_mode == "online"
            and self._app_state.current_map_provider == "official_map"
        )

    def _is_auto_calibration_enabled(self) -> bool:
        if not self._map_settings_interface:
            return False
        return (
            self._is_auto_calibration_available()
            and self._map_settings_interface.is_auto_calibration_enabled()
        )

    def _update_auto_calibration_availability(self):
        if not self._map_settings_interface:
            return
        self._map_settings_interface.set_auto_calibration_available(
            self._is_auto_calibration_available()
        )
        self._refresh_calibration_status_display()

    def _current_calibration_status_text(self):
        matrix = self._app_state.transform_matrix
        if matrix:
            return f"已校准  {self._app_state.get_current_map_identifier()}", True
        return "未校准", False

    def _refresh_calibration_status_display(self, text: str = None, ok: bool = None):
        if text is None:
            text, ok = self._current_calibration_status_text()
        if ok is None:
            ok = False
        try:
            self._navigation_interface.update_calibration_status(text, ok)
        except Exception:
            pass
        try:
            self._map_settings_interface.update_calibration_status(text, ok)
        except Exception:
            pass

    def _load_or_fetch_calibration_for_current_map(self):
        self._app_state.load_calibration_for_current_map()
        if self._is_auto_calibration_enabled():
            self._refresh_calibration_status_display("自动校准获取中", False)
            self.fetch_auto_calibration()

    def _apply_auto_calibration(self):
        matrix = self._app_state.auto_calibration_matrix
        if matrix:
            self._app_state.transform_matrix = matrix
            self._app_state.append_system_log("自动校准已应用", "INFO")
            return True
        return False

    def fetch_auto_calibration(self):
        if not self._is_auto_calibration_enabled():
            return
        if self._auto_calibration_fetching:
            return

        self._auto_calibration_fetching = True
        js_code = """
        (function() {
            try {
                if (typeof window.getCoordTransform === 'function') {
                    const result = window.getCoordTransform();
                    if (result) {
                        return JSON.stringify(result);
                    }
                }
            } catch (e) {
            }
            return null;
        })();
        """
        self._web_view.page().runJavaScript(js_code, self._on_auto_calibration_received)

    def _on_auto_calibration_received(self, result):
        self._auto_calibration_fetching = False

        if not self._is_auto_calibration_enabled():
            if self._auto_calibration_polling_timer.isActive():
                self._auto_calibration_polling_timer.stop()
            return

        if not result:
            if not self._auto_calibration_polling_timer.isActive():
                self._auto_calibration_polling_timer.start()
            return

        try:
            data = json.loads(result) if isinstance(result, str) else result
            scale_x = float(data.get("scaleX"))
            scale_y = float(data.get("scaleY"))
            offset_x = float(data.get("offsetX"))
            offset_y = float(data.get("offsetY"))
        except Exception:
            if not self._auto_calibration_polling_timer.isActive():
                self._auto_calibration_polling_timer.start()
            return

        matrix = TransformMatrix(
            a=0.0,
            b=-100.0 * scale_y,
            c=offset_y,
            d=100.0 * scale_x,
            e=0.0,
            f=offset_x,
        )

        self._app_state.auto_calibration_matrix = matrix
        self._app_state.auto_calibration_cached = True
        self._app_state.transform_matrix = matrix
        self._app_state.append_system_log("自动校准获取成功", "INFO")

        if self._auto_calibration_polling_timer.isActive():
            self._auto_calibration_polling_timer.stop()
    
    def _recapture_map(self):
        js = build_map_control_command({"type": "recaptureMap", "source": "manual"})
        self._web_view.page().runJavaScript(js)
        QTimer.singleShot(1000, self._refresh_minimap_tile_cache)
    
    def _start_ocr(self):
        if self._ocr_manager and not self._app_state.ocr_running:
            success = self._ocr_manager.start_ocr()
            if success:
                self._app_state.ocr_running = True
                self._app_state.append_system_log("OCR识别已启动", "INFO")
            else:
                # 启动失败，显示错误信息
                self._app_state.append_system_log("OCR识别启动失败", "ERROR")

    def _stop_ocr(self):
        if self._ocr_manager and self._app_state.ocr_running:
            stopped = self._ocr_manager.stop_ocr()
            if stopped:
                self._app_state.ocr_running = False
                self._app_state.append_system_log("OCR识别已停止", "INFO")
            else:
                self._app_state.append_system_log("OCR识别停止超时", "ERROR")

    def _start_recording(self):
        if self._route_recorder and not self._app_state.recording_active:
            # 与旧版行为对齐：未开启 OCR 时不允许开始录制
            if not self._app_state.ocr_running:
                self._app_state.append_system_log("无法开始录制：请先启动 OCR 识别", "ERROR")
                return

            route_name = "route_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            started = self._route_recorder.start_recording(route_name)
            if not started:
                self._app_state.append_system_log("路线录制启动失败", "ERROR")
            
    def _stop_recording(self):
        if self._route_recorder and self._app_state.recording_active:
            self._route_recorder.stop_recording()
            
    def _on_dot_size_changed(self, percent: float):
        """圆点大小变化处理（percent -> px）"""
        if self._overlay_manager:
            clamped_percent = max(1.0, min(200.0, float(percent)))
            radius_px = clamped_percent / 10.0  # 5px = 50%
            self._overlay_manager.set_circle_radius(radius_px)
            print(f"圆点大小已调整为: {clamped_percent:.1f}% ({radius_px:.1f}px)")

    def _reload_ocr_config(self):
        if not self._ocr_manager or not self._ocr_settings_interface:
            return

        try:
            screenshot_mode = self._ocr_settings_interface.get_screenshot_mode()
            interval = self._ocr_settings_interface.get_interval()
            target_window = self._ocr_settings_interface.get_target_window_name()
            digit_conf = self._ocr_settings_interface.get_digit_confidence_threshold()
            symbol_conf = self._ocr_settings_interface.get_symbol_confidence_threshold()
            auto_detect_enabled = self._ocr_settings_interface.is_auto_detect_enabled()
            heading_enabled = self._ocr_settings_interface.is_heading_recognition_enabled()

            self._ocr_manager.ocr_config['screenshot_mode'] = screenshot_mode
            self._ocr_manager.ocr_config['ocr_interval'] = int(interval)
            self._ocr_manager.ocr_config['digit_confidence_threshold'] = float(digit_conf)
            self._ocr_manager.ocr_config['symbol_confidence_threshold'] = float(symbol_conf)
            self._ocr_manager.ocr_config['auto_detect_region_enabled'] = bool(auto_detect_enabled)
            if not auto_detect_enabled:
                self._ocr_manager.ocr_config['target_window_name'] = target_window
            self._settings.set("minimap_stability.heading_recognition_enabled", bool(heading_enabled))
            self._ocr_manager.save_config()

            worker = self._ocr_manager.ocr_worker
            if worker is not None and getattr(worker, 'is_running', False):
                try:
                    worker.update_interval(int(interval))
                except Exception:
                    pass
                try:
                    worker.update_confidence_thresholds(float(digit_conf), float(symbol_conf))
                except Exception:
                    pass
                try:
                    worker.update_screenshot_mode(screenshot_mode)
                except Exception:
                    pass
                try:
                    area = self._ocr_manager.ocr_config.get('ocr_capture_area') or {}
                    active_target = self._ocr_manager.ocr_config.get('target_window_name', '')
                    game_rect = self._ocr_manager._current_game_window_rect
                    minimap_search_region = (
                        self._ocr_manager._calculate_minimap_search_region(game_rect)
                        if auto_detect_enabled and game_rect is not None
                        else None
                    )
                    worker.update_capture_settings(
                        area,
                        int(interval),
                        active_target,
                        minimap_search_region,
                    )
                except Exception:
                    pass
        except Exception as e:
            self._app_state.append_system_log(f"刷新OCR配置失败: {e}", "ERROR")

    @Slot(bool)
    def _on_detailed_ocr_logging_toggled(self, enabled: bool):
        if not self._ocr_manager or not hasattr(self._ocr_manager, 'set_detailed_ocr_logging'):
            return
        self._ocr_manager.set_detailed_ocr_logging(enabled)
        self._app_state.append_system_log(
            f"详细识别日志已{'开启' if enabled else '关闭'}", "INFO"
        )

    @Slot(bool)
    def _on_ocr_auto_detect_toggled(self, enabled: bool):
        if not self._ocr_manager:
            return
        if enabled:
            if hasattr(self._ocr_manager, 'start_auto_window_detect'):
                self._ocr_manager.start_auto_window_detect()
            self._app_state.append_system_log("OCR自动校准已开启（自动检测窗口）", "INFO")
        else:
            if hasattr(self._ocr_manager, 'stop_auto_window_detect'):
                self._ocr_manager.stop_auto_window_detect()
            if self._ocr_settings_interface:
                self._ocr_manager.ocr_config['target_window_name'] = (
                    self._ocr_settings_interface.get_target_window_name()
                )
            restored = False
            if hasattr(self._ocr_manager, 'restore_manual_region_if_available'):
                restored = self._ocr_manager.restore_manual_region_if_available()
            if not restored:
                self._sync_ocr_area_source_from_config()
            self._app_state.append_system_log("OCR自动校准已关闭（自动检测窗口）", "INFO")

    @Slot(dict)
    def _on_auto_window_status(self, status: dict):
        if not self._app_state:
            return

        state = status.get("state", "")
        countdown = status.get("countdown", 0)
        title = status.get("title", "")
        mode = status.get("mode", "")
        width = status.get("width")
        height = status.get("height")
        x = status.get("x")
        y = status.get("y")
        message = status.get("message", "")

        mode_map = {
            "fullscreen": "全屏",
            "borderless": "无边框窗口",
            "windowed": "窗口"
        }
        mode_text = mode_map.get(mode, "--")

        if state == "searching":
            if countdown == 5:
                self._app_state.append_system_log("自动窗口检测：未找到游戏窗口，5秒后重试…")
            return

        if state == "error":
            self._app_state.append_system_log(f"自动窗口检测失败：{message}", level="ERROR")
            return

        if state == "manual_skip":
            info = (
                f"自动窗口检测：识别到“{title}”，已存在手动OCR区域，未覆盖。"
                f" 模式：{mode_text} 分辨率：{width}*{height} 位置：{x}*{y}"
            )
            self._app_state.append_system_log(info)
            return

        if state == "found":
            info = (
                f"自动窗口检测：识别到“{title}”。"
                f" 模式：{mode_text} 分辨率：{width}*{height} 位置：{x}*{y}"
            )
            self._app_state.append_system_log(info)

    def _toggle_ocr(self):
        if not self._ocr_manager:
            return
        
        if self._app_state.ocr_running:
            self._stop_ocr()
        else:
            self._start_ocr()
    
    def _setup_ocr_region(self):
        """启动OCR区域校准（手动框选）"""
        if self._ocr_manager:
            self._app_state.append_system_log("OCR区域校准已启动", "INFO")
            self._ocr_manager.setup_ocr_region()

    def _setup_minimap_region(self):
        """启动小地图区域校准（手动框选）"""
        try:
            from ocr_region_calibrator import OCRRegionCalibrator

            if self._minimap_region_calibrator is not None:
                self._minimap_region_calibrator.close()
                self._minimap_region_calibrator = None

            self._minimap_region_calibrator = OCRRegionCalibrator(
                QApplication.instance(),
                region_label="小地图区域",
                selection_shape="circle",
                shift_forces_circle=True,
            )
            self._minimap_region_calibrator.region_shape_selected.connect(self._on_minimap_region_selected)
            self._minimap_region_calibrator.selection_cancelled.connect(self._on_minimap_region_cancelled)
            self._minimap_region_calibrator.show()
            self._minimap_region_calibrator.raise_()
            self._minimap_region_calibrator.activateWindow()
            self._app_state.append_system_log("小地图位置手动校准已启动", "INFO")
        except Exception as e:
            self._minimap_region_calibrator = None
            self._app_state.append_system_log(f"启动小地图位置校准失败: {e}", "ERROR")

    @Slot(int, int, int, int, str)
    def _on_minimap_region_selected(self, x: int, y: int, width: int, height: int, shape: str = "circle"):
        if self._ocr_manager and hasattr(self._ocr_manager, "normalize_minimap_manual_selection"):
            roi = self._ocr_manager.normalize_minimap_manual_selection(x, y, width, height)
        else:
            roi = MinimapRoi(int(x), int(y), int(width), int(height), "circle", "manual")

        self._settings.set("minimap_roi.x", int(roi.x), save=False)
        self._settings.set("minimap_roi.y", int(roi.y), save=False)
        self._settings.set("minimap_roi.width", int(roi.width), save=False)
        self._settings.set("minimap_roi.height", int(roi.height), save=False)
        self._settings.set("minimap_roi.shape", "circle", save=False)
        self._settings.set("minimap_roi.source", "manual", save=False)
        self._settings.set("minimap_roi.status", "locked", save=False)
        self._settings.save()

        self._app_state.append_system_log(
            f"小地图位置已保存: x={roi.x}, y={roi.y}, width={roi.width}, height={roi.height}",
            "INFO",
        )
        self._minimap_region_calibrator = None

    def _on_minimap_region_cancelled(self):
        self._app_state.append_system_log("小地图位置手动校准已取消", "INFO")
        self._minimap_region_calibrator = None

    def _request_minimap_auto_recalibration(self):
        if self._ocr_manager:
            self._ocr_manager.start_minimap_auto_search()
        self._app_state.append_system_log("小地图自动校准已开始", "INFO")

    def _on_minimap_auto_calibration_toggled(self, enabled: bool):
        if enabled:
            self._request_minimap_auto_recalibration()
            return
        if self._ocr_manager:
            self._ocr_manager.stop_minimap_auto_search()
        self._app_state.append_system_log("小地图自动校准已关闭", "INFO")

    @Slot(dict)
    def _on_minimap_roi_locked(self, payload):
        try:
            self._app_state.append_system_log(
                "小地图位置自动校准已锁定: "
                f"x={payload.get('x')}, y={payload.get('y')}, "
                f"width={payload.get('width')}, height={payload.get('height')}",
                "INFO",
            )
        except Exception:
            pass

    @Slot(int, int, int)
    def _on_ocr_coordinates_detected(self, x: int, y: int, z: int):
        if self._resource_probe:
            self._resource_probe.count("ocr.coordinates")
        self._app_state.update_ocr_coordinates(x, y, z)
        self._app_state.append_system_log(f"OCR检测到坐标: ({x}, {y}, {z})", "INFO")

        # 录制开启时自动写入路线点（去重/节流在 RouteRecorder 内部处理）
        if self._route_recorder and self._app_state.recording_active:
            self._route_recorder.record_point(x, y, z)

        try:
            if self._ocr_manager and getattr(self._ocr_manager, "auto_jump_enabled", True):
                self._ocr_auto_jump(x, y, z)
        except Exception as e:
            self._app_state.append_system_log(f"OCR自动跳转失败: {e}", "ERROR")

        # 更新覆盖层的Z值，用于颜色映射（Z轴颜色映射默认启用）
        if self._overlay_manager:
            self._overlay_manager.set_z_value(z)
            heading_candidate = (
                getattr(self._ocr_manager, "latest_heading_candidate", None)
                if self._ocr_manager is not None
                else None
            )
            if isinstance(heading_candidate, dict):
                try:
                    heading_degrees = float(heading_candidate.get("angle_degrees"))
                    if math.isfinite(heading_degrees):
                        self._overlay_manager.set_heading_degrees(heading_degrees)
                    else:
                        self._overlay_manager.clear_heading()
                except (TypeError, ValueError):
                    self._overlay_manager.clear_heading()
            else:
                self._overlay_manager.clear_heading()
    
    @Slot(str)
    def _on_ocr_state_changed(self, state: str):
        self._app_state.ocr_running = (state != "STOPPED")
        self._app_state.append_system_log(f"OCR状态变化: {state}", "INFO")

    @Slot(str)
    def _on_ocr_running_changed(self, state: str):
        self._settings_interface.set_ocr_running(state != "STOPPED")

    @Slot(bool)
    def _on_gpu_acceleration_changed(self, enabled: bool):
        if not self._ocr_manager:
            return
        self._ocr_manager.set_gpu_acceleration_enabled(enabled)
        self._settings_interface.set_gpu_configuration(self._ocr_manager.ocr_config)

    @Slot(dict)
    def _on_gpu_adapter_changed(self, selection: dict):
        if not self._ocr_manager:
            return
        self._ocr_manager.set_gpu_adapter(selection)
        self._settings_interface.set_gpu_configuration(self._ocr_manager.ocr_config)

    @Slot(dict)
    def _on_gpu_acceleration_failed(self, _details: dict):
        self._settings_interface.mark_gpu_unavailable()
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(tr("app_title"))
        dialog.setText(tr("gpu_acceleration_unavailable_title"))
        dialog.setInformativeText(tr("gpu_acceleration_unavailable_message"))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.setDefaultButton(QMessageBox.StandardButton.Ok)
        dialog.exec()
    
    @Slot(str)
    def _on_ocr_error(self, error: str):
        self._app_state.log(f"OCR Error: {error}")

    @Slot(str)
    def _on_ocr_region_source_changed(self, source: str):
        if self._app_state:
            self._app_state.ocr_area_source = source

        try:
            area = getattr(self._ocr_manager, "ocr_config", {}).get("ocr_capture_area") or {}
            if isinstance(area, dict) and self._app_state:
                x = int(area.get("x", 0) or 0)
                y = int(area.get("y", 0) or 0)
                w = int(area.get("width", 0) or 0)
                h = int(area.get("height", 0) or 0)
                self._app_state.set_ocr_region(x, y, w, h)
        except Exception:
            pass

    def _show_ocr_preview(self):
        """Show OCR preview overlay on hover enter."""
        if not self._ocr_manager:
            return

        areas = []
        area = None
        worker = getattr(self._ocr_manager, 'ocr_worker', None)
        if worker is not None and getattr(worker, 'is_running', False):
            runtime_area = getattr(self._ocr_manager, 'runtime_capture_area', None)
            if isinstance(runtime_area, dict):
                area = runtime_area

        if area is None:
            area = self._ocr_manager.ocr_config.get('ocr_capture_area')
        
        if area and isinstance(area, dict):
            if all(k in area for k in ('x', 'y', 'width', 'height')):
                if area['width'] > 0 and area['height'] > 0:
                    areas.append(area)

        minimap_area = self._build_minimap_preview_area()
        if minimap_area is not None:
            areas.append(minimap_area)

        if areas:
            self._ocr_preview_overlay.show_preview(areas)

    def _build_minimap_preview_area(self):
        try:
            if not self._ocr_manager:
                return None
            get_area = getattr(self._ocr_manager, "get_minimap_preview_area", None)
            if callable(get_area):
                return get_area()
            return None
        except Exception:
            return None
    
    def _hide_ocr_preview(self):
        """Hide OCR preview overlay on hover leave."""
        if self._ocr_preview_overlay:
            self._ocr_preview_overlay.hide_preview()

    def _sync_ocr_area_source_from_config(self):
        if not self._ocr_manager or not self._app_state:
            return
        try:
            source = self._ocr_manager.get_ocr_area_source()
            self._app_state.ocr_area_source = source
        except Exception:
            pass

        try:
            area = getattr(self._ocr_manager, "ocr_config", {}).get("ocr_capture_area") or {}
            if isinstance(area, dict):
                x = int(area.get("x", 0) or 0)
                y = int(area.get("y", 0) or 0)
                w = int(area.get("width", 0) or 0)
                h = int(area.get("height", 0) or 0)
                self._app_state.set_ocr_region(x, y, w, h)
        except Exception:
            pass
    
    def _ocr_auto_jump(self, x: int, y: int, z: int):
        # Auto-jump logic - could be moved to settings or separate logic
        # For now keep it simple or remove if not used in new interface
        self._jump_to_coordinates(x, y)
    
    def _open_calibration(self):
        try:
            from .dialogs.calibration_window import CalibrationWindow
            dialog = CalibrationWindow(
                self,
                self._app_state.current_map_provider,
                self._app_state.current_url
            )
            dialog.calibrationFinished.connect(self._on_calibration_finished)
            dialog.exec()
        except ImportError:
            print("CalibrationWindow not available")
    
    @Slot(object)
    def _on_calibration_finished(self, matrix):
        self._app_state.transform_matrix = matrix
        self._app_state.save_calibration_for_current_map()
        self._inject_kmp_runtime()
        self._app_state.append_system_log("地图校准完成！现在可以使用坐标跳转功能", "INFO")
    
    def _jump_to_coordinates(self, x: int, y: int):
        matrix = self._app_state.transform_matrix
        if not matrix:
            self._app_state.load_calibration_for_current_map()
            matrix = self._app_state.transform_matrix
        
        if matrix:
            command = {
                "type": "jumpToGame",
                "x": x,
                "y": y,
                "source": "tracking",
            }
            js = build_map_control_command(command)

            def _on_jump_result(result):
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        result = {"ok": False, "reason": result or "invalid_result"}
                if isinstance(result, dict) and result.get("ok"):
                    self._app_state.append_system_log(
                        f"OCR自动跳转成功: ({x}, {y})",
                        "INFO",
                    )
                    return
                reason = result.get("reason") if isinstance(result, dict) else "unknown"
                if reason == "point_popup_open":
                    self._app_state.append_system_log(
                        "OCR自动跳转已暂停：地图详情弹窗打开中",
                        "INFO",
                    )
                else:
                    detail_parts = []
                    if isinstance(result, dict):
                        for key in ("name", "message", "stack"):
                            value = result.get(key)
                            if value:
                                text = str(value)
                                if key == "stack":
                                    text = text.replace("\n", " | ")[:600]
                                detail_parts.append(f"{key}={text}")
                    detail = f" ({'; '.join(detail_parts)})" if detail_parts else ""
                    self._app_state.append_system_log(
                        f"OCR自动跳转失败: {reason}{detail}",
                        "ERROR",
                    )

            self._web_view.page().runJavaScript(js, _on_jump_result)
        else:
            self._app_state.append_system_log("OCR自动跳转失败: 当前地图无校准数据", "ERROR")
    
    def _toggle_recording(self):
        if not self._route_recorder:
            return
        
        if self._app_state.recording_active:
            self._stop_recording()
        else:
            self._start_recording()
    
    @Slot(str)
    def _on_recording_started(self, route_name: str):
        self._app_state.recording_active = True
        self._app_state.append_system_log(f"路线录制已启动: {route_name}", "INFO")
        if self._navigation_interface:
            self._navigation_interface.update_route_status(True, 0)

    @Slot(str, int)
    def _on_recording_stopped(self, route_name: str, point_count: int):
        self._app_state.recording_active = False
        self._app_state.append_system_log(
            f"路线录制已停止: {route_name}（共 {point_count} 点）",
            "INFO"
        )
        if self._navigation_interface:
            self._navigation_interface.update_route_status(False, point_count)
        if self._route_settings_interface:
            self._route_settings_interface.load_routes()

    @Slot(int, int, int, int)
    def _on_point_recorded(self, x: int, y: int, z: int, count: int):
        # Only log every 10 points to avoid spam
        if count % 10 == 0:
            self._app_state.append_system_log(
                f"已录制 {count} 个坐标点（最新: {x},{y},{z}）",
                "INFO"
            )
        if self._navigation_interface:
            self._navigation_interface.update_route_status(True, count)

    @Slot(str)
    def _on_recording_error(self, message: str):
        self._app_state.append_system_log(f"路线录制错误: {message}", "ERROR")
    
    def _view_route_detail(self, filepath: str):
        """查看路线详情"""
        try:
            from route_list_dialog import RouteDetailDialog
            if self._route_recorder:
                route_data = self._route_recorder.load_route(filepath)
                if route_data:
                    dialog = RouteDetailDialog(route_data, self)
                    dialog.exec()
        except Exception as e:
            print(f"查看路线详情失败: {e}")

    def _export_route(self, filepath: str):
        """导出路线"""
        try:
            from PySide6.QtWidgets import QFileDialog, QMessageBox
            import shutil

            # 打开文件保存对话框
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出路线",
                str(
                    resolve_route_export_directory(self._settings)
                    / f"route_export_{os.path.basename(filepath)}"
                ),
                "JSON Files (*.json)"
            )

            if save_path:
                shutil.copy(filepath, save_path)
                QMessageBox.information(self, "导出成功", f"路线已导出到: {save_path}")
        except Exception as e:
            print(f"导出路线失败: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "导出失败", f"导出路线失败: {e}")

    def _delete_route(self, filepath: str):
        """删除路线"""
        try:
            from PySide6.QtWidgets import QMessageBox
            import os

            # 确认删除
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要删除路线吗？\n{filepath}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                os.remove(filepath)
                # 刷新列表
                self._route_settings_interface.load_routes()
                QMessageBox.information(self, "删除成功", "路线已删除")
        except Exception as e:
            print(f"删除路线失败: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "删除失败", f"删除路线失败: {e}")

    @Slot(dict)
    def _apply_hotkeys(self, hotkeys: dict):
        """应用快捷键配置"""
        if self._hotkey_manager:
            normalized_hotkeys = DEFAULT_HOTKEYS.copy()
            normalized_hotkeys.update({
                action: (key or "")
                for action, key in hotkeys.items()
                if action in DEFAULT_HOTKEYS
            })

            self._hotkey_manager.unregister_all()
            for action, key in normalized_hotkeys.items():
                if key:
                    # 转换为 keyboard 库格式（小写）
                    keyboard_key = self._hotkey_interface._to_keyboard_format(key)
                    # register_hotkey 方法会自动识别键盘或鼠标快捷键
                    self._hotkey_manager.register_hotkey(action, keyboard_key)

            # 持久化快捷键配置
            self._settings.set("global_hotkeys.hotkeys", normalized_hotkeys, save=True)

    @Slot(str)
    def _on_hotkey_triggered(self, action: str):
        if action == "toggle_ocr":
            self._toggle_ocr()
        elif action == "toggle_recording":
            self._toggle_recording()
        elif action == "mark_next":
            self._trigger_map_action_button('#btn-mark-smart', '标记下一点')
        elif action == "undo":
            self._trigger_map_action_button('#btn-undo-smart', '取消最近点标记')
        elif action == "open_nearest":
            self._trigger_map_action_button('#btn-open-nearest', '打开最近未完成')
        elif action == "close_popup":
            self._trigger_map_action_button('#btn-close-popup', '关闭弹窗')
        elif action == "zoom_in":
            self._trigger_map_zoom(1, "地图放大一级")
        elif action == "zoom_out":
            self._trigger_map_zoom(-1, "地图缩小一级")
        elif action == "prev_route":
            self._trigger_map_action_button('#sm-prev-route', '上一条路线')
        elif action == "next_route":
            self._trigger_map_action_button('#sm-next-route', '下一条路线')

    def _trigger_map_zoom(self, delta: int, action_name: str):
        """通过快捷键调整地图缩放层级"""
        if not self._web_view or not self._web_view.page():
            self._app_state.append_system_log(f"快捷键{action_name}失败：地图页面未就绪", "ERROR")
            return

        js = build_map_control_command(
            {
                "type": "zoom",
                "delta": 1 if delta > 0 else -1,
                "source": "manual",
            }
        )

        def _on_zoom_result(result):
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = {"ok": False, "reason": result or "invalid_result"}
            if isinstance(result, dict) and result.get("ok"):
                self._app_state.append_system_log(f"快捷键触发成功：{action_name}", "INFO")
            else:
                reason = result.get("reason") if isinstance(result, dict) else "unknown"
                self._app_state.append_system_log(f"快捷键{action_name}失败：{reason}", "ERROR")

        self._web_view.page().runJavaScript(js, _on_zoom_result)

    def _trigger_map_action_button(self, button_selector: str, action_name: str):
        """触发地图页面按钮（供快捷键调用）"""
        if not self._web_view or not self._web_view.page():
            self._app_state.append_system_log(f"快捷键{action_name}失败：地图页面未就绪", "ERROR")
            return

        js = f"""
        (function() {{
            try {{
                const btn = document.querySelector({json.dumps(button_selector)});
                if (!btn) return false;
                if (btn.disabled) return false;

                if (typeof btn.click === 'function') {{
                    btn.click();
                    return true;
                }}

                const evt = new MouseEvent('click', {{ bubbles: true, cancelable: true }});
                btn.dispatchEvent(evt);
                return true;
            }} catch (e) {{
                return false;
            }}
        }})();
        """

        def _on_trigger_result(ok):
            if ok:
                self._app_state.append_system_log(f"快捷键触发成功：{action_name}", "INFO")
            else:
                self._app_state.append_system_log(
                    f"快捷键{action_name}失败：未找到按钮 {button_selector}",
                    "ERROR"
                )

        self._web_view.page().runJavaScript(js, _on_trigger_result)
    
    @Slot(str)
    def _on_language_changed(self, lang_code: str):
        if LANGUAGE_AVAILABLE:
            lm = get_language_manager()
            if lm:
                if lm.set_language(lang_code):
                    self._retranslate_ui()

    def _on_theme_changed(self, theme_mode: str):
        """主题改变时更新所有自定义组件的样式"""
        self._apply_title_bar_button_theme()

        # 更新首页背景样式
        self._home_interface.update_theme()

        # 更新快捷键界面（包括 CardWidget 和输入框）
        self._hotkey_interface.update_theme()

        # 更新路线列表表格
        self._route_settings_interface.update_theme()

        # 更新地图设置列表
        self._map_settings_interface.update_theme()

        # 更新识别设置背景和卡片
        self._ocr_settings_interface.update_theme()

        # 更新日志文本框
        self._log_interface.update_theme()

        # 更新设置界面 CardWidget
        self._settings_interface.update_theme()

        # 更新关于界面 CardWidget
        self._about_interface.update_theme()

    def _on_log_settings_changed(self, max_files: int, max_size_mb: int):
        if self._log_manager:
            self._log_manager.set_limits(max_files, max_size_mb)

    def _apply_title_bar_button_theme(self):
        """更新标题栏按钮颜色（深色模式下为白色）"""
        try:
            from qfluentwidgets import isDarkTheme
            is_dark = isDarkTheme()
        except Exception:
            is_dark = False

        title_bar = getattr(self, "titleBar", None)
        if not title_bar:
            return

        btns = []
        for attr in ("minBtn", "maxBtn", "closeBtn"):
            btn = getattr(title_bar, attr, None)
            if btn:
                btns.append(btn)

        if not btns:
            return

        if is_dark:
            icon_color = QColor("#FFFFFF")
            hover_bg = QColor(255, 255, 255, 26)
            pressed_bg = QColor(255, 255, 255, 51)
            transparent = QColor(0, 0, 0, 0)

            for btn in btns:
                btn.setNormalColor(icon_color)
                btn.setHoverColor(icon_color)
                btn.setPressedColor(icon_color)

                if btn is getattr(title_bar, "closeBtn", None):
                    btn.setNormalBackgroundColor(transparent)
                    btn.setHoverBackgroundColor(QColor(232, 17, 35))
                    btn.setPressedBackgroundColor(QColor(241, 112, 122))
                else:
                    btn.setNormalBackgroundColor(transparent)
                    btn.setHoverBackgroundColor(hover_bg)
                    btn.setPressedBackgroundColor(pressed_bg)
        else:
            icon_color = QColor(0, 0, 0)
            hover_bg = QColor(0, 0, 0, 26)
            pressed_bg = QColor(0, 0, 0, 51)
            transparent = QColor(0, 0, 0, 0)

            for btn in btns:
                if btn is getattr(title_bar, "closeBtn", None):
                    btn.setNormalColor(icon_color)
                    btn.setHoverColor(QColor("#FFFFFF"))
                    btn.setPressedColor(QColor("#FFFFFF"))
                    btn.setNormalBackgroundColor(transparent)
                    btn.setHoverBackgroundColor(QColor(232, 17, 35))
                    btn.setPressedBackgroundColor(QColor(241, 112, 122))
                else:
                    btn.setNormalColor(icon_color)
                    btn.setHoverColor(icon_color)
                    btn.setPressedColor(icon_color)
                    btn.setNormalBackgroundColor(transparent)
                    btn.setHoverBackgroundColor(hover_bg)
                    btn.setPressedBackgroundColor(pressed_bg)

    def _toggle_map_topmost(self, checked: bool):
        """切换地图窗口顶置状态"""
        self._apply_map_window_flags()

    def _toggle_map_passthrough(self, checked: bool):
        """切换地图窗口鼠标穿透状态"""
        self._apply_map_window_flags()

    def _toggle_map_frameless(self, checked: bool):
        """切换地图窗口无边框模式"""
        self._apply_map_window_flags()

    def _toggle_main_topmost(self, checked: bool):
        """切换主界面顶置状态"""
        try:
            if hasattr(self, "setStayOnTop"):
                self.setStayOnTop(checked)
            else:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
                self.show()
            self.raise_()
            self.activateWindow()
            self._apply_native_topmost(checked)
            print("主界面已设置为顶置" if checked else "主界面已取消顶置")
        except Exception as e:
            print(f"设置主界面顶置失败: {e}")

    def _apply_native_topmost(self, enabled: bool):
        """在 Windows 上使用原生 API 强制置顶"""
        if sys.platform != "win32":
            return

        try:
            import ctypes

            hwnd = int(self.winId())
            if hwnd == 0:
                return

            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            SWP_FRAMECHANGED = 0x0020

            if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong):
                get_style = user32.GetWindowLongPtrW
                set_style = user32.SetWindowLongPtrW
            else:
                get_style = user32.GetWindowLongW
                set_style = user32.SetWindowLongW

            style = get_style(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TOPMOST
            else:
                style &= ~WS_EX_TOPMOST
            set_style(hwnd, GWL_EXSTYLE, style)

            insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
            user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
        except Exception as e:
            print(f"原生置顶设置失败: {e}")

    def _apply_map_window_flags(self):
        """统一应用地图窗口标志，避免多选项互相覆盖"""
        if not self._separated_map_window or not self._navigation_interface:
            return

        try:
            geometry = self._separated_map_window.geometry()
            was_visible = self._separated_map_window.isVisible()

            flags = Qt.Window
            if self._navigation_interface.frameless_check.isChecked():
                flags |= Qt.FramelessWindowHint
            if self._navigation_interface.topmost_check.isChecked():
                flags |= Qt.WindowStaysOnTopHint
            if self._navigation_interface.passthrough_check.isChecked():
                flags |= Qt.WindowTransparentForInput

            self._separated_map_window.setWindowFlags(flags)
            self._separated_map_window.setAttribute(
                Qt.WA_TransparentForMouseEvents,
                self._navigation_interface.passthrough_check.isChecked(),
            )
            self._separated_map_window.setGeometry(geometry)

            self._separated_map_window.show()
            if was_visible:
                self._separated_map_window.raise_()
                self._separated_map_window.activateWindow()

            print(
                "地图窗口标志已更新: "
                f"topmost={self._navigation_interface.topmost_check.isChecked()}, "
                f"passthrough={self._navigation_interface.passthrough_check.isChecked()}, "
                f"frameless={self._navigation_interface.frameless_check.isChecked()}"
            )
        except Exception as e:
            print(f"应用地图窗口标志失败: {e}")

    def _on_opacity_changed(self, value: int):
        """改变地图窗口透明度"""
        print(f"[DEBUG] _on_opacity_changed called: value={value}")
        if self._separated_map_window:
            self._separated_map_window.setWindowOpacity(value / 100.0)
            print(f"[DEBUG] Map window opacity set to: {value}%")
    
    def _on_map_window_closed(self):
        self.close()
    
    def closeEvent(self, event):
        if self._is_closing:
            event.accept()
            return

        self._is_closing = True

        try:
            if (
                self._settings_interface
                and not self._settings_interface.shutdown_gpu_discovery()
            ):
                self._is_closing = False
                event.ignore()
                return

            # 停止OCR，避免窗口释放后 OCR worker 继续发信号
            if self._ocr_manager and not self._ocr_manager.stop_ocr():
                self._is_closing = False
                event.ignore()
                return

            # 停止路线录制
            if self._route_recorder and self._app_state.recording_active:
                self._route_recorder.stop_recording()

            # 清理快捷键管理器（重要：停止鼠标监听线程）
            if self._hotkey_manager:
                if hasattr(self._hotkey_manager, 'cleanup'):
                    print("正在清理快捷键管理器...")
                    self._hotkey_manager.cleanup()
                else:
                    self._hotkey_manager.unregister_all()

            if self._minimap_tile_sync_service:
                self._minimap_tile_sync_service.shutdown(timeout=1.0)

            if self._minimap_tile_index_queue:
                self._minimap_tile_index_queue.shutdown()

            if self._python_download_executor:
                self._python_download_executor.shutdown(wait=False, cancel_futures=True)

            if self._update_check_executor:
                self._update_check_executor.shutdown(wait=False, cancel_futures=True)

            if self._backend and hasattr(self._backend, "shutdown"):
                self._backend.shutdown()

            if self._log_manager:
                self._log_manager.stop()

            # 停止本地服务器
            if self._server_manager:
                self._server_manager.stop_servers()

            # 隐藏OCR预览覆盖层
            if self._ocr_preview_overlay:
                self._ocr_preview_overlay.hide_preview()

            if self._overlay_manager:
                self._overlay_manager.cleanup()
                self._overlay_manager = None

            if self._auto_calibration_polling_timer.isActive():
                self._auto_calibration_polling_timer.stop()

            # 关闭地图窗口
            if self._separated_map_window:
                self._save_map_window_geometry()
                self._separated_map_window._is_closing = True
                self._separated_map_window.close()

            print("主窗口清理完成")

        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            import traceback
            traceback.print_exc()

        super().closeEvent(event)
    
    @property
    def app_state(self) -> AppState:
        return self._app_state
    
    @property
    def web_view(self) -> QWebEngineView:
        return self._web_view
