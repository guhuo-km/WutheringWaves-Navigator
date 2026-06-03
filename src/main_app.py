#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wuthering Waves Navigator - Main Entry Point
"""

import sys
import os
import multiprocessing
import io
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)
os.chdir(script_dir)
sys.path.insert(0, script_dir)

# Prepend vendored PySide6-compatible qfluentwidgets to avoid mixing with PyQt5 version
vendored_fluent = os.path.join(repo_root, "PyQt-Fluent-Widgets-PySide6")
if os.path.isdir(vendored_fluent):
    sys.path.insert(0, vendored_fluent)


def _ensure_stdio_streams() -> None:
    """Ensure stdio streams exist in frozen/windowed environments.

    In PyInstaller windowed mode, ``sys.stdout`` / ``sys.stderr`` may be None,
    while some third-party libraries (e.g., ultralytics) access
    ``sys.stdout.encoding`` at import time.
    """

    def _fallback_stream() -> io.TextIOBase:
        return open(os.devnull, "w", encoding="utf-8", buffering=1)

    if sys.stdout is None:
        sys.stdout = _fallback_stream()
    if sys.stderr is None:
        sys.stderr = _fallback_stream()


def main():
    multiprocessing.freeze_support()
    _ensure_stdio_streams()
    try:
        from core.crash_diagnostics import install_crash_diagnostics
        crash_log_path = install_crash_diagnostics()
        if crash_log_path:
            print(f"[CRASH_DIAG] enabled: {crash_log_path}")
    except Exception as e:
        print(f"[CRASH_DIAG] unavailable: {e}")
    
    # 1. 管理员权限检测 (使用 Windows 原生弹窗，无需 Qt)
    from core.utils import is_admin, show_admin_required_message
    if not is_admin():
        show_admin_required_message()
        sys.exit(1)
        
    # 2. 正式启动
    from PySide6.QtCore import Qt, QDir, QLockFile
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from PySide6.QtGui import QIcon
    from qfluentwidgets import setTheme, Theme
    from core.utils import get_assets_path
    
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)

    # 单实例保护：避免重复启动导致本地地图端口冲突
    lock_dir = os.path.join(tempfile.gettempdir(), "wuthering_waves_navigator")
    QDir().mkpath(lock_dir)
    lock_file_path = os.path.join(lock_dir, "single_instance.lock")

    single_instance_lock = QLockFile(lock_file_path)
    if not single_instance_lock.tryLock(0):
        QMessageBox.warning(None, "程序已在运行", "检测到程序已启动，请勿重复打开。")
        sys.exit(0)

    try:
        from core.update_lock import is_update_in_progress, update_in_progress_message

        app_root = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else repo_root
        if is_update_in_progress(app_root):
            QMessageBox.information(None, "更新正在进行", update_in_progress_message())
            sys.exit(0)
        if getattr(sys, "frozen", False):
            from core.startup_maintenance import run_startup_maintenance

            result = run_startup_maintenance(app_root)
            removed = result.get("removed") or []
            if removed:
                print(f"[STARTUP_MAINTENANCE] removed obsolete files: {len(removed)}")
            if result.get("updater_refreshed"):
                print("[STARTUP_MAINTENANCE] updater refreshed")
    except Exception as e:
        print(f"[UPDATE_GUARD] unavailable: {e}")

    def _release_single_instance_lock():
        if single_instance_lock.isLocked():
            single_instance_lock.unlock()

    app.aboutToQuit.connect(_release_single_instance_lock)

    # 应用图标（窗口/任务栏）
    app_icon_path = get_assets_path("ico.ico")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))

    setTheme(Theme.AUTO)
    
    # 3. 免责声明检测
    from ui.dialogs.disclaimer_dialog import DisclaimerDialog
    from core.settings_manager import SettingsManager
    settings = SettingsManager()
    if not settings.get("disclaimer_accepted", False):
        dialog = DisclaimerDialog()
        if dialog.exec() != QDialog.Accepted:
            sys.exit(0)
        settings.set("disclaimer_accepted", True)
    
    # 4. 主窗口
    from ui.main_window import MainWindow
    
    main_window = MainWindow()
    if os.path.exists(app_icon_path):
        main_window.setWindowIcon(QIcon(app_icon_path))
    main_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
