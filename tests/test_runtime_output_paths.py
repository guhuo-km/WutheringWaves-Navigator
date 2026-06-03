import json
from pathlib import Path

from PIL import Image

from core import paths
from core.calibration import CalibrationDataManager
from core.log_manager import LogManager
from core.map_generator import MapGeneratorWorker
from route_recorder import RouteRecorder
import tile_generator
from server_manager import LocalServerManager, local_map_content_path


def test_route_recorder_uses_runtime_routes_dir(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    recorder = RouteRecorder()

    assert Path(recorder.routes_dir) == paths.routes_dir()
    assert not str(recorder.routes_dir).startswith(str(paths.src_root()))


def test_tile_generator_uses_runtime_map_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    source = tmp_path / "small_map.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(source)

    tile_generator.process_image(str(source))

    assert tile_generator.map_config_file() == paths.config_file("maps.json")
    assert (paths.images_dir() / "small_map.png").exists()
    assert json.loads(paths.config_file("maps.json").read_text(encoding="utf-8"))[0]["name"] == "small_map.png"


def test_server_manager_reads_and_deletes_runtime_map_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    paths.config_file("maps.json").write_text(
        json.dumps(
            [{"name": "demo.png", "tiled": False, "width": 10, "height": 10, "maxZoom": 0}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    paths.images_dir().mkdir(parents=True, exist_ok=True)
    (paths.images_dir() / "demo.png").write_text("image", encoding="utf-8")

    manager = LocalServerManager()

    assert manager.get_local_maps() == ["demo.png"]
    assert local_map_content_path("/maps.json") == paths.config_file("maps.json")
    assert local_map_content_path("/images/demo.png") == paths.images_dir() / "demo.png"
    assert manager.delete_local_map("demo.png") is True
    assert not (paths.images_dir() / "demo.png").exists()
    assert json.loads(paths.config_file("maps.json").read_text(encoding="utf-8")) == []


def test_calibration_data_uses_runtime_config(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    manager = CalibrationDataManager()

    assert Path(manager.calibration_file) == paths.config_file("calibration_data.json")
    assert not str(manager.calibration_file).startswith(str(paths.src_root()))


def test_log_manager_uses_runtime_logs_dir(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    manager = LogManager(session_ts="20260604_120000")
    try:
        assert Path(manager._base_log_dir) == paths.log_dir()
        assert not str(manager._base_log_dir).startswith(str(paths.src_root()))
    finally:
        manager.stop()


def test_map_generator_worker_no_longer_changes_cwd_for_output():
    source = Path(MapGeneratorWorker.run.__code__.co_filename).read_text(encoding="utf-8")

    assert "os.chdir" not in source
