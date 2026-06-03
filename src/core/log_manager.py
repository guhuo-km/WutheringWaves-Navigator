# -*- coding: utf-8 -*-
"""
Asynchronous log writer with per-session log files and retention cleanup.
"""

from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

from .settings_manager import SettingsManager


class LogManager:
    """Async log writer and session-based log file manager."""

    _LOG_TYPES = ("system", "ocr", "debug")

    def __init__(
        self,
        log_dir: Optional[str] = None,
        settings: Optional[SettingsManager] = None,
        session_ts: Optional[str] = None,
    ):
        self._settings = settings or SettingsManager()
        self._session_ts = session_ts or datetime.now().strftime("%Y%m%d_%H%M%S")

        if log_dir is None:
            core_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(core_dir)
            repo_root = os.path.dirname(src_dir)
            log_dir = os.path.join(repo_root, "logs")

        self._base_log_dir = log_dir
        self._log_dir = self._session_log_dir(log_dir, self._session_ts)
        os.makedirs(self._log_dir, exist_ok=True)

        self._max_files = int(self._settings.get("logging.max_files", 20))
        self._max_file_size_mb = int(self._settings.get("logging.max_file_size_mb", 500))
        self._clamp_limits()

        self._paths: Dict[str, str] = {}
        for log_type in self._LOG_TYPES:
            filename = f"{log_type}.log"
            self._paths[log_type] = os.path.join(self._log_dir, filename)

        self._queue: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

        self._ensure_files()
        self._cleanup_logs()

    def get_log_path(self, log_type: str) -> Optional[str]:
        return self._paths.get(log_type)

    def set_limits(self, max_files: int, max_file_size_mb: int) -> None:
        self._max_files = int(max_files)
        self._max_file_size_mb = int(max_file_size_mb)
        self._clamp_limits()
        self._cleanup_logs()

    def enqueue(self, log_type: str, line: str) -> None:
        if log_type not in self._LOG_TYPES:
            return
        if not line:
            return
        self._queue.put((log_type, line))

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._thread.join(timeout=2.0)
        except Exception:
            pass

    def _clamp_limits(self) -> None:
        if self._max_files < 1:
            self._max_files = 1
        if self._max_file_size_mb < 1:
            self._max_file_size_mb = 1

    def _ensure_files(self) -> None:
        for path in self._paths.values():
            try:
                with open(path, "a", encoding="utf-8"):
                    pass
            except Exception:
                pass

    def _writer_loop(self) -> None:
        file_handles: Dict[str, Optional[object]] = {t: None for t in self._LOG_TYPES}
        write_count = 0

        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                log_type, line = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if file_handles.get(log_type) is None:
                    file_handles[log_type] = open(
                        self._paths[log_type], "a", encoding="utf-8", buffering=1
                    )
                handle = file_handles[log_type]
                if handle:
                    if not line.endswith("\n"):
                        line = line + "\n"
                    handle.write(line)
            except Exception:
                pass
            finally:
                self._queue.task_done()

            write_count += 1
            if write_count % 50 == 0:
                self._cleanup_logs()

        for handle in file_handles.values():
            try:
                if handle:
                    handle.flush()
                    handle.close()
            except Exception:
                pass

    def _cleanup_logs(self) -> None:
        for log_type in self._LOG_TYPES:
            self._cleanup_log_type(log_type)

    def _cleanup_log_type(self, log_type: str) -> None:
        prefix = f"{log_type}_"
        files = []
        for name in os.listdir(self._log_dir):
            if not name.startswith(prefix) or not name.endswith(".log"):
                continue
            path = os.path.join(self._log_dir, name)
            files.append(path)

        if not files:
            return

        files.sort(key=self._extract_timestamp)
        max_size_bytes = self._max_file_size_mb * 1024 * 1024
        current_path = self._paths.get(log_type)

        def has_oversize() -> bool:
            for p in files:
                try:
                    if os.path.getsize(p) > max_size_bytes:
                        return True
                except Exception:
                    continue
            return False

        while (len(files) > self._max_files or has_oversize()) and len(files) > 1:
            oldest = files[0]
            if current_path and oldest == current_path and len(files) > 1:
                oldest = files[1]
            try:
                os.remove(oldest)
            except Exception:
                break
            try:
                files.remove(oldest)
            except ValueError:
                break

    @staticmethod
    def _session_log_dir(base_log_dir: str, session_ts: str) -> str:
        date_part, time_part = session_ts.split("_", 1)
        date_dir = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
        return os.path.join(base_log_dir, date_dir, time_part)

    @staticmethod
    def _extract_timestamp(path: str) -> str:
        parent = os.path.basename(os.path.dirname(path))
        date_parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
        return f"{date_parent}_{parent}_{os.path.basename(path)}"
