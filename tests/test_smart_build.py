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

    dist_version = json.loads((dist_root / "_internal" / "version.json").read_text(encoding="utf-8"))
    source_after = json.loads(source_version.read_text(encoding="utf-8"))
    assert dist_version["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"
    assert not (dist_root / "version.json").exists()
    assert source_after["update_base_url"] == ""


def test_smart_builder_leaves_dist_version_when_update_url_unconfigured(tmp_path):
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.update_base_url = ""

    assert builder.inject_dist_version_info() is True


def test_smart_builder_prunes_known_large_unused_artifacts(tmp_path):
    dist_root = tmp_path / "dist" / "WutheringWaves-Navigator-Smart"
    resources = dist_root / "_internal" / "PySide6" / "resources"
    debug_pak = resources / "qtwebengine_devtools_resources.debug.pak"
    devtools_pak = resources / "qtwebengine_devtools_resources.pak"
    debug_resources_pak = resources / "qtwebengine_resources.debug.pak"
    debug_snapshot = resources / "v8_context_snapshot.debug.bin"
    debug_100p = resources / "qtwebengine_resources_100p.debug.pak"
    debug_200p = resources / "qtwebengine_resources_200p.debug.pak"
    ffmpeg_dll = dist_root / "_internal" / "cv2" / "opencv_videoio_ffmpeg4130_64.dll"
    kept_pak = resources / "qtwebengine_resources.pak"
    debug_pak.parent.mkdir(parents=True)
    ffmpeg_dll.parent.mkdir(parents=True)
    for path in (
        debug_pak,
        devtools_pak,
        debug_resources_pak,
        debug_snapshot,
        debug_100p,
        debug_200p,
    ):
        path.write_bytes(b"unused")
    ffmpeg_dll.write_bytes(b"ffmpeg")
    kept_pak.write_bytes(b"keep")

    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path

    assert builder.prune_packaged_artifacts() is True

    assert not debug_pak.exists()
    assert not devtools_pak.exists()
    assert not debug_resources_pak.exists()
    assert not debug_snapshot.exists()
    assert not debug_100p.exists()
    assert not debug_200p.exists()
    assert not ffmpeg_dll.exists()
    assert kept_pak.exists()


def test_smart_builder_exports_clean_prebuilt_minimap_cache(tmp_path):
    source = tmp_path / "source"
    area = source / "906"
    tile = area / "standard" / "default" / "base" / "1_2.png"
    sift = area / "indexes" / "sift_tiles" / "sift.npz"
    db = area / "indexes" / "minimap_index.sqlite3"
    state = area / "indexes" / "tile_index_state.json"
    tmp_file = area / "indexes" / "tile_index_state.json.tmp"
    wal = area / "indexes" / "minimap_index.sqlite3-wal"
    shm = area / "indexes" / "minimap_index.sqlite3-shm"
    for path in (tile, sift, db, state, tmp_file, wal, shm):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.prebuilt_minimap_cache = source

    assert builder.export_prebuilt_minimap_cache() is True

    target = tmp_path / "dist" / "WutheringWaves-Navigator-Smart" / "cache" / "minimap_tiles"
    assert (target / "906" / "standard" / "default" / "base" / "1_2.png").exists()
    assert (target / "906" / "indexes" / "sift_tiles" / "sift.npz").exists()
    assert (target / "906" / "indexes" / "minimap_index.sqlite3").exists()
    assert (target / "906" / "indexes" / "tile_index_state.json").exists()
    assert not (target / "906" / "indexes" / "tile_index_state.json.tmp").exists()
    assert not (target / "906" / "indexes" / "minimap_index.sqlite3-wal").exists()
    assert not (target / "906" / "indexes" / "minimap_index.sqlite3-shm").exists()


def test_smart_builder_uses_runtime_minimap_cache_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("WUWA_PREBUILT_MINIMAP_CACHE", raising=False)
    monkeypatch.setattr(SmartBuilder, "find_project_root", lambda self, project_path=None: tmp_path)

    builder = SmartBuilder()

    assert builder.prebuilt_minimap_cache == tmp_path / ".runtime" / "cache" / "minimap_tiles"


def test_smart_builder_rejects_missing_default_minimap_cache(tmp_path):
    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.prebuilt_minimap_cache = tmp_path / ".runtime" / "cache" / "minimap_tiles"

    assert builder.export_prebuilt_minimap_cache() is False


def test_smart_builder_rejects_cache_without_complete_indexes(tmp_path):
    source = tmp_path / ".runtime" / "cache" / "minimap_tiles"
    tile = source / "8" / "standard" / "default" / "base" / "1_2.png"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")

    builder = SmartBuilder.__new__(SmartBuilder)
    builder.project_root = tmp_path
    builder.prebuilt_minimap_cache = source

    assert builder.export_prebuilt_minimap_cache() is False


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


def test_parse_build_args_accepts_prebuilt_minimap_cache_path():
    args = parse_build_args(["--prebuilt-minimap-cache", "C:/cache/minimap_tiles"])

    assert args.prebuilt_minimap_cache == "C:/cache/minimap_tiles"


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


def test_main_build_avoids_collecting_unused_runtime_packages(tmp_path):
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
    builder.check_package_installed = lambda package: True

    args = builder.build_pyinstaller_args()

    assert not any(arg.startswith("--collect-all=") for arg in args)
    assert "--exclude-module=torch" in args
    assert "--exclude-module=torchvision" in args
    assert "--exclude-module=qfluentwidgets.multimedia" in args
    assert "--exclude-module=PySide6.QtMultimedia" in args
    assert "--exclude-module=PySide6.QtMultimediaWidgets" in args
    assert "--exclude-module=cv2.data" in args


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
            "include_files": ["class_names.txt", "coord_ocr.onnx"],
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


def test_clean_updater_build_declares_psutil_dependency():
    builder = SmartBuilder(skip_deps=True, skip_updater=True)

    assert any(
        package.lower().startswith("psutil")
        for package in builder.required_packages
    )
    for requirements_file in builder.project_config["requirements_files"]:
        lines = (builder.project_root / requirements_file).read_text(
            encoding="utf-8"
        ).splitlines()
        assert any(line.strip().lower().startswith("psutil") for line in lines), (
            requirements_file
        )


def test_build_uses_single_pinned_directml_distribution_with_onnxruntime_import():
    builder = SmartBuilder(skip_deps=True, skip_updater=True)

    assert "onnxruntime-directml==1.24.4" in builder.required_packages
    assert not any(package.startswith("onnxruntime>") for package in builder.required_packages)
    assert builder.package_import_aliases["onnxruntime-directml"] == "onnxruntime"
    for requirements_file in builder.project_config["requirements_files"]:
        lines = (builder.project_root / requirements_file).read_text(encoding="utf-8").splitlines()
        runtime_lines = [line.strip() for line in lines if line.strip().startswith("onnxruntime")]
        assert runtime_lines == ["onnxruntime-directml==1.24.4"]


def test_dependency_check_fails_when_directml_provider_is_unavailable(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    monkeypatch.setattr(
        builder,
        "_distribution_version",
        lambda name: "1.24.4" if name == "onnxruntime-directml" else None,
    )
    fake_runtime = type(
        "FakeRuntime",
        (),
        {"get_available_providers": staticmethod(lambda: ["CPUExecutionProvider"])},
    )
    monkeypatch.setattr(builder, "_import_onnxruntime", lambda: fake_runtime)

    assert builder.verify_directml_runtime() is False


def test_dependency_check_accepts_directml_provider(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    monkeypatch.setattr(
        builder,
        "_distribution_version",
        lambda name: "1.24.4" if name == "onnxruntime-directml" else None,
    )
    fake_runtime = type(
        "FakeRuntime",
        (),
        {"get_available_providers": staticmethod(lambda: ["DmlExecutionProvider"])},
    )
    monkeypatch.setattr(builder, "_import_onnxruntime", lambda: fake_runtime)

    assert builder.verify_directml_runtime() is True


def test_dependency_check_rejects_missing_directml_distribution(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    monkeypatch.setattr(builder, "_distribution_version", lambda _name: None)
    monkeypatch.setattr(
        builder,
        "_import_onnxruntime",
        lambda: (_ for _ in ()).throw(AssertionError("must fail before import")),
    )

    assert builder.verify_directml_runtime() is False


def test_dependency_check_rejects_wrong_directml_distribution_version(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    monkeypatch.setattr(
        builder,
        "_distribution_version",
        lambda name: "1.24.3" if name == "onnxruntime-directml" else None,
    )

    assert builder.verify_directml_runtime() is False


def test_dependency_check_rejects_conflicting_plain_onnxruntime(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    versions = {
        "onnxruntime-directml": "1.24.4",
        "onnxruntime": "1.26.0",
    }
    monkeypatch.setattr(builder, "_distribution_version", versions.get)

    assert builder.verify_directml_runtime() is False


def test_directml_package_check_uses_distribution_not_shared_import(monkeypatch):
    builder = SmartBuilder(skip_deps=True, skip_updater=True)
    monkeypatch.setattr(builder, "_distribution_version", lambda _name: None)
    monkeypatch.setattr(
        "scripts.smart_build.importlib.util.find_spec",
        lambda _name: object(),
    )

    assert builder.check_package_installed("onnxruntime-directml") is False
