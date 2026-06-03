# -*- coding: utf-8 -*-
"""
工具函数模块
"""

import sys
import os
import ctypes

from core import paths


def is_admin() -> bool:
    """检测是否以管理员权限运行"""
    if sys.platform == 'win32':
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        # Linux/Mac: 检查是否为 root
        return os.getuid() == 0


def show_admin_required_message():
    """使用 Windows 原生 MessageBox 显示管理员权限提示"""
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(
            0,
            "本程序需要以管理员权限运行。\n请右键点击程序，选择\"以管理员身份运行\"。",
            "权限不足",
            0x10  # MB_ICONERROR
        )
    else:
        print("错误: 本程序需要以管理员/root权限运行")


def get_script_dir() -> str:
    """获取脚本所在目录"""
    return str(paths.src_root() / "core")


def get_resource_root() -> str:
    """获取运行时资源根目录，兼容源码运行和 PyInstaller 打包。"""
    return str(paths.resource_root())


def get_src_dir() -> str:
    """获取 src 目录路径"""
    return str(paths.src_root())


def get_project_root() -> str:
    """获取项目根目录路径"""
    return str(paths.project_root())


def get_assets_path(filename: str) -> str:
    """获取 assets 目录下文件的完整路径"""
    return str(paths.asset_file(filename))
