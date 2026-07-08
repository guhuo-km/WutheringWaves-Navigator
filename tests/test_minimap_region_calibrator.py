from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from ocr_region_calibrator import OCRRegionCalibrator, constrained_selection_rect


def _app():
    return QApplication.instance() or QApplication([])


def test_constrained_selection_rect_forces_square_from_drag_direction():
    rect = constrained_selection_rect(QPoint(10, 20), QPoint(40, 80), force_square=True)

    assert rect.x() == 10
    assert rect.y() == 20
    assert rect.width() == 60
    assert rect.height() == 60


def test_minimap_calibrator_reports_circle_when_shift_forces_square():
    calibrator = OCRRegionCalibrator(
        _app(),
        region_label="小地图区域",
        selection_shape="ellipse",
        shift_forces_circle=True,
    )
    emitted = []
    calibrator.region_shape_selected.connect(lambda x, y, w, h, shape: emitted.append((x, y, w, h, shape)))

    calibrator.selection_rect = constrained_selection_rect(QPoint(10, 20), QPoint(40, 80), force_square=True)
    calibrator._last_shape_forced_by_shift = True
    calibrator.confirm_selection()

    assert emitted
    assert emitted[0][2] == emitted[0][3]
    assert emitted[0][4] == "circle"
    calibrator.close()


def test_minimap_calibrator_keeps_ellipse_shape_without_shift():
    calibrator = OCRRegionCalibrator(
        _app(),
        region_label="小地图区域",
        selection_shape="ellipse",
        shift_forces_circle=True,
    )
    emitted = []
    calibrator.region_shape_selected.connect(lambda x, y, w, h, shape: emitted.append((x, y, w, h, shape)))

    calibrator.selection_rect = constrained_selection_rect(QPoint(10, 20), QPoint(40, 80), force_square=False)
    calibrator._last_shape_forced_by_shift = False
    calibrator.confirm_selection()

    assert emitted
    assert emitted[0][2] != emitted[0][3]
    assert emitted[0][4] == "ellipse"
    calibrator.close()


def test_regular_ocr_calibrator_defaults_to_rectangular_selection():
    calibrator = OCRRegionCalibrator(_app(), region_label="OCR区域")

    assert calibrator.selection_shape == "rect"
    assert calibrator.shift_forces_circle is False
    assert calibrator._shape_for_modifiers(Qt.KeyboardModifier.ShiftModifier) == "rect"
    calibrator.close()
