#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义地图示例
演示如何添加和使用自定义地图
"""

import sys
import os
import json
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))


def add_custom_map_example():
    """添加自定义地图示例"""
    print("=== 添加自定义地图示例 ===")
    
    try:
        from tile_generator import process_image, get_image_info, update_map_config
        
        # 示例图片路径（请替换为实际路径）
        image_path = "path/to/your/custom_map.jpg"
        
        if not os.path.exists(image_path):
            print(f"示例图片不存在: {image_path}")
            print("请将实际的地图图片路径替换到 image_path 变量中")
            return False
        
        # 1. 获取图片信息
        file_size_mb, width, height = get_image_info(image_path)
        print(f"图片信息:")
        print(f"  尺寸: {width} x {height}")
        print(f"  大小: {file_size_mb:.2f} MB")
        
        # 2. 处理图片（自动决定是否需要瓦片化）
        print("正在处理地图图片...")
        process_image(image_path)
        print("地图添加成功!")
        
        return True
        
    except ImportError as e:
        print(f"导入模块失败: {e}")
        return False
    except Exception as e:
        print(f"添加地图失败: {e}")
        return False


def create_map_config_example():
    """创建地图配置示例"""
    print("\n=== 创建地图配置示例 ===")
    
    # 示例地图配置
    map_configs = [
        {
            "name": "my_custom_map.jpg",
            "tiled": False,  # 小图片，不需要瓦片化
            "width": 2048,
            "height": 2048,
            "maxZoom": 0,
            "description": "我的自定义小地图"
        },
        {
            "name": "large_world_map",
            "tiled": True,   # 大图片，需要瓦片化
            "width": 8192,
            "height": 8192,
            "maxZoom": 6,
            "description": "大型世界地图"
        }
    ]
    
    # 保存到配置文件
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'custom_maps.json')
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(map_configs, f, ensure_ascii=False, indent=2)
        
        print(f"地图配置已保存到: {config_path}")
        
        # 显示配置内容
        print("配置内容:")
        for config in map_configs:
            print(f"  - {config['name']}: {config['width']}x{config['height']} "
                  f"(瓦片化: {'是' if config['tiled'] else '否'})")
            
    except Exception as e:
        print(f"保存配置失败: {e}")


def load_custom_map_example():
    """加载自定义地图示例"""
    print("\n=== 加载自定义地图示例 ===")
    
    from main_app import LocalServerManager
    
    try:
        # 创建服务器管理器
        server_mgr = LocalServerManager()
        
        # 获取本地地图列表
        local_maps = server_mgr.get_local_maps()
        print(f"发现 {len(local_maps)} 个本地地图:")
        
        for i, map_name in enumerate(local_maps, 1):
            print(f"  {i}. {map_name}")
        
        if local_maps:
            # 切换到第一个地图
            first_map = local_maps[0]
            print(f"\n切换到地图: {first_map}")
            
            command = {"type": "mapChange", "mapName": first_map}
            # 这里只是示例，实际需要启动服务器后才能广播
            print(f"发送命令: {command}")
            
    except Exception as e:
        print(f"加载地图列表失败: {e}")


def calibrate_custom_map_example():
    """校准自定义地图示例"""
    print("\n=== 校准自定义地图示例 ===")
    
    from main_app import CalibrationSystem, CalibrationDataManager, CalibrationPoint
    
    # 示例：为自定义地图设置校准点
    # 这些坐标需要根据实际地图调整
    custom_map_points = [
        # 格式：CalibrationPoint(游戏X, 游戏Y, 地理纬度, 地理经度)
        CalibrationPoint(x=500, y=500, lat=30.100000, lon=120.100000),
        CalibrationPoint(x=1500, y=1000, lat=30.110000, lon=120.120000),
        CalibrationPoint(x=1000, y=1500, lat=30.120000, lon=120.110000)
    ]
    
    # 计算变换矩阵
    transform_matrix = CalibrationSystem.calculate_transform_matrix(custom_map_points)
    
    if transform_matrix:
        print("自定义地图校准成功!")
        
        # 保存校准数据
        calibration_mgr = CalibrationDataManager()
        calibration_mgr.save_calibration('local', 'my_custom_map', transform_matrix)
        print("校准数据已保存")
        
        # 测试坐标转换
        test_x, test_y = 750, 750
        lat, lon = CalibrationSystem.transform(test_x, test_y, transform_matrix)
        print(f"测试转换: ({test_x}, {test_y}) -> ({lat:.6f}, {lon:.6f})")
        
    else:
        print("校准失败！请检查校准点数据")


def batch_process_maps():
    """批量处理地图示例"""
    print("\n=== 批量处理地图示例 ===")
    
    # 示例地图文件列表
    map_files = [
        "maps/region_1.jpg",
        "maps/region_2.png", 
        "maps/world_map.jpg"
    ]
    
    for map_file in map_files:
        if os.path.exists(map_file):
            try:
                from tile_generator import process_image
                print(f"处理地图: {map_file}")
                process_image(map_file)
                print(f"✓ 完成: {map_file}")
            except Exception as e:
                print(f"✗ 失败: {map_file} - {e}")
        else:
            print(f"跳过: {map_file} (文件不存在)")


def main():
    """主函数"""
    print("=== 自定义地图示例 ===\n")
    
    # 1. 添加自定义地图
    if add_custom_map_example():
        # 2. 创建地图配置
        create_map_config_example()
        
        # 3. 加载自定义地图
        load_custom_map_example()
        
        # 4. 校准自定义地图
        calibrate_custom_map_example()
    
    # 5. 批量处理示例
    batch_process_maps()
    
    print("\n提示:")
    print("- 将您的地图图片放在 images/ 目录中")
    print("- 大于12MB的图片会自动切分为瓦片")
    print("- 支持的格式: JPG, PNG, BMP")
    print("- 校准点需要根据实际地图调整")


if __name__ == "__main__":
    main()