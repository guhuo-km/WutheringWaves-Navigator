# -*- coding: utf-8 -*-
"""
地图生成工作线程
从 main_app_legacy.py 提取并优化
"""

import os
from PySide6.QtCore import QThread, Signal

try:
    from language_manager import tr
except ImportError:
    def tr(key, default='', **kwargs):
        text = default or key
        for k, v in kwargs.items():
            text = text.replace('{' + k + '}', str(v))
        return text


class MapGeneratorWorker(QThread):
    """地图生成工作线程，防止UI卡死"""
    progress_updated = Signal(int)  # 进度更新信号
    status_updated = Signal(str)    # 状态更新信号
    finished = Signal(bool, str)    # 完成信号 (成功/失败, 消息)
    
    def __init__(self, image_paths: list):
        super().__init__()
        self.image_paths = image_paths
        
    def run(self):
        """在后台线程中执行地图生成"""
        try:
            # 检查是否存在tile_generator模块
            try:
                from tile_generator import process_image, get_image_info
            except ImportError:
                # 如果没有tile_generator模块，发出错误信号
                self.finished.emit(
                    False,
                    tr('tile_generator_missing',
                       'tile_generator模块不存在，只能处理直接复制到maps目录的地图文件')
                )
                return

            total_files = len(self.image_paths)

            if total_files == 0:
                self.finished.emit(False, tr('no_files_selected', '未选择任何文件'))
                return

            for i, image_path in enumerate(self.image_paths):
                self.status_updated.emit(
                    tr('processing_file', '正在处理: {filename}',
                       filename=os.path.basename(image_path))
                )

                # 检查文件信息
                file_size_mb, width, height = get_image_info(image_path)
                if not file_size_mb:
                    continue

                # 创建进度回调，用于更新UI进度条
                def progress_callback(tile_progress):
                    """
                    瓦片生成进度回调
                    tile_progress: 0.0 到 1.0，表示当前文件的完成百分比
                    """
                    # 计算当前文件在总进度中的起始位置
                    file_start_progress = (i / total_files)
                    # 每个文件占据的进度范围
                    file_progress_range = 1.0 / total_files
                    # 综合进度 = 文件起始进度 + (当前文件内部进度 * 文件进度范围)
                    overall_progress = file_start_progress + (tile_progress * file_progress_range)
                    # 转换为百分比并发射信号
                    self.progress_updated.emit(int(overall_progress * 100))

                # 处理图片，传入进度回调
                map_name = os.path.splitext(os.path.basename(image_path))[0]
                try:
                    process_image(image_path, progress_callback=progress_callback)
                except Exception as e:
                    self.finished.emit(
                        False,
                        tr('processing_failed', '处理 {map_name} 失败: {error}',
                           map_name=map_name, error=str(e))
                    )
                    return

            # 处理完成，进度设为100%
            self.progress_updated.emit(100)
            self.finished.emit(
                True,
                tr('processing_complete', '成功处理了 {count} 个地图文件', count=total_files)
            )

        except Exception as e:
            self.finished.emit(
                False,
                tr('processing_error', '处理过程中出现错误: {error}', error=str(e))
            )
