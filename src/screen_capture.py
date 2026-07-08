#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Screen Capture Module for WutheringWaves Navigator
屏幕截图模块
"""

import os
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

import numpy as np
import win32gui
import win32ui
import win32con
import win32api
import win32process
from PIL import Image
import cv2
import logging


@dataclass(frozen=True)
class CapturedFrameRegion:
    frame: np.ndarray
    crop: np.ndarray
    origin: Tuple[int, int]
    source: str = "unknown"
    target_window_name: str = ""


def crop_image_region(image: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
    image_height, image_width = image.shape[:2]
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(image_width, left + max(0, int(width)))
    bottom = min(image_height, top + max(0, int(height)))
    return image[top:bottom, left:right].copy()


class ScreenCapture:
    """
    屏幕截图工具类
    支持多种截图模式和窗口检测
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _is_own_app_window(title: str, process_name: str) -> bool:
        """Exclude this navigator app window from game auto-detection."""
        title_norm = (title or "").lower().replace(" ", "")
        proc_norm = (process_name or "").lower().replace(" ", "")

        own_title_keywords = [
            "wutheringwaves-navigator",
            "wutheringwavesnavigator",
            "呜呜大地图",
            "navigator",
        ]
        own_process_keywords = [
            "wutheringwaves-navigator-smart.exe",
            "wutheringwaves-navigator.exe",
        ]

        if any(k in title_norm for k in own_title_keywords):
            return True
        if any(k in proc_norm for k in own_process_keywords):
            return True
        return False
    
    def capture_region(self, x: int, y: int, width: int, height: int, 
                      mode: str = 'BitBlt', target_window_name: str = '') -> Optional[np.ndarray]:
        """
        捕获指定区域的屏幕截图
        
        Args:
            x, y: 截图区域左上角坐标
            width, height: 截图区域尺寸
            mode: 截图模式 ('BitBlt' 或 'PrintWindow')
            target_window_name: 目标窗口名称（可选）
        
        Returns:
            numpy.ndarray: 截图图像，BGR格式，或None如果失败
        """
        result = self.capture_frame_and_region(x, y, width, height, mode, target_window_name)
        return result.crop if result is not None else None

    def capture_frame_and_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        mode: str = 'BitBlt',
        target_window_name: str = '',
    ) -> Optional[CapturedFrameRegion]:
        """Capture one shared frame and crop the requested OCR region from it."""
        try:
            if mode == 'PrintWindow' and target_window_name:
                frame_result = self._capture_window_frame(target_window_name)
                if frame_result is None:
                    crop = self._capture_window_region(x, y, width, height, target_window_name)
                    if crop is None:
                        return None
                    return CapturedFrameRegion(
                        frame=crop,
                        crop=crop,
                        origin=(int(x), int(y)),
                        source="fallback_region",
                        target_window_name=target_window_name,
                    )
                frame, window_rect = frame_result
                window_x, window_y, _, _ = window_rect
                crop = crop_image_region(frame, x - window_x, y - window_y, width, height)
                if crop.size == 0:
                    return None
                return CapturedFrameRegion(
                    frame=frame,
                    crop=crop,
                    origin=(int(window_x), int(window_y)),
                    source="window",
                    target_window_name=target_window_name,
                )

            frame_origin_x = 0
            frame_origin_y = 0
            if target_window_name:
                window_rect = self._find_window_rect_by_name(target_window_name)
                if window_rect is not None:
                    frame_origin_x, frame_origin_y, right, bottom = window_rect
                    frame = self._capture_screen_region(
                        frame_origin_x,
                        frame_origin_y,
                        right - frame_origin_x,
                        bottom - frame_origin_y,
                    )
                else:
                    frame = None
            else:
                screen_width, screen_height = self.get_screen_size()
                frame = self._capture_screen_region(0, 0, screen_width, screen_height)

            if frame is None:
                frame = self._capture_screen_region(x, y, width, height)
                if frame is None:
                    return None
                return CapturedFrameRegion(
                    frame=frame,
                    crop=frame,
                    origin=(int(x), int(y)),
                    source="fallback_region",
                    target_window_name=target_window_name,
                )
            crop = crop_image_region(frame, x - frame_origin_x, y - frame_origin_y, width, height)
            source = "window" if target_window_name else "fullscreen"
            return CapturedFrameRegion(
                frame=frame,
                crop=crop,
                origin=(frame_origin_x, frame_origin_y),
                source=source,
                target_window_name=target_window_name,
            )
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None
    
    def _capture_screen_region(self, x: int, y: int, width: int, height: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方式捕获屏幕区域
        """
        screen_dc = None
        mem_dc = None
        save_dc = None
        save_bitmap = None
        try:
            # 获取屏幕DC
            screen_dc = win32gui.GetDC(0)
            
            # 创建内存DC
            mem_dc = win32ui.CreateDCFromHandle(screen_dc)
            save_dc = mem_dc.CreateCompatibleDC()
            
            # 创建位图
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mem_dc, width, height)
            save_dc.SelectObject(save_bitmap)
            
            # 执行截图
            save_dc.BitBlt((0, 0), (width, height), mem_dc, (x, y), win32con.SRCCOPY)
            
            # 获取位图数据
            bmp_info = save_bitmap.GetInfo()
            bmp_str = save_bitmap.GetBitmapBits(True)
            
            # 转换为numpy数组
            image = np.frombuffer(bmp_str, dtype=np.uint8)
            image = image.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
            
            # 转换BGRA到BGR
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            return image
            
        except Exception as e:
            self.logger.error(f"BitBlt截图失败: {e}")
            return None
        finally:
            if save_bitmap is not None:
                try:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception:
                    pass
            if save_dc is not None:
                try:
                    save_dc.DeleteDC()
                except Exception:
                    pass
            if mem_dc is not None:
                try:
                    mem_dc.DeleteDC()
                except Exception:
                    pass
            if screen_dc is not None:
                try:
                    win32gui.ReleaseDC(0, screen_dc)
                except Exception:
                    pass
    
    def _capture_window_region(self, x: int, y: int, width: int, height: int, 
                              window_name: str) -> Optional[np.ndarray]:
        """
        使用PrintWindow方式捕获指定窗口的区域
        """
        hwnd = None
        window_dc = None
        mem_dc = None
        save_dc = None
        save_bitmap = None
        fallback_to_screen = False
        try:
            # 查找窗口
            hwnd = win32gui.FindWindow(None, window_name)
            if not hwnd:
                # 如果找不到完全匹配的窗口名，尝试部分匹配
                hwnd = self._find_window_partial(window_name)
                if not hwnd:
                    self.logger.warning(f"未找到窗口: {window_name}")
                    return self._capture_screen_region(x, y, width, height)  # 降级到屏幕截图
            
            # 获取窗口位置和大小
            window_rect = win32gui.GetWindowRect(hwnd)
            window_x, window_y, window_right, window_bottom = window_rect
            window_width = window_right - window_x
            window_height = window_bottom - window_y
            
            # 获取窗口DC
            window_dc = win32gui.GetWindowDC(hwnd)
            
            # 创建内存DC
            mem_dc = win32ui.CreateDCFromHandle(window_dc)
            save_dc = mem_dc.CreateCompatibleDC()
            
            # 创建位图
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mem_dc, window_width, window_height)
            save_dc.SelectObject(save_bitmap)
            
            # 使用PrintWindow截取整个窗口
            result = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)  # PW_RENDERFULLCONTENT
            
            if result:
                # 获取位图数据
                bmp_info = save_bitmap.GetInfo()
                bmp_str = save_bitmap.GetBitmapBits(True)
                
                # 转换为numpy数组
                image = np.frombuffer(bmp_str, dtype=np.uint8)
                image = image.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
                
                # 转换BGRA到BGR
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
                
                # 裁剪指定区域（需要转换坐标）
                # 将屏幕坐标转换为窗口坐标
                region_x = max(0, x - window_x)
                region_y = max(0, y - window_y)
                region_x2 = min(window_width, region_x + width)
                region_y2 = min(window_height, region_y + height)
                
                if region_x < region_x2 and region_y < region_y2:
                    cropped_image = image[region_y:region_y2, region_x:region_x2]

                    return cropped_image

            # 如果PrintWindow失败，降级到BitBlt
            fallback_to_screen = True
            
        except Exception as e:
            self.logger.error(f"PrintWindow截图失败: {e}")
            fallback_to_screen = True
        finally:
            if save_bitmap is not None:
                try:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception:
                    pass
            if save_dc is not None:
                try:
                    save_dc.DeleteDC()
                except Exception:
                    pass
            if mem_dc is not None:
                try:
                    mem_dc.DeleteDC()
                except Exception:
                    pass
            if hwnd and window_dc is not None:
                try:
                    win32gui.ReleaseDC(hwnd, window_dc)
                except Exception:
                    pass

        if fallback_to_screen:
            return self._capture_screen_region(x, y, width, height)  # 降级到屏幕截图
        return None
    
    def _find_window_partial(self, partial_name: str) -> Optional[int]:
        """
        部分匹配窗口名称
        """
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                if partial_name.lower() in window_text.lower():
                    windows.append(hwnd)
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        return windows[0] if windows else None

    def _find_window_rect_by_name(self, window_name: str) -> Optional[Tuple[int, int, int, int]]:
        hwnd = win32gui.FindWindow(None, window_name)
        if not hwnd:
            hwnd = self._find_window_partial(window_name)
        if not hwnd:
            return None
        return win32gui.GetWindowRect(hwnd)

    def _capture_window_frame(self, window_name: str) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
        """Capture a full target window with PrintWindow and return it with its screen rect."""
        hwnd = None
        window_dc = None
        mem_dc = None
        save_dc = None
        save_bitmap = None
        try:
            hwnd = win32gui.FindWindow(None, window_name)
            if not hwnd:
                hwnd = self._find_window_partial(window_name)
                if not hwnd:
                    self.logger.warning(f"未找到窗口: {window_name}")
                    return None

            window_rect = win32gui.GetWindowRect(hwnd)
            window_x, window_y, window_right, window_bottom = window_rect
            window_width = window_right - window_x
            window_height = window_bottom - window_y
            if window_width <= 0 or window_height <= 0:
                return None

            window_dc = win32gui.GetWindowDC(hwnd)
            mem_dc = win32ui.CreateDCFromHandle(window_dc)
            save_dc = mem_dc.CreateCompatibleDC()
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mem_dc, window_width, window_height)
            save_dc.SelectObject(save_bitmap)

            result = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
            if not result:
                return None

            bmp_info = save_bitmap.GetInfo()
            bmp_str = save_bitmap.GetBitmapBits(True)
            image = np.frombuffer(bmp_str, dtype=np.uint8)
            image = image.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image, window_rect
        except Exception as e:
            self.logger.error(f"PrintWindow整窗截图失败: {e}")
            return None
        finally:
            if save_bitmap is not None:
                try:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception:
                    pass
            if save_dc is not None:
                try:
                    save_dc.DeleteDC()
                except Exception:
                    pass
            if mem_dc is not None:
                try:
                    mem_dc.DeleteDC()
                except Exception:
                    pass
            if hwnd and window_dc is not None:
                try:
                    win32gui.ReleaseDC(hwnd, window_dc)
                except Exception:
                    pass
    
    def get_screen_size(self) -> Tuple[int, int]:
        """
        获取屏幕尺寸
        
        Returns:
            Tuple[int, int]: (width, height)
        """
        try:
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            return screen_width, screen_height
        except Exception as e:
            self.logger.error(f"获取屏幕尺寸失败: {e}")
            return 1920, 1080  # 默认值
    
    def find_game_window(self, game_names: list = None) -> Optional[Tuple[str, int]]:
        """
        查找游戏窗口
        
        Args:
            game_names: 可能的游戏窗口名称列表
        
        Returns:
            Optional[Tuple[str, int]]: (窗口名称, 窗口句柄) 或 None
        """
        if game_names is None:
            game_names = ['鸣潮', 'Wuthering Waves', 'WutheringWaves']
        
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                process_name = self._get_process_name(hwnd)
                if self._is_own_app_window(window_text, process_name):
                    return True
                for game_name in game_names:
                    if game_name.lower() in window_text.lower():
                        windows.append((window_text, hwnd))
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        if windows:
            return windows[0]  # 返回第一个匹配的窗口
        return None

    def find_best_game_window(self, keywords: Optional[List[str]] = None) -> Optional[Dict[str, object]]:
        """
        查找匹配度最高的游戏窗口（标题关键字优先，其次进程名，再面积）

        Returns:
            dict: {
                'title': str,
                'hwnd': int,
                'rect': (left, top, right, bottom),
                'width': int,
                'height': int,
                'area': int,
                'process_name': str,
                'mode': 'fullscreen'|'borderless'|'windowed',
                'title_hits': int,
                'process_hits': int
            }
        """
        if keywords is None:
            keywords = ['鸣潮', 'Wuthering Waves']

        normalized_keywords = [kw.lower().replace(" ", "") for kw in keywords if kw]
        candidates: List[Dict[str, object]] = []

        def enum_windows_callback(hwnd, windows):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd)
            if not title or not title.strip():
                return True

            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 0 or height <= 0:
                return True

            title_norm = title.lower().replace(" ", "")
            title_hits = sum(1 for kw in normalized_keywords if kw in title_norm)

            process_name = self._get_process_name(hwnd)
            if self._is_own_app_window(title, process_name):
                return True
            proc_norm = process_name.lower().replace(" ", "") if process_name else ""
            process_hits = sum(1 for kw in normalized_keywords if kw in proc_norm)

            if title_hits == 0 and process_hits == 0:
                return True

            area = width * height
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            monitor_rect = self._get_monitor_rect(hwnd)
            mode = self._detect_window_mode(rect, style, monitor_rect)

            windows.append({
                'title': title,
                'hwnd': hwnd,
                'rect': rect,
                'width': width,
                'height': height,
                'area': area,
                'process_name': process_name,
                'mode': mode,
                'title_hits': title_hits,
                'process_hits': process_hits
            })
            return True

        win32gui.EnumWindows(enum_windows_callback, candidates)

        if not candidates:
            return None

        candidates.sort(
            key=lambda w: (w['title_hits'], w['process_hits'], w['area']),
            reverse=True
        )
        return candidates[0]
    
    def get_all_windows(self) -> list:
        """
        获取所有可见窗口列表
        
        Returns:
            list: [(窗口名称, 窗口句柄), ...] 的列表
        """
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                # 过滤掉空窗口名称和一些系统窗口
                if window_text and len(window_text.strip()) > 0:
                    # 过滤掉一些常见的系统窗口
                    system_windows = ['Program Manager', 'Desktop Window Manager', 'Windows Input Experience']
                    if not any(sys_win in window_text for sys_win in system_windows):
                        windows.append((window_text, hwnd))
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        # 按窗口名称排序
        windows.sort(key=lambda x: x[0])
        return windows

    def _get_process_name(self, hwnd: int) -> str:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return ""
            try:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
                    False,
                    pid
                )
            except Exception:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                    False,
                    pid
                )
            try:
                exe_path = win32process.GetModuleFileNameEx(process_handle, 0)
                return os.path.basename(exe_path)
            finally:
                win32api.CloseHandle(process_handle)
        except Exception:
            return ""

    def _get_monitor_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        try:
            monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            info = win32api.GetMonitorInfo(monitor)
            return info.get("Monitor", (0, 0, 0, 0))
        except Exception:
            return (0, 0, 0, 0)

    def _detect_window_mode(self, rect: Tuple[int, int, int, int], style: int,
                            monitor_rect: Tuple[int, int, int, int]) -> str:
        left, top, right, bottom = rect
        mon_left, mon_top, mon_right, mon_bottom = monitor_rect

        tolerance = 2
        if (abs(left - mon_left) <= tolerance and abs(top - mon_top) <= tolerance and
                abs(right - mon_right) <= tolerance and abs(bottom - mon_bottom) <= tolerance):
            return "fullscreen"

        has_caption = bool(style & win32con.WS_CAPTION)
        has_thick = bool(style & win32con.WS_THICKFRAME)
        if not has_caption and not has_thick:
            return "borderless"
        return "windowed"


# 全局截图实例
_screen_capture_instance = None


def get_screen_capture() -> ScreenCapture:
    """
    获取全局屏幕截图实例
    """
    global _screen_capture_instance
    if _screen_capture_instance is None:
        _screen_capture_instance = ScreenCapture()
    return _screen_capture_instance


def capture_region_callback(x: int, y: int, width: int, height: int, 
                           mode: str, target_window_name: str) -> Optional[np.ndarray]:
    """
    OCR引擎使用的截图回调函数
    
    Args:
        x, y: 截图区域左上角坐标
        width, height: 截图区域尺寸
        mode: 截图模式
        target_window_name: 目标窗口名称
    
    Returns:
        numpy.ndarray: 截图图像或None
    """
    screen_capture = get_screen_capture()
    return screen_capture.capture_region(x, y, width, height, mode, target_window_name)


def capture_frame_and_region_callback(
    x: int,
    y: int,
    width: int,
    height: int,
    mode: str,
    target_window_name: str,
) -> Optional[CapturedFrameRegion]:
    """Capture one shared frame and the requested OCR crop."""
    screen_capture = get_screen_capture()
    return screen_capture.capture_frame_and_region(x, y, width, height, mode, target_window_name)
