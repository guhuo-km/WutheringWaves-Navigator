#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR Engine for WutheringWaves Navigator
集成的OCR坐标识别引擎
"""

import time
import datetime
import logging
import numpy as np
import numpy.typing as npt
import cv2
from typing import ClassVar, Optional, List, Tuple, Dict, Any, TypedDict
from pathlib import Path
import onnxruntime as ort
import math
import re
import traceback
from PySide6.QtCore import QThread, Signal


def cluster_detections_to_rich_clusters(
    detections: List[Dict[str, Any]],
    gap_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    改进的聚类算法：智能识别空格和分隔符
    能够正确区分 '2591 1891,5189' 中的空格分隔
    """
    if not detections:
        return []
    
    # 按x坐标从左到右排序
    detections.sort(key=lambda d: d['bbox'][0])
    
    # 计算当前检测批次中所有字符的平均宽度
    total_width = 0
    valid_char_count = 0
    for detection in detections:
        char = OCRWorker._class_id_to_char_static(detection['class'])
        if char and (char.isdigit() or char in ['-', ',']):  # 只统计数字、负号、逗号的宽度
            width = detection['bbox'][2] - detection['bbox'][0]
            if width > 0:
                total_width += width
                valid_char_count += 1
    
    if valid_char_count == 0:
        return []
    
    # 平均字符宽度
    avg_char_width = total_width / valid_char_count
    
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"[SMART_CLUSTERING] 平均字符宽度: {avg_char_width:.2f}, 检测到{valid_char_count}个有效字符")
    
    # 计算所有间隙，用于智能分隔符判断
    gaps = []
    for i in range(1, len(detections)):
        prev_x2 = detections[i-1]['bbox'][2]
        curr_x1 = detections[i]['bbox'][0]
        gap = curr_x1 - prev_x2
        gaps.append(gap)
    
    # 使用保守的阈值来避免过度分割
    if gaps:
        # 方法1: 基于平均字符宽度的倍数 - 使用更大的倍数避免分割数字
        threshold_1 = avg_char_width * 1.8  # 提高阈值，避免把数字内部分割开
        
        # 方法2: 基于间隙的统计特征
        gaps_sorted = sorted(gaps)
        if len(gaps_sorted) > 2:
            # 使用75分位数的2倍作为阈值，更保守
            percentile_75_index = int(len(gaps_sorted) * 0.75)
            percentile_75_gap = gaps_sorted[percentile_75_index]
            threshold_2 = percentile_75_gap * 2.0
        else:
            threshold_2 = threshold_1
        
        # 使用较大的阈值，避免过度分隔
        separation_threshold = max(threshold_1, threshold_2)
        
        logger.debug(f"[SMART_CLUSTERING] 分隔阈值: {separation_threshold:.2f} (方法1:{threshold_1:.2f}, 方法2:{threshold_2:.2f})")
    else:
        separation_threshold = avg_char_width * 1.8
    
    clusters = []
    current_word = ""
    current_detections_list = []
    last_x2 = None
    
    for detection in detections:
        char = OCRWorker._class_id_to_char_static(detection['class'])
        if not char:
            continue
            
        x1, y1, x2, y2 = detection['bbox']
        
        # 如果是第一个字符，直接添加
        if last_x2 is None:
            current_word = char
            current_detections_list = [detection]
            last_x2 = x2
            continue
        
        # 计算间隙
        gap = x1 - last_x2
        
        # 智能分隔判断
        should_separate = False
        
        # 标准1: 间隙超过分隔阈值
        if gap > separation_threshold:
            should_separate = True
            logger.debug(f"[SMART_CLUSTERING] 标准1触发: 间隙{gap:.2f} > 阈值{separation_threshold:.2f}")
        
        # 标准2: 检测明显的空格分隔（间隙显著大于字符宽度）
        if gap > avg_char_width * 2.5:  # 2.5倍字符宽度才认为是明显空格
            should_separate = True
            logger.debug(f"[SMART_CLUSTERING] 标准2触发: 检测到空格分隔 {gap:.2f} > {avg_char_width * 2.5:.2f}")
        
        # 标准3: 坐标逻辑分隔 - 更严格，避免误分割
        # 只有在间隙非常大的情况下，且前面是完整的较长数字时才分割
        if (current_word.replace(',', '').replace('-', '').isdigit() and len(current_word) >= 4 and 
            char.isdigit() and gap > avg_char_width * 2.0):  # 提高到2.0倍
            should_separate = True
            logger.debug(f"[SMART_CLUSTERING] 标准3触发: 数字分隔逻辑 '{current_word}' | '{char}'")
        
        if should_separate:
            # 保存当前聚类
            if current_word:
                clusters.append({'word': current_word, 'detections': current_detections_list})
            # 开始新聚类
            current_word = char
            current_detections_list = [detection]
        else:
            # 继续当前聚类
            current_word += char
            current_detections_list.append(detection)
        
        last_x2 = x2
    
    # 添加最后一个聚类
    if current_word:
        clusters.append({'word': current_word, 'detections': current_detections_list})
    
    logger.debug(f"[SMART_CLUSTERING] 聚类结果: {[cluster['word'] for cluster in clusters]}")
    
    return clusters




def find_best_coordinate_cluster(
    clusters: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    重写的坐标选择算法：去除语义评分，直接匹配坐标格式
    坐标格式：x,y,z（每个分量可能为正数或负数，位数1-7位不定）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 坐标格式正则：匹配 x,y,z 格式，每个分量可正可负，位数1-7位
    coord_pattern = re.compile(r'^-?\d{1,7},-?\d{1,7},-?\d{1,7}')
    
    best_cluster = None
    selection_details = []
    
    for cluster in clusters:
        word = cluster['word']
        cleaned_word = word.replace(" ", "").replace("\t", "")
        
        logger.debug(f"[COORD_SELECTION] 检查聚类: '{cleaned_word}'")
        
        # 记录选择详情
        detail = {
            'word': word,
            'cleaned': cleaned_word,
            'matched': False,
            'reason': ""
        }
        
        # 直接匹配坐标格式
        if coord_pattern.match(cleaned_word):
            logger.debug(f"[COORD_SELECTION] 找到坐标格式匹配: '{cleaned_word}'")
            detail['matched'] = True
            detail['reason'] = "匹配坐标格式"
            
            # 如果还没有选中的聚类，或者当前聚类更长（更完整），则选择它
            if best_cluster is None or len(cleaned_word) > len(best_cluster['word'].replace(" ", "")):
                best_cluster = cluster
                logger.debug(f"[COORD_SELECTION] 选中新的最佳聚类: '{cleaned_word}'")
        else:
            detail['reason'] = "不匹配坐标格式"
        
        selection_details.append(detail)
    
    if best_cluster:
        logger.debug(f"[COORD_SELECTION] 最终选择: '{best_cluster['word']}'")
    else:
        logger.debug(f"[COORD_SELECTION] 未找到匹配的坐标格式")
    
    return best_cluster, selection_details


class RecognitionState:
    """Recognition states for the state machine"""
    LOCKED = "LOCKED"
    LOST = "LOST"
    SEARCHING = "SEARCHING"


class OCRWorker(QThread):
    """
    OCR Worker implementing advanced predictive tracking algorithm
    
    This worker runs an ONNX OCR detection model on CPU and provides highly accurate coordinate
    tracking with state management and dynamic template adaptation.
    """
    
    # Static class names for global function access
    _class_names_static: ClassVar[List[str]] = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ',', ':', '-', '+']

    class _SuspectJumpState(TypedDict):
        coord: Tuple[int, int, int]
        count: int
        stable_coord: Tuple[int, int, int]
    
    # Qt Signals
    coordinates_detected = Signal(int, int, int)  # x, y, z coordinates
    recognition_state_changed = Signal(str)  # LOCKED, LOST, SEARCHING
    error_occurred = Signal(str)  # Error message
    ocr_output_updated = Signal(str)  # Raw OCR output text
    capture_area_updated = Signal(dict)  # Runtime capture area updates
    
    def __init__(self, config_dict=None, capture_callback=None):
        """
        Initialize OCR Worker
        
        Args:
            config_dict: Dictionary containing configuration parameters (optional)
            capture_callback: Function to capture screen regions (optional)
        """
        super().__init__()
        self.config_dict = config_dict or {}
        self.capture_callback = capture_callback
        self.logger = logging.getLogger(__name__)
        
        # Worker control
        self.is_running = False
        self.should_stop = False
        
        # ONNX OCR model
        self.model = None
        self.model_input_name = ""
        self.model_input_shape: Tuple[int, int] = (512, 512)
        self._last_onnx_scale: Tuple[float, float] = (1.0, 1.0)
        self._last_onnx_pad: Tuple[float, float] = (0.0, 0.0)
        self._last_onnx_source_shape: Tuple[int, int] = (0, 0)
        
        # Class names mapping
        self.class_names = self._load_class_names()
        
        # Advanced tracking algorithm state variables
        self.recognition_state = RecognitionState.SEARCHING
        self.last_valid_coord = None  # (x, y, z) tuple
        self.last_valid_detections = None  # Dynamic tracking template
        self.consecutive_failures = 0

        # Two-stage suspect jump confirmation
        self.suspect_jump: Optional[OCRWorker._SuspectJumpState] = None
        self.suspect_confirmation_window = 2

        # Dynamic ROI state
        self.consecutive_success_count = 0
        self.last_successful_bbox = None
        self.dynamic_roi_active = False
        self.dynamic_failure_count = 0
        self.dynamic_roi_base_area: Optional[Dict[str, int]] = None
        self.dynamic_roi_anchor_center_global: Optional[Tuple[int, int]] = None

        config = self.config_dict

        # Dynamic ROI constants
        self.ROI_TRIGGER_FRAMES = 3
        self.ROI_EXPAND_PIXELS = 5
        self.ROI_MAX_HEIGHT = 200
        self.ROI_MAX_WIDTH = 1000
        self.ROI_MIN_HEIGHT = int(config.get('roi_min_height', 60)) if isinstance(config, dict) else 60
        self.ROI_MIN_WIDTH = int(config.get('roi_min_width', 520)) if isinstance(config, dict) else 520
        self.ROI_SHRINK_MARGIN = int(config.get('roi_shrink_margin', 15)) if isinstance(config, dict) else 15

        # 去重优化：记录上一次发射的坐标
        self.last_emitted_coord = None
        self._last_inference_debug: Dict[str, Any] = {}
        self._last_candidate_clusters: List[Dict[str, Any]] = []
        self._last_selection_details: List[Dict[str, Any]] = []

        self._capture_error_count = 0
        
        # Configurable parameters (loaded from config dict)

        self.ROI_MAX_FAILURES_BEFORE_RESET = int(config.get('roi_max_failures_before_reset', 10)) if isinstance(config, dict) else 10
        
        self.confidence_threshold = config.get('confidence_threshold', 0.45)
        self.digit_confidence_threshold = config.get('digit_confidence_threshold', self.confidence_threshold)
        self.symbol_confidence_threshold = config.get('symbol_confidence_threshold', self.confidence_threshold)
        self.max_speed_threshold = config.get('max_speed_threshold', 1000)
        self.ema_alpha = config.get('ema_alpha', 0.3)
        self.lost_threshold_frames = config.get('lost_threshold_frames', 5)
        self.z_axis_threshold = config.get('z_axis_threshold', 50)
        
        # OCR capture area and interval
        self.capture_area = None
        self.ocr_interval = 1000  # milliseconds
        self.target_window_name = ""  # Target window name for screenshot
        self.detailed_ocr_logging = bool(config.get('detailed_ocr_logging', False))
        
        self.logger.info("OCR工作线程初始化完成")

    def set_detailed_ocr_logging(self, enabled: bool):
        """Enable/disable detailed OCR pipeline logs at runtime."""
        self.detailed_ocr_logging = bool(enabled)

    def _is_detailed_debug_enabled(self) -> bool:
        legacy_verbose = bool(
            self.config_dict.get('advanced_ocr_settings', {}).get('verbose_debug', False)
        )
        return bool(self.detailed_ocr_logging or legacy_verbose)

    def _emit_capture_area_updated(self) -> None:
        """Emit runtime capture area safely (tests may instantiate without Qt base init)."""
        try:
            if isinstance(self.capture_area, dict):
                self.capture_area_updated.emit(dict(self.capture_area))
        except Exception:
            pass

    def _build_raw_char_string(self, detections: List[Dict[str, Any]]) -> str:
        if not detections:
            return ""
        sorted_detections = sorted(detections, key=lambda d: d['bbox'][0])
        return "".join([
            OCRWorker._class_id_to_char_static(d['class']) or ""
            for d in sorted_detections
        ])

    def _emit_detailed_pipeline_log(
        self,
        state: str,
        raw_detections: List[Dict[str, Any]],
        best_cluster: Optional[Dict[str, Any]],
        path_b_result: Tuple[bool, Optional[Tuple[int, int, int]], Dict[str, Any]],
        final_success: bool,
        final_coords: Optional[Tuple[int, int, int]],
        note: str = "",
    ) -> None:
        if not self._is_detailed_debug_enabled():
            return

        try:
            raw_chars = self._build_raw_char_string(raw_detections)
            best_word = (best_cluster or {}).get('word', '') if best_cluster else ''
            best_count = len((best_cluster or {}).get('detections', [])) if best_cluster else 0

            b_success, b_coord, b_meta = path_b_result

            infer_dbg = self._last_inference_debug if isinstance(self._last_inference_debug, dict) else {}
            roi = infer_dbg.get('roi') if isinstance(infer_dbg.get('roi'), dict) else None
            roi_str = "--"
            if roi:
                roi_str = f"({roi.get('x', '-')},{roi.get('y', '-')},{roi.get('width', '-')},{roi.get('height', '-')})"

            self.ocr_output_updated.emit(
                f"[OCR-RAW] state={state} roi={roi_str} model_total={infer_dbg.get('total_boxes', 0)} kept={infer_dbg.get('kept_boxes', 0)} filtered={infer_dbg.get('filtered_boxes', 0)} raw='{raw_chars}'"
            )

            entries = infer_dbg.get('entries', []) if isinstance(infer_dbg.get('entries'), list) else []
            if entries:
                parts = []
                for e in entries[:36]:
                    parts.append(
                        f"'{e.get('char', '?')}'(conf={float(e.get('confidence', 0.0)):.2f},th={float(e.get('threshold', 0.0)):.2f},x={int(e.get('x', 0))},keep={'Y' if e.get('kept') else 'N'})"
                    )
                self.ocr_output_updated.emit(f"[OCR-RAW-CHARS] {' '.join(parts)}")

            clusters = self._last_candidate_clusters if isinstance(self._last_candidate_clusters, list) else []
            if clusters:
                cw = [f"'{c.get('word', '')}'({len(c.get('detections', []))})" for c in clusters]
                self.ocr_output_updated.emit(f"[OCR-CLUSTERS] count={len(clusters)} words={' '.join(cw)}")

            sel = self._last_selection_details if isinstance(self._last_selection_details, list) else []
            if sel:
                sw = []
                for d in sel[:12]:
                    cleaned = d.get('cleaned', '')
                    reason = d.get('reason', '')
                    matched = '✓' if d.get('matched') else '✗'
                    sw.append(f"'{cleaned}':{reason}{matched}")
                self.ocr_output_updated.emit(f"[OCR-SELECT] {' | '.join(sw)}")

            groups = b_meta.get('groups') if isinstance(b_meta, dict) else None
            trimmed = b_meta.get('trimmed_groups') if isinstance(b_meta, dict) else None
            self.ocr_output_updated.emit(
                "[OCR-PATH-B] "
                f"success={b_success} coords={b_coord} method={b_meta.get('method', 'unknown')} "
                f"avg_conf={float(b_meta.get('avg_confidence', 0.0)):.3f} "
                f"raw='{b_meta.get('raw_text', '')}' fallback='{b_meta.get('fallback_text', '')}' groups={groups} trimmed={trimmed}"
            )

            suffix = f" note={note}" if note else ""
            self.ocr_output_updated.emit(
                f"[OCR-FINAL] parser=path_b success={final_success} coords={final_coords}{suffix}"
            )
        except Exception as e:
            self.logger.debug(f"[OCR-DETAILED-LOG] emit failed: {e}")
    
    def set_capture_callback(self, capture_callback):
        """Set screen capture callback function
        
        Args:
            capture_callback: Function that captures screen region
                             Should accept: (x, y, width, height, mode, target_window_name)
                             Should return: numpy array of captured image or None if failed
        """
        self.capture_callback = capture_callback
    
    def _remove_timestamp_from_coord_string(self, coord_str: str) -> str:
        """
        精确的时间戳移除算法：只忽略202x-或203x-格式的时间戳
        用于避免误判z轴坐标（如z=20）为时间戳
        """
        self.logger.debug(f"[TIMESTAMP_REMOVAL] 输入字符串: '{coord_str}'")
        
        current_year = datetime.datetime.now().year

        # 仅匹配“当前系统年份-”作为时间戳起点（例如 2026-）
        timestamp_pattern = re.compile(fr'{current_year}-')
        match = timestamp_pattern.search(coord_str)
        
        if match:
            timestamp_start = match.start()
            timestamp_str = match.group()
            
            self.logger.debug(f"[TIMESTAMP_REMOVAL] 检测到时间戳格式: {timestamp_str} 在位置 {timestamp_start}, 强制截断")
            
            # 强制截断：忽略时间戳及其后面的所有内容
            result = coord_str[:timestamp_start].rstrip()
            self.logger.debug(f"[TIMESTAMP_REMOVAL] 时间戳截断结果: '{result}'")
            return result
        
        # 如果没有找到带破折号的时间戳，检查是否有空格分隔的时间戳部分
        # 坐标格式："-xxxx,-yyyy,-zzzz  yyyy-mm-dd hh:mm:ss"
        # 寻找两个或更多连续空格，认为是坐标和时间戳的分隔
        space_split = re.split(r'\s{2,}', coord_str, maxsplit=1)
        if len(space_split) > 1:
            result = space_split[0].strip()
            self.logger.debug(f"[TIMESTAMP_REMOVAL] 通过空格分隔移除时间戳: '{result}'")
            return result
        
        # 检查是否有“当前系统年份”在字符串末尾（没有破折号）
        # 例如: "-500,100,50 2026"
        year_only_pattern = re.compile(fr'\s+{current_year}$')
        if year_only_pattern.search(coord_str):
            result = year_only_pattern.sub('', coord_str).strip()
            self.logger.debug(f"[TIMESTAMP_REMOVAL] 移除末尾年份: '{result}'")
            return result
        
        # 如果没有找到时间戳标识，返回原字符串
        self.logger.debug(f"[TIMESTAMP_REMOVAL] 未找到时间戳标识，返回原字符串")
        return coord_str

    def _group_contiguous_tokens(self, detections: List[Dict[str, Any]]) -> Tuple[List[str], float]:
        """Group OCR chars by continuity (gap consistency + punctuation boundaries)."""
        if not detections:
            return [], 0.0

        sorted_detections = sorted(detections, key=lambda d: d['bbox'][0])
        tokens: List[Tuple[str, float, float]] = []
        confidences: List[float] = []
        for d in sorted_detections:
            ch = OCRWorker._class_id_to_char_static(d['class'])
            if not ch:
                continue
            x1, _, x2, _ = d['bbox']
            tokens.append((ch, float(x1), float(x2)))
            confidences.append(float(d.get('confidence', 0.0)))

        if not tokens:
            return [], 0.0

        gaps: List[float] = []
        widths: List[float] = []
        for i in range(1, len(tokens)):
            gaps.append(tokens[i][1] - tokens[i - 1][2])
        for _, x1, x2 in tokens:
            widths.append(max(1.0, x2 - x1))

        positive_gaps = sorted([g for g in gaps if g >= 0.0])
        median_gap = positive_gaps[len(positive_gaps) // 2] if positive_gaps else 0.0
        avg_width = sum(widths) / len(widths) if widths else 10.0
        gap_threshold = max(median_gap * 2.0, avg_width * 2.0)

        groups: List[str] = []
        current = ""
        prev_x2 = None

        for ch, x1, x2 in tokens:
            is_punctuation = ch in [',', ':']

            if prev_x2 is not None:
                gap = x1 - prev_x2
                if gap > gap_threshold and current:
                    groups.append(current)
                    current = ""

            if is_punctuation:
                if current:
                    groups.append(current)
                    current = ""
                prev_x2 = x2
                continue

            # If a minus sign appears immediately after digits, treat it as a
            # new numeric group start (e.g. "-1168-6592" -> "-1168", "-6592").
            # This is constrained to continuity grouping and still guarded later
            # by timestamp/noise checks in Path B.
            if ch == '-' and current and current[-1].isdigit():
                groups.append(current)
                current = '-'
                prev_x2 = x2
                continue

            if ch.isdigit() or ch == '-':
                current += ch

            prev_x2 = x2

        if current:
            groups.append(current)

        # Merge standalone '-' with next numeric group
        merged: List[str] = []
        i = 0
        while i < len(groups):
            if groups[i] == '-' and i + 1 < len(groups) and re.fullmatch(r'\d{1,7}', groups[i + 1]):
                merged.append('-' + groups[i + 1])
                i += 2
                continue
            merged.append(groups[i])
            i += 1

        avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
        return merged, avg_conf

    def _truncate_groups_before_timestamp(self, groups: List[str]) -> List[str]:
        """Drop groups from first timestamp-like year segment onward.

        If a group contains embedded year marker (e.g. '-66023952026-02-0721'),
        keep numeric prefix before year marker and truncate the rest.
        """
        current_year = str(datetime.datetime.now().year)
        for idx, g in enumerate(groups):
            m = re.search(re.escape(current_year), g)
            if not m:
                continue

            head = g[:m.start()].strip()
            kept = list(groups[:idx])
            if re.fullmatch(r'-?\d{1,7}', head):
                kept.append(head)
            return kept
        return groups

    def _extract_xyz_from_numeric_groups(self, groups: List[str]) -> Optional[Tuple[int, int, int]]:
        """From numeric group stream, choose best valid coordinate triplet."""
        numeric: List[str] = []
        for g in groups:
            if re.fullmatch(r'-?\d{1,7}', g):
                numeric.append(g)
                continue

            # Compact merge pattern: "-1168-6592" -> ["-1168", "-6592"]
            m = re.fullmatch(r'(-?\d{1,7})-(\d{1,7})', g)
            if m:
                numeric.append(m.group(1))
                numeric.append(f"-{m.group(2)}")

        if len(numeric) < 3:
            # Compact merge pattern: ["-1168", "-6592395"] -> (-1168, -6592, 395)
            if len(numeric) == 2:
                x_text, yz_text = numeric[0], numeric[1]
                sign = '-' if yz_text.startswith('-') else ''
                yz_digits = yz_text[1:] if sign else yz_text
                if yz_digits.isdigit() and 4 <= len(yz_digits) <= 7:
                    split_pairs: List[Tuple[str, str]] = []
                    # Prefer z=3 first, then 2/4 as fallback
                    for z_len in (3, 2, 4):
                        y_len = len(yz_digits) - z_len
                        if y_len < 1 or y_len > 7:
                            continue
                        y_text = f"{sign}{yz_digits[:y_len]}"
                        z_text = yz_digits[y_len:]
                        split_pairs.append((y_text, z_text))

                    candidate_xyz: List[Tuple[int, int, int]] = []
                    try:
                        x_val = int(x_text)
                    except Exception:
                        x_val = None

                    if x_val is not None:
                        for y_text, z_text in split_pairs:
                            try:
                                y_val = int(y_text)
                                z_val = int(z_text)
                            except Exception:
                                continue
                            if all(abs(c) <= 9999999 for c in (x_val, y_val, z_val)):
                                candidate_xyz.append((x_val, y_val, z_val))

                    if candidate_xyz:
                        return self._choose_best_xyz_candidate(candidate_xyz)

            return None

        triplet_candidates: List[Tuple[int, int, int]] = []
        for i in range(0, len(numeric) - 2):
            x, y, z = int(numeric[i]), int(numeric[i + 1]), int(numeric[i + 2])
            if all(abs(c) <= 9999999 for c in (x, y, z)):
                triplet_candidates.append((x, y, z))

        if not triplet_candidates:
            return None
        return self._choose_best_xyz_candidate(triplet_candidates)

    def _choose_best_xyz_candidate(self, candidates: List[Tuple[int, int, int]]) -> Optional[Tuple[int, int, int]]:
        """Choose most plausible xyz deterministically (history-aware when available)."""
        if not candidates:
            return None

        unique_candidates = list(dict.fromkeys(candidates))

        last = self.last_valid_coord
        if last is not None:
            def _dist(c: Tuple[int, int, int]) -> float:
                dx = c[0] - last[0]
                dy = c[1] - last[1]
                dz = c[2] - last[2]
                return math.sqrt(dx * dx + dy * dy + dz * dz)

            return sorted(
                unique_candidates,
                key=lambda c: (
                    _dist(c),
                    -self._score_xyz_without_history(c),
                    abs(c[2]),
                    c,
                )
            )[0]

        return sorted(
            unique_candidates,
            key=lambda c: (
                -self._score_xyz_without_history(c),
                abs(c[2]),
                c,
            )
        )[0]

    def _score_xyz_without_history(self, xyz: Tuple[int, int, int]) -> float:
        """Heuristic score used when no trajectory history is available."""
        x, y, z = xyz
        lx = len(str(abs(x)))
        ly = len(str(abs(y)))
        lz = len(str(abs(z)))

        score = 0.0
        if 3 <= lx <= 5:
            score += 2.0
        elif lx in (2, 6):
            score += 0.8

        if 3 <= ly <= 5:
            score += 2.0
        elif ly in (2, 6):
            score += 0.8

        if 1 <= lz <= 4:
            score += 1.5
        elif lz in (5,):
            score += 0.5

        score -= abs(lx - ly) * 0.6
        score -= max(0, lx - 6) * 0.7
        score -= max(0, ly - 6) * 0.7
        score -= max(0, lz - 5) * 0.6
        return score

    def _generate_xy_candidates_from_compact_group(self, compact_xy: str) -> List[Tuple[str, str]]:
        """Split compact x+y group into candidate (x_text, y_text) pairs."""
        text = compact_xy.strip()
        if not re.fullmatch(r'-?\d{2,14}', text):
            return []

        sign = '-' if text.startswith('-') else ''
        digits = text[1:] if sign else text
        if len(digits) < 2:
            return []

        pairs: List[Tuple[str, str]] = []
        for split_idx in range(1, len(digits)):
            left = digits[:split_idx]
            right = digits[split_idx:]
            if not (1 <= len(left) <= 7 and 1 <= len(right) <= 7):
                continue
            x_text = f"{sign}{left}"
            y_text = right
            pairs.append((x_text, y_text))

        return pairs

    def _recover_xyz_from_two_groups(
        self,
        groups: List[str],
        allow_compact_yz: bool = True,
        allow_compact_xy: bool = True,
    ) -> Optional[Tuple[int, int, int]]:
        """Recover xyz from two groups, supporting compact XY and compact YZ patterns."""
        if len(groups) != 2:
            return None

        g1, g2 = groups[0], groups[1]
        candidates: List[Tuple[int, int, int]] = []

        # Pattern A: compact YZ, existing behavior generalized
        if allow_compact_yz and re.fullmatch(r'-?\d{1,7}', g1):
            sign = '-' if g2.startswith('-') else ''
            yz_digits = g2[1:] if sign else g2
            if yz_digits.isdigit() and 4 <= len(yz_digits) <= 7:
                try:
                    x_val = int(g1)
                except Exception:
                    x_val = None

                if x_val is not None:
                    for z_len in (3, 2, 4, 1):
                        y_len = len(yz_digits) - z_len
                        if not (1 <= y_len <= 7):
                            continue
                        y_text = f"{sign}{yz_digits[:y_len]}"
                        z_text = yz_digits[y_len:]
                        try:
                            y_val = int(y_text)
                            z_val = int(z_text)
                        except Exception:
                            continue
                        if all(abs(c) <= 9999999 for c in (x_val, y_val, z_val)):
                            candidates.append((x_val, y_val, z_val))

        # Pattern B: compact XY + explicit Z (key missing-comma rescue)
        # Require compact XY group to be long enough to avoid mis-parsing
        # normal two-value input like "-500,100".
        if allow_compact_xy and re.fullmatch(r'-?\d{1,7}', g2):
            g1_digits = g1[1:] if g1.startswith('-') else g1
            if not (g1_digits.isdigit() and 6 <= len(g1_digits) <= 14):
                return self._choose_best_xyz_candidate(candidates)
            xy_pairs = self._generate_xy_candidates_from_compact_group(g1)
            try:
                z_val = int(g2)
            except Exception:
                z_val = None

            if z_val is not None:
                for x_text, y_text in xy_pairs:
                    try:
                        x_val = int(x_text)
                        y_val = int(y_text)
                    except Exception:
                        continue
                    if all(abs(c) <= 9999999 for c in (x_val, y_val, z_val)):
                        candidates.append((x_val, y_val, z_val))

        return self._choose_best_xyz_candidate(candidates)

    def _is_time_contaminated_triplet(self, xyz: Tuple[int, int, int]) -> bool:
        """Conservative guard: reject triplets that strongly resemble HH:MM(:SS) fragments."""
        vals = [abs(v) for v in xyz]
        within_59 = sum(1 for v in vals if v <= 59)
        within_23 = any(v <= 23 for v in vals)
        return within_59 >= 2 and within_23

    def _is_safe_timestamp_noise_compact_yz_candidate(self, xyz: Tuple[int, int, int]) -> bool:
        """Extra guard for compact-yz recovery under timestamp noise.

        When timestamp text contaminates the OCR string, two-group recovery (x, yz)
        can accidentally absorb HH:MM:SS fragments into yz. This helper keeps the
        recovery conservative by requiring trajectory history and a reasonable
        delta from the last stable coordinate.
        """
        if self.last_valid_coord is None:
            return False

        last_x, last_y, last_z = self.last_valid_coord
        x, y, z = xyz

        dx = x - last_x
        dy = y - last_y
        dz = z - last_z
        horizontal_distance = math.sqrt(dx * dx + dy * dy)

        # Stay within normal movement thresholds; don't accept teleports from
        # this recovery mode because it's the most error-prone.
        if horizontal_distance > float(self.max_speed_threshold):
            return False
        if abs(dz) > float(self.z_axis_threshold):
            return False

        return True

    def _parse_path_b_spacing_dominant(self, detections: List[Dict[str, Any]]) -> Tuple[bool, Optional[Tuple[int, int, int]], Dict[str, Any]]:
        """
        Path B: continuity-group parsing fallback.
        No fixed 3-block split; groups are built from x-gap continuity.
        """
        metadata: Dict[str, Any] = {
            'avg_confidence': 0.0,
            'complete': False,
            'method': 'path_b'
        }

        try:
            if not detections:
                return False, None, metadata

            sorted_detections = sorted(detections, key=lambda d: d['bbox'][0])
            chars: List[str] = []
            for d in sorted_detections:
                ch = OCRWorker._class_id_to_char_static(d['class'])
                if ch:
                    chars.append(ch)

            if not chars:
                return False, None, metadata

            groups, avg_conf = self._group_contiguous_tokens(detections)
            metadata['avg_confidence'] = avg_conf
            metadata['groups'] = list(groups)

            raw_str = "".join(chars)
            metadata['raw_text_before_cleanup'] = raw_str
            raw_str = self._remove_timestamp_from_coord_string(raw_str)
            metadata['raw_text'] = raw_str

            # Fast path: punctuation-complete text
            punct_match = re.match(r'^\s*(-?\d{1,7}),(-?\d{1,7}),(-?\d{1,7})\s*$', raw_str.strip())
            if punct_match:
                x, y, z = int(punct_match.group(1)), int(punct_match.group(2)), int(punct_match.group(3))
                if all(abs(c) <= 9999999 for c in (x, y, z)):
                    metadata['complete'] = True
                    metadata['method'] = 'path_b'
                    return True, (x, y, z), metadata

            # Continuity-group parse (non-fixed group count)
            trimmed_groups = self._truncate_groups_before_timestamp(groups)
            metadata['trimmed_groups'] = list(trimmed_groups)
            current_year = str(datetime.datetime.now().year)
            metadata['timestamp_noise_detected'] = bool(re.search(re.escape(current_year), ''.join(groups)))
            metadata['has_time_like_segment'] = bool(re.search(r'\d{1,2}:\d{1,2}', ''.join(chars)))

            timestamp_noise = bool(metadata['timestamp_noise_detected'])

            # Guard: with timestamp noise, allow only {2,3} groups for compact recovery;
            # reject wider residual group streams to avoid taking HH/MM/SS fragments.
            if timestamp_noise and len(trimmed_groups) not in (2, 3):
                metadata['method'] = 'path_b_groups_reject_timestamp_noise'
                return False, None, metadata

            # Under timestamp noise, two-group compact-YZ recovery is risky.
            # However, when we have a stable trajectory history, allow it and
            # validate against last_valid_coord to prevent time-fragment leakage.
            allow_compact_yz_under_timestamp_noise = (
                timestamp_noise
                and len(trimmed_groups) == 2
                and self.last_valid_coord is not None
            )

            if timestamp_noise and len(trimmed_groups) == 2 and not allow_compact_yz_under_timestamp_noise:
                xyz = None
            else:
                xyz = self._extract_xyz_from_numeric_groups(trimmed_groups)

            if xyz is None and len(trimmed_groups) == 2:
                if timestamp_noise and self.last_valid_coord is None:
                    metadata['method'] = 'path_b_groups_reject_timestamp_noise'
                    return False, None, metadata

                xyz = self._recover_xyz_from_two_groups(
                    trimmed_groups,
                    allow_compact_yz=(not timestamp_noise) or allow_compact_yz_under_timestamp_noise,
                    allow_compact_xy=True,
                )
                if xyz is not None:
                    metadata['recovered_from_two_groups'] = True

            if xyz is not None and allow_compact_yz_under_timestamp_noise:
                metadata['recovered_compact_yz_under_timestamp_noise'] = True
                if not self._is_safe_timestamp_noise_compact_yz_candidate(xyz):
                    metadata['method'] = 'path_b_groups_reject_timestamp_noise'
                    return False, None, metadata

            if xyz is not None:
                # Additional guard for obvious time-like contamination.
                if metadata['has_time_like_segment'] and self._is_time_contaminated_triplet(xyz):
                    metadata['method'] = 'path_b_groups_reject_time_contaminated_triplet'
                    return False, None, metadata
                metadata['complete'] = True
                metadata['method'] = 'path_b_groups'
                return True, xyz, metadata

            # Fallback regex parse (space-separated)
            metadata['method'] = 'path_b_fallback'
            fallback_text = re.sub(r'[,:\t]+', ' ', raw_str)
            fallback_text = re.sub(r'\s+', ' ', fallback_text).strip()
            metadata['fallback_text'] = fallback_text

            if re.search(r'(?<!\d)-?\d{8,}(?!\d)', fallback_text):
                return False, None, metadata

            m = re.match(r'^\s*(-?\d{1,7})\s+(-?\d{1,7})\s+(-?\d{1,7})\s*$', fallback_text)
            if m:
                x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if all(abs(c) <= 9999999 for c in (x, y, z)):
                    metadata['complete'] = True
                    return True, (x, y, z), metadata

            return False, None, metadata
        except Exception as e:
            self.logger.debug(f"[PATH_B] 解析失败: {e}")
            return False, None, metadata

    def _is_near(
        self,
        coord1: Tuple[int, int, int],
        coord2: Tuple[int, int, int],
        tolerance: int = 100
    ) -> bool:
        dx = coord1[0] - coord2[0]
        dy = coord1[1] - coord2[1]
        dz = coord1[2] - coord2[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        return dist <= tolerance

    def _process_suspect_jump(self, candidate_coord: Tuple[int, int, int]) -> Optional[Tuple[int, int, int]]:
        """
        Two-stage suspect confirmation:
        - Frame N: record suspect, return None
        - Frame N+1: confirm if near suspect, else reject to stable coord
        """
        if self.last_valid_coord is None:
            return candidate_coord

        if self.suspect_jump is None:
            self.suspect_jump = {
                'coord': candidate_coord,
                'count': 1,
                'stable_coord': self.last_valid_coord
            }
            return None

        suspect_coord = self.suspect_jump['coord']
        if self._is_near(candidate_coord, suspect_coord, tolerance=100):
            self.suspect_jump['count'] += 1
            if self.suspect_jump['count'] >= self.suspect_confirmation_window:
                confirmed = suspect_coord
                self.suspect_jump = None
                return confirmed
            return None

        # reject: keep stable
        stable = self.suspect_jump['stable_coord']
        self.suspect_jump = None
        return stable

    def _reset_suspect_on_failure(self) -> Optional[Tuple[int, int, int]]:
        """Reset suspect buffer on failure/no-data and return stable coordinate if any."""
        if self.suspect_jump is None:
            return None
        stable = self.suspect_jump.get('stable_coord')
        self.suspect_jump = None
        return stable

    def _update_last_successful_bbox(self, detections: List[Dict[str, Any]]) -> None:
        if not detections:
            return
        try:
            x_min = min(float(d['bbox'][0]) for d in detections)
            y_min = min(float(d['bbox'][1]) for d in detections)
            x_max = max(float(d['bbox'][2]) for d in detections)
            y_max = max(float(d['bbox'][3]) for d in detections)
            self.last_successful_bbox = {
                'x': int(x_min),
                'y': int(y_min),
                'width': int(max(0.0, x_max - x_min)),
                'height': int(max(0.0, y_max - y_min)),
            }
            if isinstance(self.capture_area, dict):
                origin_x = int(self.capture_area.get('x', 0) or 0)
                origin_y = int(self.capture_area.get('y', 0) or 0)
                center_x = origin_x + int(self.last_successful_bbox['x'] + self.last_successful_bbox['width'] / 2)
                center_y = origin_y + int(self.last_successful_bbox['y'] + self.last_successful_bbox['height'] / 2)
                self.dynamic_roi_anchor_center_global = (center_x, center_y)
            self.logger.debug(f"[DYNAMIC_ROI] Updated successful bbox: {self.last_successful_bbox}")
        except Exception:
            return

    def _shrink_roi_to_detections(self) -> None:
        if not isinstance(self.capture_area, dict) or not self.last_successful_bbox:
            return

        old_w = int(self.capture_area.get('width', 0) or 0)
        old_h = int(self.capture_area.get('height', 0) or 0)
        margin = max(0, int(self.ROI_SHRINK_MARGIN))
        bbox = self.last_successful_bbox
        origin_x = int(self.capture_area.get('x', 0) or 0)
        origin_y = int(self.capture_area.get('y', 0) or 0)
        # bbox is ROI-local; convert to screen-global before updating capture area
        new_x = max(0, origin_x + int(bbox['x'] - margin))
        new_y = max(0, origin_y + int(bbox['y'] - margin))
        new_w = int(min(self.ROI_MAX_WIDTH, bbox['width'] + margin * 2))
        new_h = int(min(self.ROI_MAX_HEIGHT, bbox['height'] + margin * 2))

        # Clamp to minimum ROI size only when source ROI is already at/above that scale.
        # Never enlarge width during shrink for small base ROIs.
        if old_w >= int(self.ROI_MIN_WIDTH):
            new_w = max(int(self.ROI_MIN_WIDTH), new_w)
        if old_h >= int(self.ROI_MIN_HEIGHT):
            new_h = max(int(self.ROI_MIN_HEIGHT), new_h)

        if self.dynamic_roi_base_area is None:
            self.dynamic_roi_base_area = dict(self.capture_area)
        self.capture_area.update({'x': new_x, 'y': new_y, 'width': new_w, 'height': new_h})
        self.dynamic_roi_active = True
        self.dynamic_failure_count = 0
        self._emit_capture_area_updated()
        self.logger.info(
            f"[DYNAMIC_ROI] ✓ ROI shrunk from {old_w}x{old_h} to {new_w}x{new_h} at ({new_x}, {new_y})"
        )

    def _expand_roi_on_failure(self) -> None:
        if not isinstance(self.capture_area, dict) or not self.last_successful_bbox:
            return

        old_w = int(self.capture_area['width'])
        old_h = int(self.capture_area['height'])
        origin_x = int(self.capture_area.get('x', 0) or 0)
        origin_y = int(self.capture_area.get('y', 0) or 0)

        new_w = min(self.ROI_MAX_WIDTH, old_w + self.ROI_EXPAND_PIXELS * 2)
        new_h = min(self.ROI_MAX_HEIGHT, old_h + self.ROI_EXPAND_PIXELS * 2)

        if self.dynamic_roi_anchor_center_global is not None:
            center_x, center_y = self.dynamic_roi_anchor_center_global
        else:
            # fallback: last_successful_bbox is ROI-local; convert center to screen-global
            center_x = origin_x + int(self.last_successful_bbox['x'] + self.last_successful_bbox['width'] / 2)
            center_y = origin_y + int(self.last_successful_bbox['y'] + self.last_successful_bbox['height'] / 2)
        new_x = max(0, center_x - new_w // 2)
        new_y = max(0, center_y - new_h // 2)

        self.capture_area.update({'x': int(new_x), 'y': int(new_y), 'width': int(new_w), 'height': int(new_h)})
        self._emit_capture_area_updated()
        self.logger.info(
            f"[DYNAMIC_ROI] ⚠ ROI expanded from {old_w}x{old_h} to {new_w}x{new_h} at ({new_x}, {new_y})"
        )

    def _reset_dynamic_roi_to_base(self) -> None:
        if isinstance(self.dynamic_roi_base_area, dict):
            self.capture_area = dict(self.dynamic_roi_base_area)
            self._emit_capture_area_updated()
            self.logger.warning(
                f"[DYNAMIC_ROI] ↩ rollback to base area after {self.dynamic_failure_count} failures: {self.capture_area}"
            )

        self.dynamic_roi_active = False
        self.dynamic_failure_count = 0
        self.consecutive_success_count = 0
        self.last_successful_bbox = None
        self.dynamic_roi_anchor_center_global = None

    def _on_dynamic_roi_failure(self) -> None:
        if not self.dynamic_roi_active:
            self.consecutive_success_count = 0
            return

        self.dynamic_failure_count += 1
        if self.dynamic_failure_count >= self.ROI_MAX_FAILURES_BEFORE_RESET:
            self._reset_dynamic_roi_to_base()
            return

        self._expand_roi_on_failure()
        self.consecutive_success_count = 0
    
    @staticmethod
    def _class_id_to_char_static(class_id: int) -> str | None:
        try:
            if 0 <= class_id < len(OCRWorker._class_names_static):
                return OCRWorker._class_names_static[class_id]
            return None
        except:
            return None
    
    def _load_class_names(self) -> List[str]:
        """
        Load class names from models/class_names.txt
        
        Returns:
            List of class names where index corresponds to class ID
        """
        try:
            class_names_path = Path("models/class_names.txt")
            
            if not class_names_path.exists():
                self.logger.error(f"类别名称文件不存在: {class_names_path}")
                # Fallback to hardcoded mapping
                class_names = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ',', ':', '-']
                OCRWorker._class_names_static = class_names
                return class_names
            
            with open(class_names_path, 'r', encoding='utf-8') as f:
                class_names = [line.strip() for line in f.readlines() if line.strip()]
            
            self.logger.info(f"成功加载类别名称: {len(class_names)} 个类别")
            OCRWorker._class_names_static = class_names
            return class_names
            
        except Exception as e:
            self.logger.error(f"加载类别名称失败: {e}")
            # Fallback to hardcoded mapping
            class_names = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ',', ':', '-', '+']
            OCRWorker._class_names_static = class_names
            return class_names
    
    def load_model(self, model_path=None) -> bool:
        """Load ONNX coordinate recognition model."""
        try:
            if model_path is None:
                model_path = self.config_dict.get('model_path', "models/coord_ocr.onnx")
            
            model_path = Path(model_path)
            
            if not model_path.exists():
                error_msg = f"模型文件不存在: {model_path}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False

            self.model = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
            inputs = self.model.get_inputs()
            if not inputs:
                raise ValueError("ONNX model has no inputs")
            self.model_input_name = inputs[0].name
            shape = inputs[0].shape
            if len(shape) >= 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
                self.model_input_shape = (shape[2], shape[3])

            self.logger.info(f"ONNX OCR模型加载成功: {model_path}")
            return True
            
        except Exception as e:
            error_msg = f"模型加载失败: {e}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            return False
    
    def load_settings(self):
        """Load settings from configuration dictionary"""
        config = self.config_dict
        
        # Load OCR capture area
        ocr_area = config.get('ocr_capture_area', {})
        self.capture_area = {
            'x': ocr_area.get('x', 100),
            'y': ocr_area.get('y', 100),
            'width': ocr_area.get('width', 200),
            'height': ocr_area.get('height', 50)
        }
        self._emit_capture_area_updated()
        
        # Load OCR interval
        self.ocr_interval = config.get('ocr_interval', 1000)
        
        # Load target window name (if using window-specific capture)
        self.target_window_name = config.get('target_window_name', '')
        
        self.logger.info(f"OCR设置加载完成: 区域{self.capture_area}, 间隔{self.ocr_interval}ms")
    
    def start_recognition(self):
        """Start the OCR recognition process"""
        if not self.is_running:
            self.should_stop = False
            self.start()
            self.logger.info("OCR识别启动")
    
    def stop_recognition(self) -> bool:
        """Stop the OCR recognition process"""
        if not self.is_running and not self.isRunning():
            return True

        self.should_stop = True
        stopped = self.wait(5000)  # Wait up to 5 seconds for thread to finish
        if stopped:
            self.is_running = False
            self.logger.info("OCR识别停止")
            return True

        self.logger.error("OCR识别停止超时，工作线程仍在运行")
        return False
    
    def update_confidence_threshold(self, threshold: float):
        """Update confidence threshold dynamically"""
        self.confidence_threshold = threshold
        self.logger.info(f"置信率阈值已更新为: {threshold:.2f}")

    def update_confidence_thresholds(self, digit_threshold: float, symbol_threshold: float):
        """Update digit/symbol confidence thresholds dynamically."""
        self.digit_confidence_threshold = float(digit_threshold)
        self.symbol_confidence_threshold = float(symbol_threshold)
        self.logger.info(
            f"识别阈值已更新: 数字={self.digit_confidence_threshold:.2f}, 符号={self.symbol_confidence_threshold:.2f}"
        )

    def update_screenshot_mode(self, screenshot_mode: str):
        """Update screenshot mode dynamically."""
        self.config_dict['screenshot_mode'] = screenshot_mode
        self.logger.info(f"截图方式已更新为: {screenshot_mode}")

    def _get_confidence_threshold_for_class(self, class_id: int) -> float:
        ch = OCRWorker._class_id_to_char_static(class_id)
        if ch is None:
            return float(self.confidence_threshold)
        if ch.isdigit():
            return float(self.digit_confidence_threshold)
        if ch in [',', ':', '-']:
            return float(self.symbol_confidence_threshold)
        return float(self.confidence_threshold)
    
    def update_interval(self, interval: int):
        """Update OCR recognition interval dynamically"""
        self.ocr_interval = interval
        self.logger.info(f"OCR识别间隔已更新为: {interval}ms")
    
    def get_current_state(self) -> str:
        """Get current recognition state"""
        return self.recognition_state
    
    def update_advanced_parameters(self, params: Dict[str, Any]):
        """Update advanced OCR parameters dynamically"""
        try:
            if 'confidence_threshold' in params:
                self.confidence_threshold = params['confidence_threshold']
            
            if 'max_speed_threshold' in params:
                self.max_speed_threshold = params['max_speed_threshold']
            
            if 'ema_alpha' in params:
                self.ema_alpha = params['ema_alpha']
            
            if 'lost_threshold_frames' in params:
                self.lost_threshold_frames = params['lost_threshold_frames']
            
            if 'z_axis_threshold' in params:
                self.z_axis_threshold = params['z_axis_threshold']
            
            self.logger.info(f"高级OCR参数已更新: {params}")
            
        except Exception as e:
            self.logger.error(f"更新高级OCR参数失败: {e}")
    
    def run(self):
        """Main thread execution loop"""
        self.is_running = True
        
        # Load model and settings
        if not self.load_model():
            self.ocr_output_updated.emit("❌ 模型加载失败，请检查models/coord_ocr.onnx文件")
            self.error_occurred.emit("OCR模型加载失败")
            self.is_running = False
            return
        
        self.load_settings()
        
        # Reset state
        self.recognition_state = RecognitionState.SEARCHING
        self.last_valid_coord = None
        self.last_valid_detections = None
        self.consecutive_failures = 0
        self.suspect_jump = None
        self.consecutive_success_count = 0
        self.last_successful_bbox = None
        self.dynamic_roi_active = False
        self.dynamic_failure_count = 0
        self.dynamic_roi_base_area = None
        self.dynamic_roi_anchor_center_global = None
        
        # Emit initial state
        self.recognition_state_changed.emit(self.recognition_state)
        
        # 发射启动信息
        self.ocr_output_updated.emit("🚀 OCR识别已启动，正在搜索坐标...")
        
        self.logger.info("OCR识别循环开始")
        
        while not self.should_stop:
            try:
                frame_start_time = time.time()
                
                # 截图
                screenshot = self._capture_ocr_region()
                if screenshot is None:
                    self.ocr_output_updated.emit("⚠ 截图失败，请检查OCR区域设置")
                    self.msleep(self.ocr_interval)
                    continue
                
                # 模型推理
                detections = self._run_yolo_inference(screenshot)
                
                # 应用跟踪算法
                success, final_coords = self._apply_tracking_algorithm(detections)

                # Dynamic ROI: conditional activation with progressive shrinking/expansion
                if self.config_dict.get('auto_detect_region_enabled', True):
                    if success and final_coords is not None:
                        self._update_last_successful_bbox(detections)
                        self.consecutive_success_count += 1
                        self.dynamic_failure_count = 0

                        if self.consecutive_success_count >= self.ROI_TRIGGER_FRAMES:
                            self._shrink_roi_to_detections()
                            self.consecutive_success_count = 0
                    else:
                        self._on_dynamic_roi_failure()
                
                # Calculate sleep time to maintain consistent interval
                processing_time = (time.time() - frame_start_time) * 1000
                sleep_time = max(0, self.ocr_interval - processing_time)
                self.msleep(int(sleep_time))
                
            except Exception as e:
                error_msg = f"OCR识别过程出错: {e}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                self.msleep(self.ocr_interval)
        
        self.is_running = False
        self.logger.info("OCR识别循环结束")
    
    def _capture_ocr_region(self) -> Optional[npt.NDArray[np.uint8]]:
        """Capture the OCR region from screen"""
        try:
            if self.capture_callback is None:
                self.logger.error("No capture callback provided")
                return None

            if not isinstance(self.capture_area, dict):
                self.logger.error("No capture area configured")
                return None
            
            # Get screenshot mode from config (optional)
            config = self.config_dict
            screenshot_mode = config.get('screenshot_mode', 'BitBlt')
            
            # Convert mode string to expected format
            if 'PrintWindow' in screenshot_mode:
                mode = 'PrintWindow'
            else:
                mode = 'BitBlt'
            
            # Use callback function to capture screen region
            screenshot = self.capture_callback(
                int(self.capture_area.get('x', 0) or 0),
                int(self.capture_area.get('y', 0) or 0),
                int(self.capture_area.get('width', 0) or 0),
                int(self.capture_area.get('height', 0) or 0),
                mode,
                self.target_window_name
            )
            
            return screenshot
            
        except Exception as e:
            self._capture_error_count += 1
            
            if self._capture_error_count % 10 == 1:
                self.logger.error(f"截图失败 (第{self._capture_error_count}次): {e}")
            
            return None
    
    def _run_yolo_inference(self, image: npt.NDArray[np.uint8]) -> List[Dict[str, Any]]:
        try:
            if self.model is None:
                self.logger.error("ONNX OCR model is not loaded")
                self._last_inference_debug = {
                    'roi': dict(self.capture_area) if isinstance(self.capture_area, dict) else None,
                    'total_boxes': 0,
                    'kept_boxes': 0,
                    'filtered_boxes': 0,
                    'entries': [],
                }
                return []

            input_tensor = self._prepare_onnx_input(image)
            outputs = self.model.run(None, {self.model_input_name: input_tensor})
            detections, debug = self._parse_onnx_output(outputs[0])
            self._last_inference_debug = {
                **debug,
                'roi': dict(self.capture_area) if isinstance(self.capture_area, dict) else None,
            }
            return detections
        except Exception as e:
            self.logger.error(f"ONNX OCR推理失败: {e}")
            self._last_inference_debug = {
                'roi': dict(self.capture_area) if isinstance(self.capture_area, dict) else None,
                'total_boxes': 0,
                'kept_boxes': 0,
                'filtered_boxes': 0,
                'entries': [],
            }
            return []

    def _prepare_onnx_input(self, image: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        target_h, target_w = self.model_input_shape
        source_h, source_w = image.shape[:2]
        self._last_onnx_source_shape = (int(source_h), int(source_w))
        scale = min(float(target_w) / float(source_w), float(target_h) / float(source_h))
        resized_w = int(round(source_w * scale))
        resized_h = int(round(source_h * scale))
        resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
        pad_x = float(target_w - resized_w) / 2.0
        pad_y = float(target_h - resized_h) / 2.0
        canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
        left = int(round(pad_x - 0.1))
        top = int(round(pad_y - 0.1))
        canvas[top:top + resized_h, left:left + resized_w] = resized
        self._last_onnx_scale = (1.0 / scale, 1.0 / scale)
        self._last_onnx_pad = (float(left), float(top))
        image = canvas
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = image_rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
        return np.expand_dims(tensor, axis=0)

    def _parse_onnx_output(self, output: npt.NDArray[np.float32]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        arr = np.asarray(output)
        if arr.ndim == 3:
            arr = arr[0]

        detections: List[Dict[str, Any]] = []
        debug_entries: List[Dict[str, Any]] = []
        total_boxes = 0
        kept_boxes = 0
        collect_debug = self._is_detailed_debug_enabled()

        for row in arr:
            if len(row) < 6:
                continue
            total_boxes += 1
            raw_x1, raw_y1, raw_x2, raw_y2, confidence, class_id_float = row[:6]
            confidence = float(confidence)
            class_id = int(round(float(class_id_float)))
            threshold = self._get_confidence_threshold_for_class(class_id)
            scale_x, scale_y = self._last_onnx_scale
            pad_x, pad_y = self._last_onnx_pad
            x1 = (float(raw_x1) - pad_x) * scale_x
            y1 = (float(raw_y1) - pad_y) * scale_y
            x2 = (float(raw_x2) - pad_x) * scale_x
            y2 = (float(raw_y2) - pad_y) * scale_y
            source_h, source_w = self._last_onnx_source_shape
            if source_h > 0 and source_w > 0:
                x1 = max(0.0, min(float(source_w), x1))
                x2 = max(0.0, min(float(source_w), x2))
                y1 = max(0.0, min(float(source_h), y1))
                y2 = max(0.0, min(float(source_h), y2))
            valid_box = (x2 - x1) >= 1.0 and (y2 - y1) >= 1.0
            kept = confidence >= threshold and valid_box

            if collect_debug and len(debug_entries) < 120:
                debug_entries.append({
                    'char': OCRWorker._class_id_to_char_static(class_id) or '?',
                    'class_id': class_id,
                    'confidence': confidence,
                    'threshold': threshold,
                    'x': x1,
                    'kept': kept,
                })

            if kept:
                kept_boxes += 1
                detections.append({
                    'class': class_id,
                    'bbox': np.array([x1, y1, x2, y2], dtype=np.float32),
                    'confidence': confidence,
                })

        return detections, {
            'total_boxes': total_boxes,
            'kept_boxes': kept_boxes,
            'filtered_boxes': max(0, total_boxes - kept_boxes),
            'entries': debug_entries,
        }
    
    def _apply_tracking_algorithm(self, raw_detections: List[Dict[str, Any]]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """
        重写的追踪算法：智能调试输出，支持简洁和详细两种模式
        """
        # 使用新的聚类算法
        candidate_clusters = cluster_detections_to_rich_clusters(raw_detections)
        best_cluster, selection_details = find_best_coordinate_cluster(candidate_clusters)
        self._last_candidate_clusters = candidate_clusters
        self._last_selection_details = selection_details
        
        detection_count = len(raw_detections)
        cluster_count = len(candidate_clusters)
        
        # 简洁模式：只显示关键信息
        debug_info = f"OCR [{self.recognition_state}]: {detection_count}字符 -> {cluster_count}聚类"
        
        if candidate_clusters:
            cluster_words = [f"'{cluster['word']}'" for cluster in candidate_clusters]
            debug_info += f" | {' '.join(cluster_words)}"
        
        if best_cluster:
            selected_word = best_cluster['word'].replace(" ", "").replace("\t", "")
            debug_info += f" -> '{selected_word}' ✓"
        else:
            debug_info += f" -> 无匹配 ✗"
        
        success_this_frame = False
        new_coords = None

        if self.recognition_state == RecognitionState.LOCKED:
            success_this_frame, new_coords = self._handle_locked_state(raw_detections, best_cluster)
        elif self.recognition_state in [RecognitionState.SEARCHING, RecognitionState.LOST]:
            success_this_frame, new_coords = self._handle_searching_state(raw_detections, best_cluster)

        # 最终状态更新与信号发射
        if success_this_frame and new_coords is not None:
            self.consecutive_failures = 0
            self.last_valid_coord = new_coords
            if self.recognition_state != RecognitionState.LOCKED:
                self._transition_to_locked()
            # 坐标去重：如果与上一个完全相同则跳过
            if hasattr(self, 'last_emitted_coord') and self.last_emitted_coord == new_coords:
                pass  # 跳过重复坐标
            else:
                self.coordinates_detected.emit(*new_coords)
                self.last_emitted_coord = new_coords
            # 发射成功的坐标结果
            final_output = f"✓ 坐标: ({new_coords[0]}, {new_coords[1]}, {new_coords[2]})"
            self.ocr_output_updated.emit(final_output)
        else:
            self.consecutive_failures += 1
            if self.recognition_state == RecognitionState.LOCKED and self.consecutive_failures >= self.lost_threshold_frames:
                self._transition_to_lost()
            # 根据调试模式发射对应的信息
            self.ocr_output_updated.emit(debug_info)
        
        return success_this_frame, new_coords
    
    def _handle_locked_state(self, raw_detections: List[Dict[str, Any]], best_cluster: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """处理LOCKED状态：仅Path B解析 + suspect jump确认"""
        best_detections = best_cluster.get('detections', []) if best_cluster else []
        path_b_result = self._parse_path_b_spacing_dominant(raw_detections)
        is_valid, parsed_coords, _ = path_b_result

        if is_valid and parsed_coords is not None:
            if self._is_teleport_jump(parsed_coords):
                suspect_result = self._process_suspect_jump(parsed_coords)
                if suspect_result is None:
                    self._emit_detailed_pipeline_log(
                        self.recognition_state,
                        raw_detections,
                        best_cluster,
                        path_b_result,
                        True if self.last_valid_coord is not None else False,
                        self.last_valid_coord,
                        note="suspect_pending",
                    )
                    if self.last_valid_coord is not None:
                        return True, self.last_valid_coord
                    return False, None

                self.last_valid_detections = best_detections
                self._emit_detailed_pipeline_log(
                    self.recognition_state,
                    raw_detections,
                    best_cluster,
                    path_b_result,
                    True,
                    suspect_result,
                    note="suspect_confirmed_or_rejected",
                )
                return True, suspect_result

            # Normal movement clears suspect state
            self.suspect_jump = None
            self.last_valid_detections = best_detections
            self._emit_detailed_pipeline_log(
                self.recognition_state,
                raw_detections,
                best_cluster,
                path_b_result,
                True,
                parsed_coords,
                note="normal",
            )
            return True, parsed_coords

        suspect_reset = self._reset_suspect_on_failure()
        if suspect_reset is not None:
            self._emit_detailed_pipeline_log(
                self.recognition_state,
                raw_detections,
                best_cluster,
                path_b_result,
                True,
                suspect_reset,
                note="suspect_reset_to_stable",
            )
            return True, suspect_reset

        self._emit_detailed_pipeline_log(
            self.recognition_state,
            raw_detections,
            best_cluster,
            path_b_result,
            False,
            None,
            note="path_b_failed",
        )

        return False, None

    def _handle_searching_state(self, raw_detections: List[Dict[str, Any]], best_cluster: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """处理SEARCHING/LOST状态：仅Path B解析（不做jump过滤）"""
        best_detections = best_cluster.get('detections', []) if best_cluster else []
        path_b_result = self._parse_path_b_spacing_dominant(raw_detections)
        is_valid, parsed_coords, _ = path_b_result

        if is_valid and parsed_coords is not None:
            self.last_valid_detections = best_detections
            self._emit_detailed_pipeline_log(
                self.recognition_state,
                raw_detections,
                best_cluster,
                path_b_result,
                True,
                parsed_coords,
                note="searching_or_lost",
            )
            return True, parsed_coords

        self._emit_detailed_pipeline_log(
            self.recognition_state,
            raw_detections,
            best_cluster,
            path_b_result,
            False,
            None,
            note="searching_or_lost_failed",
        )

        return False, None
    
    def _is_teleport_jump(self, coordinates: Tuple[int, int, int]) -> bool:
        """Check if coordinate change exceeds maximum speed threshold"""
        if not self.last_valid_coord:
            return False
        
        # Calculate differences
        dx = coordinates[0] - self.last_valid_coord[0]
        dy = coordinates[1] - self.last_valid_coord[1]
        dz = coordinates[2] - self.last_valid_coord[2]
        
        # Calculate 2D horizontal distance (X, Y only)
        horizontal_distance = math.sqrt(dx*dx + dy*dy)
        
        # Z轴(高度)异常检测
        if abs(dz) > self.z_axis_threshold:
            return True
        
        # 水平移动检测
        if horizontal_distance > self.max_speed_threshold:
            return True
        
        return False
    
    def _transition_to_locked(self):
        """Transition to LOCKED state"""
        if self.recognition_state != RecognitionState.LOCKED:
            self.recognition_state = RecognitionState.LOCKED
            self.recognition_state_changed.emit(RecognitionState.LOCKED)
            self.logger.info(f"[STATE_CHANGE] -> LOCKED")
    
    def _transition_to_lost(self):
        """Transition to LOST state"""
        if self.recognition_state != RecognitionState.LOST:
            self.recognition_state = RecognitionState.LOST
            self.recognition_state_changed.emit(RecognitionState.LOST)
            self.logger.warning(f"[STATE_CHANGE] -> LOST (连续失败: {self.consecutive_failures})")
    
    def _transition_to_searching(self):
        """Transition to SEARCHING state"""
        if self.recognition_state != RecognitionState.SEARCHING:
            self.recognition_state = RecognitionState.SEARCHING
            self.recognition_state_changed.emit(RecognitionState.SEARCHING)
            self.logger.info(f"[STATE_CHANGE] -> SEARCHING")
    
    def get_current_state(self) -> str:
        """Get current recognition state"""
        return self.recognition_state
    
    def get_last_coordinates(self) -> Optional[Tuple[int, int, int]]:
        """Get last valid coordinates"""
        return self.last_valid_coord
    
    def update_confidence_threshold(self, threshold: float):
        """Update confidence threshold dynamically"""
        self.confidence_threshold = threshold
        self.logger.info(f"置信率阈值已更新为: {threshold:.2f}")
    
    def update_interval(self, interval: int):
        """Update OCR recognition interval"""
        self.ocr_interval = interval
        self.logger.info(f"OCR识别间隔已更新为: {interval}ms")
    
    def update_advanced_parameters(self, params: Dict[str, Any]):
        """Update advanced OCR parameters dynamically"""
        try:
            if 'confidence_threshold' in params:
                self.confidence_threshold = params['confidence_threshold']
                self.logger.debug(f"置信度阈值更新为: {self.confidence_threshold}")

            if 'digit_confidence_threshold' in params:
                self.digit_confidence_threshold = float(params['digit_confidence_threshold'])
                self.logger.debug(f"数字置信度阈值更新为: {self.digit_confidence_threshold}")

            if 'symbol_confidence_threshold' in params:
                self.symbol_confidence_threshold = float(params['symbol_confidence_threshold'])
                self.logger.debug(f"符号置信度阈值更新为: {self.symbol_confidence_threshold}")
            
            if 'max_speed_threshold' in params:
                self.max_speed_threshold = params['max_speed_threshold']
                self.logger.debug(f"最大速度阈值更新为: {self.max_speed_threshold}")
            
            if 'ema_alpha' in params:
                self.ema_alpha = params['ema_alpha']
                self.logger.debug(f"EMA平滑因子更新为: {self.ema_alpha}")
            
            if 'lost_threshold_frames' in params:
                self.lost_threshold_frames = params['lost_threshold_frames']
                self.logger.debug(f"丢失阈值帧数更新为: {self.lost_threshold_frames}")
            
            if 'z_axis_threshold' in params:
                self.z_axis_threshold = params['z_axis_threshold']
                self.logger.debug(f"Z轴异常阈值更新为: {self.z_axis_threshold}")
            
            # 其他高级参数（这些参数在函数中动态读取）
            if 'char_spacing_threshold' in params:
                self.logger.debug(f"字符间距阈值设置为: {params['char_spacing_threshold']}")
            
            if 'smart_split_threshold' in params:
                self.logger.debug(f"智能分割阈值设置为: {params['smart_split_threshold']}")
            
            if 'verbose_diagnostics' in params:
                self.logger.debug(f"详细诊断设置为: {params['verbose_diagnostics']}")
            
            self.logger.info(f"高级OCR参数已更新: {list(params.keys())}")
            
        except Exception as e:
            self.logger.error(f"更新高级OCR参数失败: {e}")
    
    def update_capture_settings(self, capture_area: Dict[str, int], interval: int, window_name: str):
        """Update capture settings"""
        self.capture_area = capture_area
        self.dynamic_roi_base_area = dict(capture_area) if isinstance(capture_area, dict) else None
        self.dynamic_roi_anchor_center_global = None
        self.dynamic_failure_count = 0
        self.dynamic_roi_active = False
        self.last_successful_bbox = None
        self.consecutive_success_count = 0
        self.ocr_interval = interval
        self.target_window_name = window_name
        self._emit_capture_area_updated()
        self.logger.info(f"截图设置已更新: 区域{capture_area}, 间隔{interval}ms, 窗口'{window_name}'")
