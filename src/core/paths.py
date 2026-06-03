from __future__ import annotations

import sys
from pathlib import Path


def src_root() -> Path:
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    return src_root().parent


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve()
    return project_root()


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return app_root()
    return project_root() / ".runtime"


def runtime_dir(*parts: str) -> Path:
    path = runtime_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file(name: str) -> Path:
    return runtime_dir("config") / name


def log_file(name: str) -> Path:
    return runtime_dir("logs") / name


def log_dir() -> Path:
    return runtime_dir("logs")


def cache_dir(*parts: str) -> Path:
    return runtime_dir("cache", *parts)


def routes_dir() -> Path:
    return runtime_dir("recorded_routes")


def tiles_dir() -> Path:
    return runtime_dir("tiles")


def images_dir() -> Path:
    return runtime_dir("images")


def asset_file(*parts: str) -> Path:
    return resource_root().joinpath("assets", *parts)


def language_file(name: str) -> Path:
    return resource_root() / "languages" / name


def model_file(name: str) -> Path:
    return resource_root() / "models" / name
