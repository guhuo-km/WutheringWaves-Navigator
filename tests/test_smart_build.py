import json

from scripts.smart_build import SmartBuilder, parse_build_args


def test_smart_builder_injects_dist_update_url_without_changing_source(tmp_path):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    source_version = project_root / "version.json"
    source_version.write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "version": "0.2.0",
                "channel": "stable",
                "update_base_url": "",
            }
        ),
        encoding="utf-8",
    )

    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = project_root
    builder.update_base_url = "https://updates.example.com/wuwa/stable"

    assert builder.inject_dist_version_info() is True

    dist_version = json.loads((dist_root / "version.json").read_text(encoding="utf-8"))
    source_after = json.loads(source_version.read_text(encoding="utf-8"))
    assert dist_version["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"
    assert source_after["update_base_url"] == ""


def test_smart_builder_leaves_dist_version_when_update_url_unconfigured(tmp_path):
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.update_base_url = ""

    assert builder.inject_dist_version_info() is True


def test_smart_builder_prunes_known_large_unused_artifacts(tmp_path):
    dist_root = tmp_path / "dist" / "WutheringWaves-Navigator-Smart"
    debug_pak = dist_root / "_internal" / "PySide6" / "resources" / "qtwebengine_devtools_resources.debug.pak"
    ffmpeg_dll = dist_root / "_internal" / "cv2" / "opencv_videoio_ffmpeg4130_64.dll"
    kept_pak = dist_root / "_internal" / "PySide6" / "resources" / "qtwebengine_resources.pak"
    debug_pak.parent.mkdir(parents=True)
    ffmpeg_dll.parent.mkdir(parents=True)
    debug_pak.write_bytes(b"debug")
    ffmpeg_dll.write_bytes(b"ffmpeg")
    kept_pak.write_bytes(b"keep")

    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path

    assert builder.prune_packaged_artifacts() is True

    assert not debug_pak.exists()
    assert not ffmpeg_dll.exists()
    assert kept_pak.exists()


def test_parse_build_args_fast_expands_development_shortcuts():
    args = parse_build_args(["--fast"])

    assert args.no_clean is True
    assert args.skip_deps is True
    assert args.skip_updater is True


def test_parse_build_args_allows_independent_speed_flags():
    args = parse_build_args(["--no-clean", "--skip-updater", "--skip-deps"])

    assert args.no_clean is True
    assert args.skip_updater is True
    assert args.skip_deps is True


def test_no_clean_omits_pyinstaller_clean_flag(tmp_path):
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.project_config = {
        "name": "WutheringWaves-Navigator",
        "main_script": "src/main_app.py",
        "icon": "assets/ico.ico",
        "data_dirs": [],
        "data_files": [],
    }
    builder.include_local_maps = False
    builder.include_images = False
    builder.include_runtime_configs = False
    builder.no_clean = True
    builder.python_version = "312"
    builder.should_include_group = lambda group: True
    builder.resolve_data_dir = lambda candidates: None
    builder.get_python_dll_path = lambda: None
    builder.check_package_installed = lambda package: False

    args = builder.build_pyinstaller_args()

    assert "--clean" not in args
    assert "--noconfirm" in args


def test_runtime_language_config_is_not_packaged_as_default_user_setting(tmp_path):
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.project_config = {
        "name": "WutheringWaves-Navigator",
        "main_script": "src/main_app.py",
        "icon": "assets/ico.ico",
        "data_dirs": [],
        "data_files": [],
        "runtime_data_files": [
            ".runtime/config/ocr_config.json",
            ".runtime/config/app_settings.json",
            ".runtime/config/language_config.json",
        ],
    }
    builder.include_local_maps = False
    builder.include_images = False
    builder.include_runtime_configs = True
    builder.no_clean = True
    builder.python_version = "312"
    builder.should_include_group = lambda group: True
    builder.resolve_data_dir = lambda candidates: None
    builder.get_python_dll_path = lambda: None
    builder.check_package_installed = lambda package: False

    args = builder.build_pyinstaller_args()

    assert not any("language_config.json" in arg for arg in args)


def test_default_build_uses_canonical_static_resource_locations():
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_config = SmartBuilder(skip_deps=True, skip_updater=True).project_config

    model_dirs = [
        data_dir
        for data_dir in builder.project_config["data_dirs"]
        if data_dir["dest"] == "models"
    ]
    assert model_dirs == [
        {
            "dest": "models",
            "candidates": ["models"],
            "required": True,
            "include_files": ["class_names.txt", "coord_ocr.pt"],
        }
    ]
    assert "src/ocr_config.json" not in builder.project_config["runtime_data_files"]
    assert "src/app_settings.json" not in builder.project_config["runtime_data_files"]
    assert ".runtime/config/ocr_config.json" in builder.project_config["runtime_data_files"]
    assert ".runtime/config/app_settings.json" in builder.project_config["runtime_data_files"]

    language_dirs = [
        data_dir
        for data_dir in builder.project_config["data_dirs"]
        if data_dir["dest"] == "languages"
    ]
    assert language_dirs == [
        {
            "dest": "languages",
            "candidates": ["languages"],
            "required": True,
        }
    ]

    optional_runtime_dirs = {
        data_dir["dest"]: data_dir["candidates"]
        for data_dir in builder.project_config["data_dirs"]
        if data_dir["dest"] in {"tiles", "images"}
    }
    assert optional_runtime_dirs == {
        "tiles": [".runtime/tiles"],
        "images": [".runtime/images"],
    }
