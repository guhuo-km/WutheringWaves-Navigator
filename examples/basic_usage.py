#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本使用示例
演示WutheringWaves Navigator的基本功能
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import CalibrationSystem, CalibrationDataManager, CalibrationPoint


def basic_calibration_example():
    """基本校准示例"""
    print("=== 基本校准示例 ===")
    
    # 1. 创建校准管理器
    calibration_mgr = CalibrationDataManager()
    
    # 2. 创建校准点 (游戏坐标 -> 地理坐标)
    points = [
        CalibrationPoint(x=1000, y=2000, lat=31.123456, lon=121.654321),
        CalibrationPoint(x=1500, y=2500, lat=31.133456, lon=121.664321),
        CalibrationPoint(x=2000, y=3000, lat=31.143456, lon=121.674321)
    ]
    
    # 3. 计算变换矩阵
    transform_matrix = CalibrationSystem.calculate_transform_matrix(points)
    
    if transform_matrix:
        print(f"校准成功！变换矩阵: {transform_matrix.to_dict()}")
        
        # 4. 坐标转换示例
        game_x, game_y = 1750, 2750
        lat, lon = CalibrationSystem.transform(game_x, game_y, transform_matrix)
        print(f"游戏坐标 ({game_x}, {game_y}) -> 地理坐标 ({lat:.6f}, {lon:.6f})")
        
        # 5. 保存校准数据
        calibration_mgr.save_calibration('local', 'example_map', transform_matrix)
        print("校准数据已保存")
        
    else:
        print("校准失败！")


def load_calibration_example():
    """加载校准数据示例"""
    print("\n=== 加载校准数据示例 ===")
    
    calibration_mgr = CalibrationDataManager()
    
    # 加载已保存的校准数据
    transform_matrix = calibration_mgr.load_calibration('local', 'example_map')
    
    if transform_matrix:
        print("成功加载校准数据")
        
        # 使用加载的矩阵进行坐标转换
        test_points = [(1200, 2200), (1800, 2800), (2200, 3200)]
        
        for game_x, game_y in test_points:
            lat, lon = CalibrationSystem.transform(game_x, game_y, transform_matrix)
            print(f"游戏坐标 ({game_x}, {game_y}) -> 地理坐标 ({lat:.6f}, {lon:.6f})")
    else:
        print("未找到校准数据")


if __name__ == "__main__":
    try:
        basic_calibration_example()
        load_calibration_example()
    except Exception as e:
        print(f"示例运行失败: {e}")
        print("请确保已正确安装依赖包和OCR模型")