"""
Test suite for Path-B-only OCR coordinate parsing.
"""

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from conftest import build_ocr_string_detections, build_yolo_detection
from ocr_engine import OCRWorker


def build_missing_comma_detections(
    text,
    missing_comma_indexes,
    start_x=10,
    start_y=10,
    char_width=10,
    char_height=20,
    gap=2,
):
    class_map = {
        '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
        '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
        ',': 10, ':': 11, '-': 12, '+': 13,
    }
    detections = []
    current_x = start_x
    missing_comma_indexes = set(missing_comma_indexes)

    for index, char in enumerate(text):
        if char == ' ':
            current_x += char_width + gap
            continue
        if char == ',' and index in missing_comma_indexes:
            current_x += char_width + gap
            continue
        if char not in class_map:
            continue

        bbox = [current_x, start_y, current_x + char_width, start_y + char_height]
        detections.append(build_yolo_detection(class_id=class_map[char], bbox=bbox))
        current_x += char_width + gap

    return detections


class TestPathBParsing:
    @pytest.fixture
    def ocr_worker(self):
        return OCRWorker(config_dict={})

    def test_normal_comma_coordinates(self, ocr_worker):
        detections = build_ocr_string_detections("-500,100,50")
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert metadata['complete'] is True

    def test_missing_commas_rescue(self, ocr_worker):
        detections = build_ocr_string_detections("-500 100 50", gap=30)
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert metadata['method'] in ['path_b', 'path_b_fallback', 'path_b_groups']

    def test_no_separators_with_spacing(self, ocr_worker):
        detections = build_ocr_string_detections("-500  100  50")
        success, coords, _ = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)

    def test_current_frame_success_uses_path_b(self, ocr_worker):
        detections = build_ocr_string_detections("-500 100 50", gap=30)
        success, coords = ocr_worker._apply_tracking_algorithm(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert ocr_worker.get_current_state() == "SUCCESS"

    def test_current_frame_failure_does_not_reuse_previous_success(self, ocr_worker):
        detections = build_ocr_string_detections("-500 100 50", gap=30)
        success, coords = ocr_worker._apply_tracking_algorithm(detections)
        assert success is True
        assert coords == (-500, 100, 50)

        success, coords = ocr_worker._apply_tracking_algorithm([])
        assert success is False
        assert coords is None
        assert ocr_worker.get_current_state() == "FAILED"

    def test_current_frame_failure_emits_frame_completion(self, ocr_worker):
        emitted = []
        ocr_worker.frame_recognition_completed.connect(emitted.append)

        success, coords = ocr_worker._apply_tracking_algorithm([])

        assert success is False
        assert coords is None
        assert len(emitted) == 1
        assert emitted[0]["ocr_coord"] is None
        assert "frame_result" in emitted[0]

    def test_timestamp_noise_with_timezone(self, ocr_worker):
        detections = build_ocr_string_detections("-500,100,50 2026-02-07 16:20:33 +8")
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert metadata['complete'] is True

    def test_missing_commas_with_timestamp_timezone(self, ocr_worker):
        detections = build_ocr_string_detections("-500 100 50 2026-02-07 16:20:33 +8", gap=30)
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert metadata['method'] in ['path_b_groups', 'path_b_fallback', 'path_b']

    def test_tracking_algorithm_runs_when_best_cluster_missing(self, ocr_worker, monkeypatch):
        detections = build_ocr_string_detections("-500 100 50", gap=30)
        monkeypatch.setattr("ocr_engine.find_best_coordinate_cluster", lambda clusters: (None, []))
        success, coords = ocr_worker._apply_tracking_algorithm(detections)
        assert success is True
        assert coords == (-500, 100, 50)

    def test_rejects_embedded_timestamp_contamination(self, ocr_worker):
        noisy = "-1183,-66023952026-02-0721:31:2618"
        detections = build_ocr_string_detections(noisy)
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is False
        assert coords is None
        assert metadata['method'] in [
            'path_b_groups_reject_timestamp_noise',
            'path_b_groups_reject_time_contaminated_triplet',
            'path_b_fallback',
        ]

    def test_recovers_compact_x_y_joined(self, ocr_worker):
        detections = build_ocr_string_detections("-1168-6592,395")
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-1168, -6592, 395)
        assert metadata['method'] in ['path_b_groups', 'path_b_fallback', 'path_b']

    def test_recovers_compact_yz_joined(self, ocr_worker):
        detections = build_missing_comma_detections("-1168,-6592,395", missing_comma_indexes=[11])
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-1168, -6592, 395)
        assert metadata['method'] in ['path_b_groups', 'path_b_fallback', 'path_b']

    def test_group_split_at_inner_minus(self, ocr_worker):
        detections = build_ocr_string_detections("-1168-6592,395")
        groups, _ = ocr_worker._group_contiguous_tokens(detections)
        assert groups == ['-1168', '-6592', '395']

    def test_recovers_compact_xy_with_timestamp_tail(self, ocr_worker):
        detections = build_missing_comma_detections("2406,3306,-372026-02-0800:15:4318", missing_comma_indexes=[4])
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (2406, 3306, -37)
        assert metadata.get('recovered_from_two_group_gap') is True

    def test_recovers_compact_xy_without_timestamp(self, ocr_worker):
        detections = build_missing_comma_detections("2406,3306,-37", missing_comma_indexes=[4])
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (2406, 3306, -37)
        assert metadata['method'] in ['path_b_groups', 'path_b']

    def test_rejects_time_like_triplet_after_timestamp(self, ocr_worker):
        noisy = "24063306,15182026-02-0800:15:18"
        detections = build_ocr_string_detections(noisy)
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is False
        assert coords is None
        assert metadata['method'] in [
            'path_b_groups_reject_time_contaminated_triplet',
            'path_b_groups_reject_timestamp_noise',
            'path_b_fallback',
        ]

    def test_truncate_groups_embedded_year_marker(self, ocr_worker):
        groups = ['-1183', '-66023952026-02-0721', '31', '2618']
        trimmed = ocr_worker._truncate_groups_before_timestamp(groups)
        assert trimmed == ['-1183', '-6602395']

    def test_only_filters_current_system_year(self, ocr_worker):
        current_year = datetime.datetime.now().year
        prev_year = current_year - 1

        det_current = build_ocr_string_detections(
            f"-500 100 50 {current_year}-02-07 16:20:33 +8",
            gap=30,
        )
        success_current, coords_current, _ = ocr_worker._parse_path_b_spacing_dominant(det_current)
        assert success_current is True
        assert coords_current == (-500, 100, 50)

        det_prev = build_ocr_string_detections(
            f"-500 100 50 {prev_year}-02-07 16:20:33 +8",
            gap=30,
        )
        success_prev, coords_prev, _ = ocr_worker._parse_path_b_spacing_dominant(det_prev)
        assert success_prev is True
        assert coords_prev == (-500, 100, 50)

    def test_candidate_choice_ignores_previous_coordinate_attribute(self, ocr_worker):
        ocr_worker.last_valid_coord = (1010, 2010, 100)
        result = ocr_worker._choose_best_xyz_candidate([(1000, 2000, 100), (1010, 2010, 100)])
        assert result == (1000, 2000, 100)


class TestPathBEdgeCases:
    @pytest.fixture
    def ocr_worker(self):
        return OCRWorker(config_dict={})

    def test_empty_detections(self, ocr_worker):
        success, coords, _ = ocr_worker._parse_path_b_spacing_dominant([])
        assert success is False
        assert coords is None

    def test_single_coordinate_value(self, ocr_worker):
        detections = build_ocr_string_detections("-500")
        success, _, _ = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is False

    def test_two_coordinate_values(self, ocr_worker):
        detections = build_ocr_string_detections("-500,100")
        success, _, _ = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is False

    def test_coordinate_range_validation(self, ocr_worker):
        detections = build_ocr_string_detections("99999999,100,50")
        success, _, _ = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is False

    def test_mixed_separators(self, ocr_worker):
        detections = build_ocr_string_detections("-500,100 50")
        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert metadata['method'] in ['path_b', 'path_b_fallback', 'path_b_groups']
        assert (success and coords is not None) or (not success and coords is None)

    def test_large_gap_detection(self, ocr_worker):
        detections = []
        x_pos = 0
        char_width = 10
        normal_gap = 2
        large_gap = 30

        for char in "-500":
            class_id = 12 if char == '-' else int(char)
            detections.append(build_yolo_detection(class_id=class_id, bbox=[x_pos, 10, x_pos + char_width, 30], confidence=0.9))
            x_pos += char_width + normal_gap

        x_pos += large_gap
        for char in "100":
            detections.append(build_yolo_detection(class_id=int(char), bbox=[x_pos, 10, x_pos + char_width, 30], confidence=0.9))
            x_pos += char_width + normal_gap

        x_pos += large_gap
        for char in "50":
            detections.append(build_yolo_detection(class_id=int(char), bbox=[x_pos, 10, x_pos + char_width, 30], confidence=0.9))
            x_pos += char_width + normal_gap

        success, coords, metadata = ocr_worker._parse_path_b_spacing_dominant(detections)
        assert success is True
        assert coords == (-500, 100, 50)
        assert metadata['complete'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
