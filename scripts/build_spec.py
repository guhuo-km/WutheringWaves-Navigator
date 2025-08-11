#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 构建配置脚本
用于将呜呜大地图打包为独立的可执行文件
"""

import os
import sys

# 获取当前脚本目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 数据文件列表
datas = [
    (os.path.join(current_dir, 'languages'), 'languages'),
    (os.path.join(current_dir, 'models'), 'models'),
    (os.path.join(current_dir, 'tiles'), 'tiles'),
    (os.path.join(current_dir, 'images'), 'images'),
    (os.path.join(current_dir, 'recorded_routes'), 'recorded_routes'),
    (os.path.join(current_dir, 'web_profile'), 'web_profile'),
    (os.path.join(current_dir, 'index.html'), '.'),
    (os.path.join(current_dir, 'ico.png'), '.'),
]

# 确保图标文件存在
icon_path = os.path.join(current_dir, 'ico.png')
if not os.path.exists(icon_path):
    print(f"警告: 图标文件 {icon_path} 不存在")
    icon_path = None

# 隐藏导入
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtWidgets', 
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebChannel',
    'numpy',
    'ultralytics',
    'torch',
    'torchvision',
    'cv2',
    'PIL',
    'werkzeug',
    'requests',
    'json',
    'threading',
    'urllib.parse',
    'datetime',
    'language_manager',
    'ocr_manager',
    'route_recorder',
    'transparent_overlay',
    'separated_map_window',
    'route_list_dialog',
]

# 排除的模块（减少包大小）
excludes = [
    'tkinter',
    'matplotlib',
    'PyQt5',
    'PyQt6',
    'wx',
    'Tkinter',
]

# PyInstaller配置
a = Analysis(
    ['main_app.py'],
    pathex=[current_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 移除不必要的文件以减小体积
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='呜呜大地图',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if icon_path else None,
    version='version_info.txt'  # 可选的版本信息文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WutheringWaves_Navigator'
)

print("构建配置完成!")
print("使用方法: pyinstaller build_spec.py")