# -*- coding: utf-8 -*-
"""
Opt-in runtime counters for investigating high CPU reports.

This module is intentionally passive by default. It is enabled only when
settings key ``diagnostics.resource_probe_enabled`` is true.
"""

from __future__ import annotations

from collections import Counter
from time import monotonic
from typing import Optional

from .settings_manager import SettingsManager


class ResourceProbe:
    """Small in-process counter aggregator for temporary diagnostics."""

    def __init__(self, settings: Optional[SettingsManager] = None, log_manager=None):
        self._settings = settings or SettingsManager()
        self._log_manager = log_manager
        self._enabled = bool(self._settings.get("diagnostics.resource_probe_enabled", False))
        self._interval_s = max(10.0, float(self._settings.get("diagnostics.resource_probe_interval_s", 60)))
        self._counters = Counter()
        self._last_flush = monotonic()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def count(self, name: str, amount: int = 1) -> None:
        if not self._enabled:
            return
        self._counters[str(name)] += int(amount)
        self.flush_if_due()

    def flush_if_due(self) -> None:
        if not self._enabled:
            return
        now = monotonic()
        if now - self._last_flush < self._interval_s:
            return
        self.flush()

    def flush(self) -> None:
        if not self._enabled:
            return
        now = monotonic()
        elapsed = max(0.001, now - self._last_flush)
        parts = [
            f"{key}={value} ({value / elapsed:.2f}/s)"
            for key, value in sorted(self._counters.items())
        ]
        line = f"[RESOURCE_PROBE] interval={elapsed:.1f}s " + ("; ".join(parts) if parts else "no events")
        if self._log_manager:
            try:
                self._log_manager.enqueue("debug", line)
            except Exception:
                pass
        else:
            print(line)
        self._counters.clear()
        self._last_flush = now
