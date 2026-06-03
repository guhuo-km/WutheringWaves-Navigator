# Project Structure

This document describes the current active project structure. Older implementations may still exist in git history, but should not be kept in the main source tree when they are no longer part of the product path.

## Active Runtime

- `src/main_app.py`: application entry point.
- `src/ui/main_window.py`: main FluentWindow orchestration layer.
- `src/ui/interfaces/`: current page-level UI modules.
- `src/ui/components/`: shared current UI widgets.
- `src/ui/dialogs/`: current dialogs used by startup, OCR, calibration, and window selection.

## Core Runtime

- `src/core/app_state.py`: shared application state and signals.
- `src/core/settings_manager.py`: persisted settings access.
- `src/core/log_manager.py`: application log layout and log writing.
- `src/core/map_backend.py`: WebChannel backend exposed to the map page.
- `src/core/map_control_bridge.py`: Python-to-userscript map command payloads.
- `src/core/update_provider.py`, `src/core/update_downloader.py`, `src/core/file_updater.py`, `src/core/update_manifest.py`, `src/core/update_lock.py`: online update flow.
- `src/core/startup_maintenance.py`: startup cleanup for obsolete packaged files.
- `src/core/version.py`: application version metadata.

## Map And Script Assets

- `src/index.html`: local map page.
- `js/wuwa_map_optimizer.js`: full userscript for official map integration.
- `js/wuwa_map_optimizer_lite.js`: lite userscript for local map integration.
- `templates/`: userscript wrapper templates.
- `src/greasemonkey_manager.py`: current script injection manager.
- `src/separated_map_window.py`: detachable map window still used by the current main UI.

## OCR And Automation

- `src/ocr_manager.py`: OCR workflow coordination.
- `src/ocr_engine.py`: OCR inference implementation.
- `src/screen_capture.py`: screen capture helpers.
- `src/ocr_region_calibrator.py`: OCR region calibration UI.
- `src/hotkey_manager.py`: global hotkey handling.

## Routes And Local Maps

- `src/route_recorder.py`: route recording.
- `src/route_list_dialog.py`: route detail/list dialogs still used by the current UI.
- `src/core/map_generator.py` and `src/tile_generator.py`: local map generation path used by map settings.

## Build And Release

- `scripts/smart_build.py`: primary executable build entry.
- `scripts/installer.nsi`: NSIS installer definition.
- `scripts/make_release.py`: update manifest and release artifact generation.
- `version.json`: release/version metadata. Official local builds may contain the production update URL.

### Online Update Release Layout

The public update channel is split into versioned metadata and a persistent file pool:

```text
stable/
  latest.json
  changelog.json
  releases/
    <version>/
      release.json
      manifest.json
      installer/
  files/
    <sha256>
```

- `latest.json` points clients at the newest `releases/<version>/manifest.json`.
- Managed files in `manifest.json` use absolute `.../stable/files/<sha256>` URLs.
- `stable/files/<sha256>` is shared across all versions and should only receive missing hashes.
- Versioned release folders should not duplicate managed payload files.
- Protected/user-data files stay out of the hash pool and are skipped by the updater.
- The private `.local/scripts/publish_delta_update.ps1` script packages `stable/files` and uploads it with `rsync --ignore-existing`, then overwrites only metadata for the new version.

## Removed Legacy Code

Legacy alternate UI and old map-window implementations are intentionally removed from the main source tree once they stop participating in the active runtime. To inspect an older implementation, use git history instead of reintroducing stale files:

```powershell
git log -- src/control_console.py
git show <commit>:src/control_console.py
git show <commit>:src/map_window.py
git show <commit>:src/simple_map_window.py
```

Use `docs/main_app_legacy_analysis.md` only as a historical reference for the old monolithic UI. Current implementation work should start from the active runtime sections above.
