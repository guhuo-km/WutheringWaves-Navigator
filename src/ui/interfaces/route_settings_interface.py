# -*- coding: utf-8 -*-
"""
路线设置页面 - 内嵌路线列表
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    BodyLabel, SubtitleLabel, PushButton, PrimaryPushButton, CardWidget,
    StrongBodyLabel, LineEdit
)

from core.route_export_paths import (
    ROUTE_EXPORT_DIRECTORY_KEY,
    resolve_route_export_directory,
)
from core.settings_manager import SettingsManager

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key


class RouteSettingsInterface(QWidget):
    """路线设置页面 - 内嵌路线列表"""

    # 信号定义
    refresh_routes_requested = Signal()
    view_detail_requested = Signal(str)  # 传递文件路径
    export_route_requested = Signal(str)  # 传递文件路径
    delete_route_requested = Signal(str)  # 传递文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('routeSettingsInterface')
        self.route_recorder = None  # 将由 MainWindow 设置
        self._settings = SettingsManager()
        self._status_key = "route_loading"
        self._status_kwargs = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # === 录制设置 ===
        record_card = CardWidget(self)
        record_layout = QVBoxLayout(record_card)
        record_layout.setContentsMargins(20, 16, 20, 16)
        record_layout.setSpacing(12)

        self.record_title_label = StrongBodyLabel()
        record_layout.addWidget(self.record_title_label)

        self.record_desc_label = BodyLabel()
        record_layout.addWidget(self.record_desc_label)

        self.record_tip_label = BodyLabel()
        self.record_tip_label.setStyleSheet("color: gray;")
        record_layout.addWidget(self.record_tip_label)

        self.export_directory_label = BodyLabel()
        record_layout.addWidget(self.export_directory_label)

        export_directory_layout = QHBoxLayout()
        self.export_directory_edit = LineEdit()
        self.export_directory_edit.setReadOnly(True)
        export_directory_layout.addWidget(self.export_directory_edit, 1)

        self.choose_export_directory_btn = PushButton()
        self.choose_export_directory_btn.clicked.connect(self._choose_export_directory)
        export_directory_layout.addWidget(self.choose_export_directory_btn)

        self.reset_export_directory_btn = PushButton()
        self.reset_export_directory_btn.clicked.connect(self._reset_export_directory)
        export_directory_layout.addWidget(self.reset_export_directory_btn)

        record_layout.addLayout(export_directory_layout)
        self._refresh_export_directory()

        layout.addWidget(record_card)

        # === 路线列表卡片 ===
        route_list_card = CardWidget(self)
        route_list_layout = QVBoxLayout(route_list_card)
        route_list_layout.setContentsMargins(20, 16, 20, 16)
        route_list_layout.setSpacing(12)

        # 标题
        self.list_title_label = StrongBodyLabel()
        route_list_layout.addWidget(self.list_title_label)

        # 路线列表表格
        self.routes_table = QTableWidget()
        self.routes_table.setColumnCount(6)

        # 设置表格属性
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.setAlternatingRowColors(True)

        # 应用主题样式
        self.update_theme()

        # 调整列宽
        header = self.routes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        route_list_layout.addWidget(self.routes_table, 1)  # Stretch

        # 按钮区域
        button_layout = QHBoxLayout()

        self.refresh_btn = PushButton()
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        button_layout.addWidget(self.refresh_btn)

        self.view_detail_btn = PushButton()
        self.view_detail_btn.clicked.connect(self._on_view_detail_clicked)
        self.view_detail_btn.setEnabled(False)
        button_layout.addWidget(self.view_detail_btn)

        self.export_btn = PushButton()
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.export_btn.setEnabled(False)
        button_layout.addWidget(self.export_btn)

        self.delete_btn = PushButton()
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
        button_layout.addWidget(self.delete_btn)

        # 打开路线文件夹按钮
        self.open_folder_btn = PushButton()
        self.open_folder_btn.clicked.connect(self._on_open_folder_clicked)
        button_layout.addWidget(self.open_folder_btn)

        button_layout.addStretch()

        route_list_layout.addLayout(button_layout)

        # 状态标签
        self.status_label = BodyLabel()
        self.status_label.setStyleSheet("color: gray;")
        route_list_layout.addWidget(self.status_label)

        layout.addWidget(route_list_card, 1)  # Stretch

        # 连接表格选择事件
        self.routes_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.retranslate_ui()

    def set_route_recorder(self, route_recorder):
        """设置路线记录器"""
        self.route_recorder = route_recorder
        self.load_routes()

    def load_routes(self):
        """加载路线列表"""
        if not self.route_recorder:
            self._set_status("route_recorder_not_initialized")
            return

        try:
            route_files = self.route_recorder.list_recorded_routes()

            self.routes_table.setRowCount(len(route_files))

            for row, filepath in enumerate(route_files):
                summary = self.route_recorder.get_route_summary(filepath)
                if summary:
                    self.routes_table.setItem(row, 0, QTableWidgetItem(summary["name"]))
                    self.routes_table.setItem(row, 1, QTableWidgetItem(summary["created_time"]))
                    self.routes_table.setItem(row, 2, QTableWidgetItem(summary["duration"]))
                    self.routes_table.setItem(row, 3, QTableWidgetItem(str(summary["point_count"])))
                    self.routes_table.setItem(row, 4, QTableWidgetItem(summary["file_size"]))
                    self.routes_table.setItem(row, 5, QTableWidgetItem(summary["filepath"]))

                    # 存储文件路径到第一列的用户数据
                    self.routes_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, filepath)

            self._set_status("route_files_found", count=len(route_files))

        except Exception as e:
            self._set_status("route_load_failed", error=e)

    def _on_selection_changed(self):
        """选择改变时的处理"""
        has_selection = len(self.routes_table.selectedItems()) > 0
        self.view_detail_btn.setEnabled(has_selection)
        self.export_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def _get_selected_filepath(self):
        """获取选中的文件路径"""
        current_row = self.routes_table.currentRow()
        if current_row >= 0:
            item = self.routes_table.item(current_row, 0)
            if item:
                return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        self.load_routes()

    def _on_view_detail_clicked(self):
        """查看详情按钮点击"""
        filepath = self._get_selected_filepath()
        if filepath:
            self.view_detail_requested.emit(filepath)

    def _on_export_clicked(self):
        """导出按钮点击"""
        filepath = self._get_selected_filepath()
        if filepath:
            self.export_route_requested.emit(filepath)

    def _on_delete_clicked(self):
        """删除按钮点击"""
        filepath = self._get_selected_filepath()
        if filepath:
            self.delete_route_requested.emit(filepath)

    def _on_open_folder_clicked(self):
        """打开路线文件夹按钮点击"""
        import os
        import subprocess
        import sys
        from core import paths

        if not self.route_recorder:
            return

        # 获取路线文件夹路径
        folder_path = paths.routes_dir()

        # 确保文件夹存在
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        # 根据操作系统打开文件夹
        try:
            if sys.platform == "win32":
                os.startfile(str(folder_path))
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", str(folder_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)])
        except Exception as e:
            print(f"打开文件夹失败: {e}")

    def _choose_export_directory(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("route_export_directory_dialog_title", "选择默认路线导出文件夹"),
            str(resolve_route_export_directory(self._settings)),
        )
        if not folder:
            return
        self._settings.set(ROUTE_EXPORT_DIRECTORY_KEY, folder)
        self._refresh_export_directory()

    def _reset_export_directory(self):
        self._settings.delete(ROUTE_EXPORT_DIRECTORY_KEY)
        self._refresh_export_directory()

    def _refresh_export_directory(self):
        self.export_directory_edit.setText(
            str(resolve_route_export_directory(self._settings))
        )

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager
        self.routes_table.setStyleSheet(ThemeManager.get_route_table_style())

    def _set_status(self, key: str, **kwargs):
        self._status_key = key
        self._status_kwargs = kwargs
        defaults = {
            "route_loading": "加载路线列表中...",
            "route_recorder_not_initialized": "路线记录器未初始化",
            "route_files_found": "找到 {count} 个路线文件",
            "route_load_failed": "加载失败: {error}",
        }
        self.status_label.setText(tr(key, defaults[key], **kwargs))

    def retranslate_ui(self):
        self.record_title_label.setText(tr("route_record_settings", "录制设置"))
        self.record_desc_label.setText(
            tr("route_record_desc", "路线录制会自动记录OCR识别到的坐标点")
        )
        self.record_tip_label.setText(
            tr("route_record_tip", "提示: 在导航页面点击\"开始录制\"按钮开始录制路线")
        )
        self.export_directory_label.setText(
            tr("route_export_directory", "默认路线导出文件夹")
        )
        self.choose_export_directory_btn.setText(
            tr("route_export_directory_choose", "选择文件夹")
        )
        self.reset_export_directory_btn.setText(
            tr("route_export_directory_reset", "恢复默认")
        )
        self.list_title_label.setText(tr("route_list_title", "路线列表"))
        self.routes_table.setHorizontalHeaderLabels([
            tr("route_table_name", "路线名称"),
            tr("route_table_created_time", "创建时间"),
            tr("route_table_duration", "录制时长"),
            tr("route_table_point_count", "坐标点数"),
            tr("route_table_file_size", "文件大小"),
            tr("route_table_file_path", "文件路径"),
        ])
        self.refresh_btn.setText(tr("route_refresh_list", "刷新列表"))
        self.view_detail_btn.setText(tr("route_view_detail", "查看详情"))
        self.export_btn.setText(tr("route_export", "导出路线"))
        self.delete_btn.setText(tr("route_delete", "删除路线"))
        self.open_folder_btn.setText(tr("route_open_folder", "打开路线文件夹"))
        self._set_status(self._status_key, **self._status_kwargs)
