# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.file_updater import apply_staged_update
from core.update_downloader import stage_file_update
from core.update_lock import update_lock
from core.update_manifest import ReleaseManifest

STAGE_LABELS = {
    "waiting": "正在准备更新...",
    "download": "正在下载更新文件...",
    "verify": "正在校验更新文件...",
    "apply": "正在应用更新...",
    "complete": "正在完成更新...",
}

UPDATER_UI_BACKEND = "tkinter"


def updater_stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, STAGE_LABELS["waiting"])


def parse_update_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WutheringWaves Navigator updater")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--main-exe", required=True)
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--version")
    parser.add_argument("--manifest-url")
    parser.add_argument("--full-zip-url", default="")
    parser.add_argument("--full-zip-sha256", default="")
    parser.add_argument("--staging-root")
    parser.add_argument("--manifest")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-restart", action="store_true")
    return parser.parse_args(argv)


def wait_for_process_exit(pid: int, timeout_seconds: int) -> bool:
    if pid <= 0:
        return True
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            import psutil

            if not psutil.pid_exists(pid):
                return True
        except Exception:
            return True
        time.sleep(0.5)
    return False


def _progress_percent(downloaded: int, total: int) -> int:
    if total <= 0:
        return 10
    return max(0, min(69, int(downloaded * 70 / total)))


def _load_manifest(path: str | Path) -> ReleaseManifest:
    manifest_data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ReleaseManifest.from_dict(manifest_data)


def run_update_flow(
    args: argparse.Namespace,
    progress_callback,
    stage_update=stage_file_update,
    apply_update=apply_staged_update,
    wait_for_exit=wait_for_process_exit,
) -> Path:
    app_root = Path(args.app_root)
    with update_lock(app_root):
        if not wait_for_exit(args.wait_pid, 30):
            raise RuntimeError("主程序仍在运行，更新已取消。")

        progress_callback("download", 0)
        if args.manifest and args.staging_root:
            staged_root = Path(args.staging_root)
            manifest_path = Path(args.manifest)
        else:
            if not args.version or not args.manifest_url:
                raise RuntimeError("更新参数不完整。")

            def on_download_progress(downloaded: int, total: int):
                progress_callback("download", _progress_percent(downloaded, total))

            staged = stage_update(
                version=args.version,
                manifest_url=args.manifest_url,
                full_zip_url=args.full_zip_url,
                full_zip_sha256=args.full_zip_sha256 or None,
                staging_base=app_root / ".update" / "staging",
                app_root=app_root,
                timeout=args.timeout,
                progress_callback=on_download_progress,
            )
            staged_root = Path(staged.staging_root)
            manifest_path = Path(staged.manifest_path)

        progress_callback("verify", 70)
        manifest = _load_manifest(manifest_path)
        progress_callback("apply", 75)
        apply_update(app_root, staged_root, manifest)
        progress_callback("complete", 100)
    return app_root / args.main_exe


class UpdaterWindow:
    def __init__(self, args: argparse.Namespace):
        import tkinter as tk
        from tkinter import ttk

        self.args = args
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("正在更新呜呜大地图")
        self.root.resizable(False, False)
        self.root.geometry("460x190")

        self.title_var = tk.StringVar(value="正在更新呜呜大地图")
        self.stage_var = tk.StringVar(value=updater_stage_label("waiting"))
        self.detail_var = tk.StringVar(value="请不要关闭电脑或重复启动软件。")
        self.progress_var = tk.IntVar(value=0)

        container = ttk.Frame(self.root, padding=(24, 20, 24, 18))
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, textvariable=self.title_var, font=("Microsoft YaHei UI", 12, "bold"))
        title.pack(anchor="w")
        stage = ttk.Label(container, textvariable=self.stage_var)
        stage.pack(anchor="w", pady=(12, 6))
        self.progress = ttk.Progressbar(container, maximum=100, variable=self.progress_var, length=408)
        self.progress.pack(fill="x")
        detail = ttk.Label(container, textvariable=self.detail_var)
        detail.pack(anchor="w", pady=(8, 14))

        button_bar = ttk.Frame(container)
        button_bar.pack(fill="x")
        self.cancel_button = ttk.Button(button_bar, text="取消", command=self.root.destroy)
        self.cancel_button.state(["disabled"])
        self.start_button = ttk.Button(button_bar, text="启动软件", command=self._start_app)
        self.later_button = ttk.Button(button_bar, text="稍后启动", command=self.root.destroy)
        self.later_button.pack(side="right")
        self.start_button.pack(side="right", padx=(0, 8))
        self.cancel_button.pack(side="right")
        self.start_button.pack_forget()
        self.later_button.pack_forget()

        self.main_exe_path: Path | None = None
        self._closing_after_failure = False

    def _on_progress(self, stage: str, percent: int):
        self.stage_var.set(updater_stage_label(stage))
        self.progress_var.set(percent)
        if stage != "download":
            self.cancel_button.state(["disabled"])

    def _on_finished(self, ok: bool, message: str):
        if ok:
            self.stage_var.set("更新完成")
            self.detail_var.set("新版本已应用完成。")
            self.progress_var.set(100)
            self.cancel_button.pack_forget()
            self.later_button.pack(side="right")
            self.start_button.pack(side="right", padx=(0, 8))
            return
        self.stage_var.set("更新失败")
        self.detail_var.set(message or "更新失败，请稍后重试。")
        self.cancel_button.configure(text="关闭")
        self.cancel_button.state(["!disabled"])

    def _start_app(self):
        if self.main_exe_path and self.main_exe_path.exists():
            subprocess.Popen([str(self.main_exe_path)], cwd=str(self.main_exe_path.parent))
        self.root.destroy()

    def run(self) -> int:
        def worker():
            try:
                self.main_exe_path = run_update_flow(
                    self.args,
                    progress_callback=lambda stage, percent: self.root.after(0, self._on_progress, stage, percent),
                )
                self.root.after(0, self._on_finished, True, "")
            except Exception as exc:
                self.root.after(0, self._on_finished, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()
        self.root.mainloop()
        return 0


def main() -> int:
    args = parse_update_args()
    try:
        return UpdaterWindow(args).run()
    except RuntimeError as exc:
        print(str(exc))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
