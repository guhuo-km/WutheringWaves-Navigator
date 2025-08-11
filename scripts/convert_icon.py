#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图标转换工具
将ico.png转换为标准的.ico格式，用于Windows程序图标
"""

import os
from PIL import Image

def convert_png_to_ico():
    """将PNG图标转换为ICO格式"""
    try:
        # 检查源文件
        png_path = "ico.png"
        ico_path = "ico.ico"
        
        if not os.path.exists(png_path):
            print(f"错误: 未找到图标文件 {png_path}")
            return False
        
        # 打开PNG图像
        img = Image.open(png_path)
        print(f"原始图像尺寸: {img.size}")
        
        # 创建多尺寸的ICO文件
        # Windows推荐的图标尺寸
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        # 调整图像为正方形（如果需要）
        if img.size[0] != img.size[1]:
            # 如果不是正方形，裁剪为正方形
            min_size = min(img.size)
            left = (img.size[0] - min_size) // 2
            top = (img.size[1] - min_size) // 2
            right = left + min_size
            bottom = top + min_size
            img = img.crop((left, top, right, bottom))
            print(f"已裁剪为正方形: {img.size}")
        
        # 确保是RGBA模式
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # 保存为ICO格式
        img.save(ico_path, format='ICO', sizes=sizes)
        print(f"✓ 成功转换: {png_path} -> {ico_path}")
        print(f"✓ 生成的ICO文件包含尺寸: {sizes}")
        
        return True
        
    except Exception as e:
        print(f"转换失败: {e}")
        return False

if __name__ == "__main__":
    print("=== 图标转换工具 ===")
    print()
    
    if convert_png_to_ico():
        print()
        print("转换完成！现在可以使用ico.ico文件作为程序图标。")
    else:
        print()
        print("转换失败！请检查ico.png文件是否存在且格式正确。")
    
    input("\n按回车键退出...")