from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class MinimapObservationWorker(QObject):
    """Run minimap observation off the Qt UI thread with latest-frame backpressure."""

    result_ready = Signal(object)

    def __init__(
        self,
        collect_observation: Callable[[Any], dict[str, Any]],
        parent=None,
        result_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(parent)
        self._collect_observation = collect_observation
        self._result_callback = result_callback
        self._condition = threading.Condition()
        self._pending: Any = None
        self._has_pending = False
        self._active = False
        self._stop = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def submit(self, ocr_candidate: Any) -> None:
        with self._condition:
            self._pending = ocr_candidate
            self._has_pending = True
            self._condition.notify()

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        deadline = threading.Event()
        # Use Condition.wait with monotonic timeout calculation without importing time in tests.
        import time

        end_at = time.monotonic() + float(timeout)
        with self._condition:
            while self._active or self._has_pending:
                remaining = end_at - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def shutdown(self, timeout: float = 1.0) -> bool:
        with self._condition:
            self._stop = True
            self._has_pending = False
            self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout=max(0.0, float(timeout)))
        return not self._thread.is_alive()

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                while not self._has_pending and not self._stop:
                    self._condition.wait()
                if self._stop:
                    self._active = False
                    self._condition.notify_all()
                    return
                ocr_candidate = self._pending
                self._pending = None
                self._has_pending = False
                self._active = True

            observation: dict[str, Any]
            try:
                observation = self._collect_observation(ocr_candidate)
            except Exception as exc:
                observation = {
                    "visual_candidate": None,
                    "visual_result": None,
                    "heading_candidate": None,
                    "visual_failure_reason": "observation_error",
                    "heading_failure_reason": "observation_error",
                    "error": str(exc),
                }

            payload = {
                "ocr_candidate": ocr_candidate,
                "observation": observation,
            }
            if self._result_callback is not None:
                try:
                    self._result_callback(payload)
                except Exception:
                    pass
            self.result_ready.emit(payload)

            with self._condition:
                self._active = False
                self._condition.notify_all()
