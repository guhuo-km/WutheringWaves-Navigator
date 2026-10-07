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
import subprocess
from pathlib import Path

# 必须在 faiss / onnxruntime / cv2 等原生库 import 之前设置：OpenMP 运行时只在初始化时读一次 OMP_WAIT_POLICY。
# faiss 的 OpenMP 工作线程默认在每次调用后自旋等待；本程序每 500 ms 才调用一次，实测每帧整进程 CPU 从 891 ms 降到 234 ms（单帧实际耗时 86.5 ms 降到 65.1 ms），建库只慢 8.4%。
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

# 同样必须在 faiss / numpy 等原生库 import 之前设置：OpenBLAS 只在初始化时读一次线程数。
# faiss 的 wheel 自带一份 OpenBLAS（faiss_cpu.libs\\libopenblas.dll），numpy 2.4.2 也自带一份
# （libscipy_openblas64_*.dll）。两份在加载时都按工作线程数预留固定大小的匿名暂存池：
# faiss 那份每线程 128 MiB，numpy 那份每线程 32 MiB；均不写入数据、进程结束前不释放。
# 实测 OPENBLAS_NUM_THREADS 为 1/2/4/8/16 时块数为 0/1/3/7/15（块数 = 线程数 - 1），
# 默认不设时本机 16 逻辑核会预留 15*128 MiB + 15*32 MiB 约 2.3 GiB 已提交但基本不用的匿名内存，
# 且这些零页一旦被访问就会进入工作集，直接推高任务管理器的"内存"列。
# 本程序每帧真正走 BLAS 的运算只有 rough_matrix @ query（约 2.83 MFLOP），亚毫秒级，单线程足够；
# faiss 的二进制指纹搜索是 popcount 位运算、不走 BLAS，其并行度由 OMP_NUM_THREADS 管，不受此设置影响。
# 用户在环境变量中已显式指定时用 setdefault 尊重该值。
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

sys.dont_write_bytecode = True

BOOTSTRAP_SRC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOOTSTRAP_SRC_ROOT))

from core import paths

# Prepend vendored PySide6-compatible qfluentwidgets to avoid mixing with PyQt5 version
vendored_fluent = paths.project_root() / "PyQt-Fluent-Widgets-PySide6"
if vendored_fluent.is_dir():
    sys.path.insert(0, str(vendored_fluent))


DEBUG_RECOGNITION_ARG = "--debug-recognition"


def configure_debug_recognition_from_argv(argv: list[str] | None = None) -> list[str]:
    """Enable developer-only recognition diagnostics from a startup flag."""
    args = list(sys.argv if argv is None else argv)
    if DEBUG_RECOGNITION_ARG not in args:
        return args

    filtered = [arg for arg in args if arg != DEBUG_RECOGNITION_ARG]
    settings_cls = globals().get("SettingsManager")
    if settings_cls is None:
        from core.settings_manager import SettingsManager as settings_cls
    settings = settings_cls()
    settings.set("logging.detailed_ocr_enabled", True, save=False)
    settings.set("logging.save_minimap_frame_packages", True, save=False)
    settings.set("diagnostics.resource_probe_enabled", True, save=False)
    settings.save()
    print("[DEBUG_RECOGNITION] enabled")
    return filtered


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


def main() -> int:
    multiprocessing.freeze_support()
    _ensure_stdio_streams()
    sys.argv = configure_debug_recognition_from_argv(sys.argv)
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
    from language_manager import tr
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

    app_root = paths.app_root()
    try:
        from core.update_lock import (
            is_update_in_progress,
            update_in_progress_message,
            update_lock,
        )

        if is_update_in_progress(app_root):
            QMessageBox.information(None, "更新正在进行", update_in_progress_message())
            sys.exit(0)
        if getattr(sys, "frozen", False):
            from core.file_updater import recover_interrupted_updates

            with update_lock(app_root):
                recovered = recover_interrupted_updates(app_root)
            if recovered:
                print(f"[UPDATE_RECOVERY] restored interrupted updates: {len(recovered)}")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[UPDATE_GUARD] recovery failed: {e}")
        QMessageBox.information(None, "更新正在进行", update_in_progress_message())
        sys.exit(1)

    if getattr(sys, "frozen", False):
        try:
            from core.startup_maintenance import run_startup_maintenance

            result = run_startup_maintenance(app_root)
            removed = result.get("removed") or []
            if removed:
                print(f"[STARTUP_MAINTENANCE] removed obsolete files: {len(removed)}")
        except Exception as e:
            print(f"[STARTUP_MAINTENANCE] unavailable: {e}")

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
    settings.migrate_minimap_rough_candidate_limit()
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
    
    exit_code = app.exec()
    pending_update_command = main_window.take_pending_update_command()
    if pending_update_command:
        try:
            subprocess.Popen(pending_update_command)
        except Exception as exc:
            from updater_app import append_update_failure_log

            append_update_failure_log(app_root, "launch", exc)
            QMessageBox.critical(
                None,
                tr("update_apply_unavailable_title", "无法应用更新"),
                tr(
                    "update_updater_launch_failed",
                    "启动更新器失败: {error}",
                    error=exc,
                ),
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
