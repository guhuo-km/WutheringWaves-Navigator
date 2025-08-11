#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Screen Capture Module for WutheringWaves Navigator
屏幕截图模块
"""

import numpy as np
import win32gui
import win32ui
import win32con
import win32api
from PIL import Image
import cv2
from typing import Optional, Tuple
import logging


class ScreenCapture:
    """
    屏幕截图工具类
    支持多种截图模式和窗口检测
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
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
        try:
            if mode == 'PrintWindow' and target_window_name:
                return self._capture_window_region(x, y, width, height, target_window_name)
            else:
                return self._capture_screen_region(x, y, width, height)
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None
    
    def _capture_screen_region(self, x: int, y: int, width: int, height: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方式捕获屏幕区域
        """
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
            
            # 清理资源
            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(0, screen_dc)
            
            return image
            
        except Exception as e:
            self.logger.error(f"BitBlt截图失败: {e}")
            return None
    
    def _capture_window_region(self, x: int, y: int, width: int, height: int, 
                              window_name: str) -> Optional[np.ndarray]:
        """
        使用PrintWindow方式捕获指定窗口的区域
        """
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
                    
                    # 清理资源
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                    save_dc.DeleteDC()
                    mem_dc.DeleteDC()
                    win32gui.ReleaseDC(hwnd, window_dc)
                    
                    return cropped_image
            
            # 清理资源
            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, window_dc)
            
            # 如果PrintWindow失败，降级到BitBlt
            return self._capture_screen_region(x, y, width, height)
            
        except Exception as e:
            self.logger.error(f"PrintWindow截图失败: {e}")
            return self._capture_screen_region(x, y, width, height)  # 降级到屏幕截图
    
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
                for game_name in game_names:
                    if game_name.lower() in window_text.lower():
                        windows.append((window_text, hwnd))
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        if windows:
            return windows[0]  # 返回第一个匹配的窗口
        return None
    
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