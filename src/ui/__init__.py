# -*- coding: utf-8 -*-
"""
UI Module - FluentWindow-based modern interface

Uses lazy loading to avoid circular imports and premature widget construction.
"""


def __getattr__(name):
    """Lazy load MainWindow to avoid side effects during import."""
    if name == 'MainWindow':
        from .main_window import MainWindow
        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['MainWindow']
