# WutheringWaves Navigator

WutheringWaves Navigator is a Windows-first PySide6 desktop tool for map navigation, OCR coordinate recognition, route recording, and local map management for Wuthering Waves.

## Requirements

- Windows 10/11 64-bit
- Python 3.12 recommended
- Administrator privileges when running the app, because OCR and global hotkeys need access to game/window input state

## Install

Create and activate a virtual environment, then install the full dependency set:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements_fluent.txt
```

## Run From Source

```powershell
.\.venv\Scripts\python.exe src\main_app.py
```

Static project resources are kept in these canonical locations:

- `assets\`: application images and icons
- `models\`: OCR model files and class names
- `languages\`: translation files
- `config\`: default configuration templates

## Build

Use the project virtual environment explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\smart_build.py
```

Optional build flags:

```powershell
.\.venv\Scripts\python.exe scripts\smart_build.py --fast
.\.venv\Scripts\python.exe scripts\smart_build.py --include-local-maps
.\.venv\Scripts\python.exe scripts\smart_build.py --include-images
```

Build output is written to `dist\WutheringWaves-Navigator-Smart\`.

## Tests

Run the focused structure/path checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_paths.py tests\test_project_structure.py tests\test_runtime_output_paths.py tests\test_smart_build.py -q
```
