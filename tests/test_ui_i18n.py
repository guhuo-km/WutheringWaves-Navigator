import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = PROJECT_ROOT / "src" / "ui" / "main_window.py"
INTERFACES = PROJECT_ROOT / "src" / "ui" / "interfaces"
LANGUAGES = PROJECT_ROOT / "languages"


RETRANSLATABLE_INTERFACES = [
    "home_interface.py",
    "navigation_interface.py",
    "ocr_settings_interface.py",
    "map_settings_interface.py",
    "route_settings_interface.py",
    "settings_interface.py",
    "hotkey_interface.py",
    "log_interface.py",
    "about_interface.py",
]


REQUIRED_LANGUAGE_KEYS = [
    "nav_home",
    "nav_navigation",
    "nav_ocr_settings",
    "nav_map_settings",
    "nav_route_recording",
    "nav_hotkeys",
    "nav_logs",
    "nav_settings",
    "nav_about",
    "settings_appearance",
    "settings_theme_mode",
    "settings_theme_light",
    "settings_theme_dark",
    "settings_theme_auto",
    "settings_language",
    "settings_interface_language",
    "settings_window",
    "settings_remember_map_window_geometry",
    "settings_logs",
    "settings_log_retention_count",
    "settings_log_max_file_size_mb",
    "hotkey_config_title",
    "hotkey_config_desc",
    "hotkey_settings_title",
    "hotkey_action_toggle_ocr",
    "hotkey_action_toggle_recording",
    "hotkey_action_mark_next",
    "hotkey_action_undo",
    "hotkey_action_open_nearest",
    "hotkey_action_close_popup",
    "hotkey_action_zoom_in",
    "hotkey_action_zoom_out",
    "hotkey_action_prev_route",
    "hotkey_action_next_route",
    "hotkey_clear",
    "hotkey_reset_default",
    "hotkey_apply_settings",
    "hotkey_reset_success_title",
    "hotkey_reset_success_message",
    "hotkey_apply_error_title",
    "hotkey_duplicate_error_message",
    "hotkey_apply_success_title",
    "hotkey_apply_success_message",
    "log_auto_refresh",
    "log_refresh_interval_1s",
    "log_detailed_ocr",
    "log_manual_refresh",
    "log_missing_file",
    "log_save_dialog_title",
    "home_banner_title",
    "home_banner_subtitle",
    "home_launch_title",
    "home_game_path_placeholder",
    "home_pick_game_path",
    "home_launch_game",
    "home_launch_status_no_path",
    "home_launch_status_path_selected",
    "home_launch_status_invalid_path",
    "home_launch_status_launched",
    "home_launch_status_failed",
    "nav_ocr_card_title",
    "nav_start_ocr",
    "nav_stop_ocr",
    "nav_calibrate_ocr_region",
    "nav_status_not_started",
    "nav_status_running",
    "nav_coordinates_empty",
    "nav_coordinates_value",
    "nav_ocr_region_empty",
    "nav_ocr_region_value",
    "nav_ocr_region_source",
    "nav_map_control_title",
    "nav_map_source",
    "nav_map_source_official",
    "nav_map_source_local",
    "nav_map_calibration",
    "nav_map_recapture",
    "nav_map_waiting",
    "nav_map_status_value",
    "nav_area_id",
    "nav_calibration_status",
    "nav_dot_size",
    "nav_route_recording_title",
    "nav_start_recording",
    "nav_stop_recording",
    "nav_route_status_not_recording",
    "nav_route_status_recording",
    "nav_route_count",
    "nav_window_control_title",
    "nav_map_window",
    "nav_window_topmost",
    "nav_window_passthrough",
    "nav_window_frameless",
    "nav_window_opacity",
    "nav_main_window",
    "nav_main_window_topmost",
    "ocr_basic_settings",
    "ocr_capture_mode",
    "ocr_capture_mode_bitblt",
    "ocr_capture_mode_printwindow",
    "ocr_capture_mode_tooltip",
    "ocr_capture_mode_tooltip",
    "ocr_target_window",
    "ocr_target_window_placeholder",
    "ocr_select_window",
    "ocr_interval_ms",
    "ocr_digit_confidence",
    "ocr_symbol_confidence",
    "ocr_auto_calibration",
    "ocr_switch_on",
    "ocr_switch_off",
    "ocr_auto_detect_hint",
    "ocr_region_status_title",
    "ocr_preview_region",
    "ocr_preview_region_tooltip",
    "ocr_auto_searching",
    "ocr_unknown",
    "ocr_window_unknown",
    "ocr_mode_empty",
    "ocr_resolution_empty",
    "ocr_position_empty",
    "ocr_detect_failed",
    "ocr_detect_manual_skip",
    "ocr_detect_found",
    "ocr_region_status_empty",
    "ocr_window_value",
    "ocr_mode_value",
    "ocr_resolution_value",
    "ocr_position_value",
    "ocr_mode_fullscreen",
    "ocr_mode_borderless",
    "ocr_mode_windowed",
    "ocr_select_success_title",
    "ocr_select_success_message",
    "ocr_select_error_title",
    "ocr_select_error_message",
    "map_source_title",
    "map_source_official_full",
    "map_source_local",
    "map_local_management",
    "map_add",
    "map_delete",
    "map_refresh_list",
    "map_calibration_title",
    "map_calibration_desc",
    "map_open_calibration_window",
    "map_auto_calibration_on",
    "map_auto_calibration_off",
    "map_auto_calibration_available_hint",
    "map_auto_calibration_unavailable_hint",
    "map_calibration_status",
    "map_select_images_title",
    "map_image_filter",
    "map_generation_success_title",
    "map_generation_failed_title",
    "map_no_selection_title",
    "map_no_selection_message",
    "map_confirm_delete_title",
    "map_confirm_delete_message",
    "map_delete_success_title",
    "map_delete_success_message",
    "map_delete_failed_title",
    "map_delete_failed_message",
    "map_delete_error_title",
    "map_delete_error_message",
    "route_record_settings",
    "route_record_desc",
    "route_record_tip",
    "route_export_directory",
    "route_export_directory_choose",
    "route_export_directory_reset",
    "route_export_directory_dialog_title",
    "route_list_title",
    "route_table_name",
    "route_table_created_time",
    "route_table_duration",
    "route_table_point_count",
    "route_table_file_size",
    "route_table_file_path",
    "route_refresh_list",
    "route_view_detail",
    "route_export",
    "route_delete",
    "route_open_folder",
    "route_loading",
    "route_recorder_not_initialized",
    "route_files_found",
    "route_load_failed",
    "about_title",
    "about_description",
    "about_github_homepage",
    "about_bilibili_homepage",
    "about_update",
    "about_version",
    "about_update_status_not_checked",
    "about_update_status_checking",
    "about_update_status_latest",
    "about_update_status_available",
    "about_update_status_full_required",
    "about_update_status_failed",
    "about_update_mode_empty",
    "about_update_mode_size",
    "about_update_manual_mode",
    "about_update_checked_empty",
    "about_update_checked",
    "about_update_release_notes",
    "about_update_reason",
    "about_check_update",
    "about_start_update",
    "about_open_download",
    "about_credits_title",
    "about_credit_fluent",
    "about_credit_ocr",
    "about_credit_maps",
]


def test_main_window_refreshes_navigation_and_interfaces_on_language_change():
    text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "def _retranslate_ui(self)" in text
    assert "def _set_navigation_item_text" in text
    assert "self._retranslate_ui()" in text
    assert 'tr("nav_home"' in text
    assert 'tr("nav_hotkeys"' in text


def test_core_interfaces_expose_retranslate_ui():
    for filename in RETRANSLATABLE_INTERFACES:
        text = (INTERFACES / filename).read_text(encoding="utf-8")
        assert "def retranslate_ui(self)" in text, filename
        assert "tr(" in text, filename


def test_settings_interface_uses_language_manager_api_for_supported_languages():
    text = (INTERFACES / "settings_interface.py").read_text(encoding="utf-8")

    assert "SUPPORTED_LANGUAGES" not in text
    assert "get_supported_languages()" in text


def test_minimap_visual_controls_move_from_map_settings_to_ocr_settings():
    text = (INTERFACES / "map_settings_interface.py").read_text(encoding="utf-8")
    ocr_text = (INTERFACES / "ocr_settings_interface.py").read_text(encoding="utf-8")

    removed_from_map_names = [
        "minimap_visual_title_label",
        "minimap_roi_x_spin",
        "minimap_roi_y_spin",
        "minimap_roi_w_spin",
        "minimap_roi_h_spin",
        "minimap_shape_circle_radio",
        "minimap_shape_ellipse_radio",
        "minimap_manual_calibrate_btn",
        "minimap_auto_recalibrate_btn",
    ]
    for name in removed_from_map_names:
        assert name not in text

    expected_ocr_names = [
        "minimap_auto_calibration_label",
        "minimap_auto_calibration_switch",
        "minimap_manual_calibrate_btn",
        "coordinate_agreement_x_threshold_spin",
        "coordinate_agreement_y_threshold_spin",
        "history_x_threshold_spin",
        "history_y_threshold_spin",
        "auto_roi_lock_tolerance_spin",
        "rough_candidate_limit_spin",
        "heading_recognition_enabled_switch",
    ]
    for name in expected_ocr_names:
        assert name in ocr_text

    removed_ocr_names = [
        "minimap_detect_interval_spin",
        "heading_recognition_interval_spin",
    ]
    for name in removed_ocr_names:
        assert name not in ocr_text

    expected_settings = [
        "minimap_roi.auto_calibration_enabled",
        "minimap_stability.coordinate_agreement_x_threshold",
        "minimap_stability.coordinate_agreement_y_threshold",
        "minimap_stability.history_x_threshold",
        "minimap_stability.history_y_threshold",
        "minimap_stability.auto_roi_lock_tolerance_px",
        "minimap_stability.rough_candidate_limit",
        "minimap_stability.heading_recognition_enabled",
    ]
    for key in expected_settings:
        assert key in ocr_text

    removed_settings = [
        "minimap_roi.detect_interval_ms",
        "minimap_stability.heading_recognition_interval_ms",
    ]
    for key in removed_settings:
        assert key not in ocr_text

    assert "preview_button" in ocr_text
    assert ocr_text.count("preview_button") >= 1


def test_ocr_settings_interface_updates_dark_theme_backgrounds():
    ocr_text = (INTERFACES / "ocr_settings_interface.py").read_text(encoding="utf-8")
    main_window_text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "def update_theme(self):" in ocr_text
    assert "ThemeManager.get_page_background_style()" in ocr_text
    assert "ThemeManager.get_card_widget_style()" in ocr_text
    assert "self.basic_card" in ocr_text
    assert "self.status_divider" in ocr_text
    assert "self.params_divider" in ocr_text
    assert "findChildren(QFrame)" not in ocr_text
    assert "self._ocr_settings_interface.update_theme()" in main_window_text


def test_aura_helper_is_removed_from_map_source_ui():
    nav_text = (PROJECT_ROOT / "src" / "ui" / "interfaces" / "navigation_interface.py").read_text(encoding="utf-8")
    settings_text = (PROJECT_ROOT / "src" / "ui" / "interfaces" / "map_settings_interface.py").read_text(encoding="utf-8")
    constants_text = (PROJECT_ROOT / "src" / "core" / "constants.py").read_text(encoding="utf-8")
    calibration_text = (PROJECT_ROOT / "src" / "ui" / "dialogs" / "calibration_window.py").read_text(encoding="utf-8")
    zh_text = (PROJECT_ROOT / "languages" / "zh_CN.json").read_text(encoding="utf-8")
    en_text = (PROJECT_ROOT / "languages" / "en_US.json").read_text(encoding="utf-8")

    for text in (nav_text, settings_text, constants_text, calibration_text):
        assert "aura" not in text
        assert "aura_helper" not in text
        assert "ghzs" not in text

    assert "光环助手" not in zh_text
    assert "Aura" not in en_text


def test_calibration_window_uses_current_local_map_server_port():
    text = (PROJECT_ROOT / "src" / "ui" / "dialogs" / "calibration_window.py").read_text(encoding="utf-8")

    assert "http://localhost:58427/index.html" in text
    assert "http://localhost:8000/index.html" not in text


def test_minimap_calibration_buttons_are_connected_to_main_window():
    map_settings_text = (INTERFACES / "map_settings_interface.py").read_text(encoding="utf-8")
    ocr_settings_text = (INTERFACES / "ocr_settings_interface.py").read_text(encoding="utf-8")
    main_window_text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "minimap_manual_calibration_requested" not in map_settings_text
    assert "minimap_auto_calibration_toggled" not in map_settings_text

    assert "minimap_manual_calibration_requested" in ocr_settings_text
    assert "minimap_auto_calibration_toggled" in ocr_settings_text

    assert "_ocr_settings_interface.minimap_manual_calibration_requested.connect(self._setup_minimap_region)" in main_window_text
    assert "_ocr_settings_interface.minimap_auto_calibration_toggled.connect(self._on_minimap_auto_calibration_toggled)" in main_window_text
    assert "minimap_roi_locked.connect(self._on_minimap_roi_locked)" in main_window_text
    assert "def _on_minimap_roi_locked(self, payload):" in main_window_text
    assert 'self._settings.set("minimap_roi.status", "locked"' in main_window_text
    assert 'start_minimap_auto_search' in main_window_text
    assert 'stop_minimap_auto_search' in main_window_text


def test_new_ui_i18n_keys_exist_in_both_language_files():
    zh = json.loads((LANGUAGES / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((LANGUAGES / "en_US.json").read_text(encoding="utf-8"))

    missing_zh = [key for key in REQUIRED_LANGUAGE_KEYS if key not in zh]
    missing_en = [key for key in REQUIRED_LANGUAGE_KEYS if key not in en]

    assert missing_zh == []
    assert missing_en == []


def test_log_ui_uses_recognition_log_wording():
    zh = json.loads((LANGUAGES / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((LANGUAGES / "en_US.json").read_text(encoding="utf-8"))
    log_interface_text = (INTERFACES / "log_interface.py").read_text(encoding="utf-8")
    main_window_text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert zh["log_ocr"] == "识别日志"
    assert zh["log_detailed_ocr"] == "详细识别日志:"
    assert en["log_ocr"] == "Recognition Log"
    assert en["log_detailed_ocr"] == "Detailed recognition log:"
    assert "OCR 日志" not in log_interface_text
    assert "详细OCR日志" not in log_interface_text
    assert "详细OCR日志" not in main_window_text


def test_all_interface_tr_keys_exist_in_both_language_files():
    zh = json.loads((LANGUAGES / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((LANGUAGES / "en_US.json").read_text(encoding="utf-8"))

    keys = set()
    for path in INTERFACES.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys.update(re.findall(r'tr\("([^"]+)"', text))

    missing_zh = sorted(key for key in keys if key not in zh)
    missing_en = sorted(key for key in keys if key not in en)

    assert missing_zh == []
    assert missing_en == []
