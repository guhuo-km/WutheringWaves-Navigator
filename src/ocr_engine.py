#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR Engine for WutheringWaves Navigator
集成的OCR坐标识别引擎
"""

import time
import logging
import numpy as np
import cv2
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
import torch
from ultralytics import YOLO
import math
import re
import traceback
from PySide6.QtCore import QThread, Signal


def cluster_detections_to_rich_clusters(detections: list, gap_threshold: float = 0.5) -> list[dict]:
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




def find_best_coordinate_cluster(clusters: list[dict]) -> tuple[dict | None, list[dict]]:
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
    
    This worker runs YOLOv8 model on CPU and provides highly accurate coordinate
    tracking with state management and dynamic template adaptation.
    """
    
    # Static class names for global function access
    _CLASS_NAMES_STATIC = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ',', ':', '-']
    
    # Qt Signals
    coordinates_detected = Signal(int, int, int)  # x, y, z coordinates
    recognition_state_changed = Signal(str)  # LOCKED, LOST, SEARCHING
    error_occurred = Signal(str)  # Error message
    ocr_output_updated = Signal(str)  # Raw OCR output text
    
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
        
        # YOLOv8 model
        self.model = None
        
        # Class names mapping
        self.class_names = self._load_class_names()
        
        # Advanced tracking algorithm state variables
        self.recognition_state = RecognitionState.SEARCHING
        self.last_valid_coord = None  # (x, y, z) tuple
        self.last_valid_detections = None  # Dynamic tracking template
        self.consecutive_failures = 0
        
        # Configurable parameters (loaded from config dict)
        config = self.config_dict
        advanced_settings = config.get('advanced_ocr_settings', {})
        
        self.confidence_threshold = config.get('confidence_threshold', 0.45)
        self.max_speed_threshold = advanced_settings.get('max_speed_threshold', 1000)
        self.ema_alpha = advanced_settings.get('ema_alpha', 0.3)
        self.lost_threshold_frames = advanced_settings.get('lost_threshold_frames', 5)
        self.z_axis_threshold = advanced_settings.get('z_axis_threshold', 50)
        
        # OCR capture area and interval
        self.capture_area = None
        self.ocr_interval = 1000  # milliseconds
        self.target_window_name = ""  # Target window name for screenshot
        
        self.logger.info("OCR工作线程初始化完成")
    
    def set_capture_callback(self, capture_callback):
        """Set screen capture callback function
        
        Args:
            capture_callback: Function that captures screen region
                             Should accept: (x, y, width, height, mode, target_window_name)
                             Should return: numpy array of captured image or None if failed
        """
        self.capture_callback = capture_callback
    
    def _parse_and_validate_from_detections(self, detections: List[Dict]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """
        重写的坐标解析算法：简化解析逻辑，支持1-7位坐标
        从检测列表中精准提取xyz坐标值
        """
        try:
            if not detections:
                return False, None
            
            # 按x坐标排序并拼接字符串
            sorted_detections = sorted(detections, key=lambda d: d['bbox'][0])
            coord_str = "".join([OCRWorker._class_id_to_char_static(d['class']) or "" for d in sorted_detections])
            
            self.logger.debug(f"[COORD_PARSE] 原始字符串: '{coord_str}'")
            
            # 移除时间戳部分
            coord_str_cleaned = self._remove_timestamp_from_coord_string(coord_str)
            self.logger.debug(f"[COORD_PARSE] 清理后字符串: '{coord_str_cleaned}'")
            
            # 发射OCR输出信号
            self.ocr_output_updated.emit(f"识别结果: {coord_str_cleaned}")
            
            # 精准提取坐标：支持1-7位数字，可能为负数
            coord_pattern = re.compile(r'^(-?\d{1,7}),(-?\d{1,7}),(-?\d{1,7})')
            match = coord_pattern.match(coord_str_cleaned.strip())
            
            if match:
                try:
                    x, y, z = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    self.logger.debug(f"[COORD_PARSE] 提取坐标: ({x}, {y}, {z})")
                    
                    # 扩大范围验证：支持7位数字，范围±9999999
                    max_coord_value = 9999999
                    if all(abs(c) <= max_coord_value for c in [x, y, z]):
                        self.logger.debug(f"[COORD_PARSE] 坐标验证通过: ({x}, {y}, {z})")
                        parse_result = f"坐标: ({x}, {y}, {z})"
                        self.ocr_output_updated.emit(parse_result)
                        return True, (x, y, z)
                    else:
                        self.logger.debug(f"[COORD_PARSE] 坐标超出范围(±{max_coord_value}): ({x}, {y}, {z})")
                        self.ocr_output_updated.emit(f"坐标超出范围: ({x}, {y}, {z})")
                        
                except ValueError as e:
                    self.logger.debug(f"[COORD_PARSE] 数值转换失败: {e}")
                    self.ocr_output_updated.emit(f"数值转换错误: {coord_str_cleaned}")
            else:
                self.logger.debug(f"[COORD_PARSE] 正则匹配失败: '{coord_str_cleaned}'")
                self.ocr_output_updated.emit(f"格式不匹配: {coord_str_cleaned}")
                
        except Exception as e:
            self.logger.error(f"[COORD_PARSE] 解析异常: {e}")
            self.ocr_output_updated.emit(f"解析错误: {str(e)}")
            return False, None
            
        return False, None
    
    def _remove_timestamp_from_coord_string(self, coord_str: str) -> str:
        """
        精确的时间戳移除算法：只忽略202x-或203x-格式的时间戳
        用于避免误判z轴坐标（如z=20）为时间戳
        """
        self.logger.debug(f"[TIMESTAMP_REMOVAL] 输入字符串: '{coord_str}'")
        
        # 精确匹配时间戳格式：202x-或203x-（年份后必须跟破折号）
        # 这样可以区分z轴坐标20和时间戳2025-
        timestamp_pattern = re.compile(r'20[23]\d-')
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
        
        # 检查是否有单独的四位年份（没有破折号）在字符串末尾
        # 这种情况可能是年份信息，但不会误判z轴坐标
        year_only_pattern = re.compile(r'\s+20[23]\d$')
        if year_only_pattern.search(coord_str):
            result = year_only_pattern.sub('', coord_str).strip()
            self.logger.debug(f"[TIMESTAMP_REMOVAL] 移除末尾年份: '{result}'")
            return result
        
        # 如果没有找到时间戳标识，返回原字符串
        self.logger.debug(f"[TIMESTAMP_REMOVAL] 未找到时间戳标识，返回原字符串")
        return coord_str
    
    @staticmethod
    def _class_id_to_char_static(class_id: int) -> str | None:
        try:
            if 0 <= class_id < len(OCRWorker._CLASS_NAMES_STATIC):
                return OCRWorker._CLASS_NAMES_STATIC[class_id]
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
                OCRWorker._CLASS_NAMES_STATIC = class_names
                return class_names
            
            with open(class_names_path, 'r', encoding='utf-8') as f:
                class_names = [line.strip() for line in f.readlines() if line.strip()]
            
            self.logger.info(f"成功加载类别名称: {len(class_names)} 个类别")
            OCRWorker._CLASS_NAMES_STATIC = class_names
            return class_names
            
        except Exception as e:
            self.logger.error(f"加载类别名称失败: {e}")
            # Fallback to hardcoded mapping
            class_names = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ',', ':', '-']
            OCRWorker._CLASS_NAMES_STATIC = class_names
            return class_names
    
    def load_model(self, model_path=None) -> bool:
        """
        Load YOLOv8 coordinate recognition model
        
        Args:
            model_path: Path to the YOLO model file. If None, uses default or config value.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            if model_path is None:
                model_path = self.config_dict.get('model_path', "models/coord_ocr.pt")
            
            model_path = Path(model_path)
            
            if not model_path.exists():
                error_msg = f"模型文件不存在: {model_path}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return False
            
            # Load model and force CPU usage
            self.model = YOLO(str(model_path))
            self.model.to('cpu')  # Force CPU inference as specified
            
            self.logger.info(f"YOLOv8模型加载成功: {model_path}")
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
    
    def stop_recognition(self):
        """Stop the OCR recognition process"""
        if self.is_running:
            self.should_stop = True
            self.wait(5000)  # Wait up to 5 seconds for thread to finish
            self.logger.info("OCR识别停止")
    
    def update_confidence_threshold(self, threshold: float):
        """Update confidence threshold dynamically"""
        self.confidence_threshold = threshold
        self.logger.info(f"置信率阈值已更新为: {threshold:.2f}")
    
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
            self.ocr_output_updated.emit("❌ 模型加载失败，请检查models/coord_ocr.pt文件")
            self.error_occurred.emit("OCR模型加载失败")
            self.is_running = False
            return
        
        self.load_settings()
        
        # Reset state
        self.recognition_state = RecognitionState.SEARCHING
        self.last_valid_coord = None
        self.last_valid_detections = None
        self.consecutive_failures = 0
        
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
    
    def _capture_ocr_region(self) -> Optional[np.ndarray]:
        """Capture the OCR region from screen"""
        try:
            if self.capture_callback is None:
                self.logger.error("No capture callback provided")
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
                self.capture_area['x'],
                self.capture_area['y'],
                self.capture_area['width'],
                self.capture_area['height'],
                mode,
                self.target_window_name
            )
            
            return screenshot
            
        except Exception as e:
            if not hasattr(self, '_capture_error_count'):
                self._capture_error_count = 0
            self._capture_error_count += 1
            
            if self._capture_error_count % 10 == 1:
                self.logger.error(f"截图失败 (第{self._capture_error_count}次): {e}")
            
            return None
    
    def _run_yolo_inference(self, image: np.ndarray) -> List[Dict]:
        try:
            results = self.model(image, verbose=False)
            detections = []
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for i in range(len(boxes)):
                        confidence = float(boxes.conf[i])
                        if confidence >= self.confidence_threshold:
                            detections.append({
                                'class': int(boxes.cls[i]),
                                'bbox': boxes.xyxy[i].cpu().numpy(),
                                'confidence': confidence
                            })
            return detections
        except Exception as e:
            self.logger.error(f"YOLO推理失败: {e}")
            return []
    
    def _apply_tracking_algorithm(self, raw_detections: List[Dict]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """
        重写的追踪算法：智能调试输出，支持简洁和详细两种模式
        """
        # 使用新的聚类算法
        candidate_clusters = cluster_detections_to_rich_clusters(raw_detections)
        best_cluster, selection_details = find_best_coordinate_cluster(candidate_clusters)
        
        # 检查是否启用详细调试
        verbose_debug = self.config_dict.get('advanced_ocr_settings', {}).get('verbose_debug', False)
        
        detection_count = len(raw_detections)
        cluster_count = len(candidate_clusters)
        
        if verbose_debug:
            # 详细模式：完整的调试信息
            debug_info = f"=== 详细OCR调试 [{self.recognition_state}] ===\n"
            debug_info += f"原始检测: {detection_count}个字符\n"
            
            # 字符检测详情
            if raw_detections:
                char_details = []
                for i, det in enumerate(raw_detections):
                    char = self._class_id_to_char_static(det['class']) or '?'
                    conf = det['confidence']
                    x1, y1, x2, y2 = det['bbox']
                    char_details.append(f"'{char}'({conf:.2f}@{int(x1)})")
                debug_info += f"字符详情: {' '.join(char_details)}\n"
            
            # 聚类分析过程
            debug_info += f"\n智能聚类: {cluster_count}个聚类\n"
            for i, cluster in enumerate(candidate_clusters):
                word = cluster['word']
                detections_in_cluster = cluster.get('detections', [])
                debug_info += f"聚类{i+1}: '{word}' ({len(detections_in_cluster)}个字符)\n"
            
            # 坐标选择分析
            debug_info += f"\n坐标选择分析:\n"
            for detail in selection_details:
                word = detail['cleaned']
                matched = detail['matched']
                reason = detail['reason']
                status = "✓" if matched else "✗"
                debug_info += f"'{word}': {reason} {status}\n"
            
            # 选择结果
            if best_cluster:
                selected_word = best_cluster['word'].replace(" ", "").replace("\t", "")
                debug_info += f"\n最终选择: '{selected_word}' ✓"
            else:
                debug_info += f"\n最终选择: 无匹配坐标格式 ✗"
        else:
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
            success_this_frame, new_coords = self._handle_searching_state(best_cluster)

        # 最终状态更新与信号发射
        if success_this_frame and new_coords is not None:
            self.consecutive_failures = 0
            self.last_valid_coord = new_coords
            if self.recognition_state != RecognitionState.LOCKED:
                self._transition_to_locked()
            # 发射坐标信号
            self.coordinates_detected.emit(*new_coords)
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
    
    def _handle_locked_state(self, raw_detections: List[Dict], best_cluster: Optional[Dict]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """处理LOCKED状态：使用最佳坐标聚类进行解析"""
        if best_cluster:
            detections = best_cluster['detections']
            is_valid, parsed_coords = self._parse_and_validate_from_detections(detections)
            if is_valid and not self._is_teleport_jump(parsed_coords):
                self.last_valid_detections = detections  # 更新模板
                return True, parsed_coords
        
        return False, None
    
    def _handle_searching_state(self, best_cluster: Optional[Dict]) -> Tuple[bool, Optional[Tuple[int, int, int]]]:
        """处理SEARCHING/LOST状态：尝试从最佳聚类中提取坐标"""
        if best_cluster:
            detections = best_cluster['detections']
            is_valid, parsed_coords = self._parse_and_validate_from_detections(detections)
            if is_valid:
                self.last_valid_detections = detections # 初始化新模板
                return True, parsed_coords
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
        self.ocr_interval = interval
        self.target_window_name = window_name
        self.logger.info(f"截图设置已更新: 区域{capture_area}, 间隔{interval}ms, 窗口'{window_name}'")