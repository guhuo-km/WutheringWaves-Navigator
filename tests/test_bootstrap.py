"""Test bootstrap helpers.

This repository vendors a PySide6-compatible qfluentwidgets distribution under
``PyQt-Fluent-Widgets-PySide6``. When running tests directly, the system
environment might have a different qfluentwidgets installed (e.g. PyQt5-based),
which can break widget construction even if a QApplication exists.

Importing this module ensures:
1) Offscreen Qt platform is used for CI/headless environments.
2) The vendored qfluentwidgets path is prepended so imports are consistent with
   the packaged app runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepend_vendored_qfluentwidgets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    vendored = repo_root / "PyQt-Fluent-Widgets-PySide6"
    if vendored.is_dir():
        sys.path.insert(0, str(vendored))


# Must set platform before importing PySide6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_prepend_vendored_qfluentwidgets()
