# -*- coding: utf-8 -*-
"""
地图设置页面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QFileDialog, QProgressBar, QMessageBox
)
from PySide6.QtCore import Signal
from qfluentwidgets import (
    BodyLabel, SubtitleLabel, PushButton, PrimaryPushButton,
    RadioButton, CardWidget, InfoBar, InfoBarPosition,
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

from core.settings_manager import SettingsManager
from core.map_generator import MapGeneratorWorker
from core.calibration import CalibrationDataManager


class MapSettingsInterface(QWidget):
    """地图设置页面"""
    
    map_source_changed = Signal(str)  # 'official', 'local'
    calibration_requested = Signal()
    auto_calibration_toggled = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('mapSettingsInterface')
        self.settings = SettingsManager()
        self.map_worker = None
        self._auto_calibration_available = True
        self._calibration_text = tr("not_calibrated", "未校准")
        self._calibration_ok = False
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # === 地图源选择 ===
        source_card = CardWidget(self)
        source_layout = QVBoxLayout(source_card)
        
        self.source_title_label = SubtitleLabel()
        source_layout.addWidget(self.source_title_label)
        
        self.radio_official = RadioButton()
        self.radio_official.setChecked(True)
        self.radio_official.toggled.connect(lambda c: c and self.on_source_changed('official'))
        source_layout.addWidget(self.radio_official)
        
        self.radio_local = RadioButton()
        self.radio_local.toggled.connect(lambda c: c and self.on_source_changed('local'))
        source_layout.addWidget(self.radio_local)
        
        layout.addWidget(source_card)
        
        # === 本地地图管理 ===
        local_card = CardWidget(self)
        local_layout = QVBoxLayout(local_card)
        
        self.local_title_label = SubtitleLabel()
        local_layout.addWidget(self.local_title_label)
        
        btn_layout = QHBoxLayout()
        self.add_map_btn = PrimaryPushButton()
        self.add_map_btn.clicked.connect(self.add_local_map)
        btn_layout.addWidget(self.add_map_btn)

        self.delete_map_btn = PushButton()
        self.delete_map_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
        self.delete_map_btn.clicked.connect(self.delete_local_map)
        btn_layout.addWidget(self.delete_map_btn)

        self.refresh_btn = PushButton()
        self.refresh_btn.clicked.connect(self.refresh_map_list)
        btn_layout.addWidget(self.refresh_btn)
        
        btn_layout.addStretch()
        local_layout.addLayout(btn_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        local_layout.addWidget(self.progress_bar)
        
        self.status_label = BodyLabel("")
        local_layout.addWidget(self.status_label)
        
        self.map_list = QListWidget()
        self.map_list.setMaximumHeight(150)
        self.update_theme()  # 应用主题样式
        local_layout.addWidget(self.map_list)
        
        layout.addWidget(local_card)
        
        # === 校准设置 ===
        calib_card = CardWidget(self)
        calib_layout = QVBoxLayout(calib_card)
        
        self.calib_title_label = SubtitleLabel()
        calib_layout.addWidget(self.calib_title_label)
        
        self.calib_desc_label = BodyLabel()
        calib_layout.addWidget(self.calib_desc_label)

        calib_actions = QHBoxLayout()

        self.calib_btn = PrimaryPushButton()
        self.calib_btn.clicked.connect(self.calibration_requested.emit)
        calib_actions.addWidget(self.calib_btn)

        self.auto_calibration_check = PushButton()
        self.auto_calibration_check.setCheckable(True)
        self.auto_calibration_check.toggled.connect(self._on_auto_calibration_toggled)
        calib_actions.addWidget(self.auto_calibration_check)
        calib_actions.addStretch()
        calib_layout.addLayout(calib_actions)

        self.auto_calibration_hint = BodyLabel()
        calib_layout.addWidget(self.auto_calibration_hint)

        self.calibration_status_label = BodyLabel()
        calib_layout.addWidget(self.calibration_status_label)
        
        layout.addWidget(calib_card)

        layout.addStretch()
        self.retranslate_ui()
    
    def on_source_changed(self, source: str):
        self.settings.set("map.source", source)
        self.map_source_changed.emit(source)
    
    def add_local_map(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("map_select_images_title", "选择地图图片"),
            "",
            tr("map_image_filter", "图片文件 (*.png *.jpg *.jpeg *.bmp)")
        )
        if files:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.map_worker = MapGeneratorWorker(files)
            self.map_worker.progress_updated.connect(self.progress_bar.setValue)
            self.map_worker.status_updated.connect(self.status_label.setText)
            self.map_worker.finished.connect(self.on_map_generation_finished)
            self.map_worker.start()
    
    def on_map_generation_finished(self, success: bool, message: str):
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
        if success:
            self.refresh_map_list()
            InfoBar.success(
                tr("map_generation_success_title", "成功"),
                message,
                parent=self,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.error(
                tr("map_generation_failed_title", "失败"),
                message,
                parent=self,
                position=InfoBarPosition.TOP,
            )
    
    def refresh_map_list(self):
        self.map_list.clear()
        try:
            from server_manager import LocalServerManager
            server = LocalServerManager()
            maps = server.get_local_maps()
            for m in maps:
                self.map_list.addItem(m)
        except Exception as e:
            print(f"刷新地图列表失败: {e}")

    def delete_local_map(self):
        """删除选中的本地地图"""
        current_item = self.map_list.currentItem()
        if not current_item:
            QMessageBox.warning(
                self,
                tr("map_no_selection_title", "未选择地图"),
                tr("map_no_selection_message", "请先选择要删除的地图"),
            )
            return

        map_name = current_item.text()

        # 确认删除
        reply = QMessageBox.question(
            self,
            tr("map_confirm_delete_title", "确认删除"),
            tr("map_confirm_delete_message", "确定要删除地图 '{map_name}' 吗？\n\n这将删除：\n• 地图文件和瓦片数据\n• 该地图的校准数据\n\n此操作不可恢复！", map_name=map_name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            from server_manager import LocalServerManager
            server = LocalServerManager()

            # Delete map files
            success = server.delete_local_map(map_name)

            if success:
                # Delete calibration data
                try:
                    calib_manager = CalibrationDataManager()
                    calib_manager.delete_calibration('local', map_name)
                    print(f"Deleted calibration data for: {map_name}")
                except Exception as e:
                    print(f"Failed to delete calibration data: {e}")

                # Refresh list
                self.refresh_map_list()

                InfoBar.success(
                    tr("map_delete_success_title", "删除成功"),
                    tr("map_delete_success_message", "已成功删除地图: {map_name}", map_name=map_name),
                    parent=self,
                    position=InfoBarPosition.TOP
                )
            else:
                InfoBar.error(
                    tr("map_delete_failed_title", "删除失败"),
                    tr("map_delete_failed_message", "删除地图失败，请查看日志了解详情"),
                    parent=self,
                    position=InfoBarPosition.TOP
                )

        except Exception as e:
            print(f"删除地图失败: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                tr("map_delete_error_title", "错误"),
                tr("map_delete_error_message", "删除地图时发生错误:\n{error}", error=str(e))
            )

    def load_settings(self):
        source = self.settings.get("map.source", "official")
        if source not in {"official", "local"}:
            source = "official"
            self.settings.set("map.source", source)
        if source == "official":
            self.radio_official.setChecked(True)
        elif source == "local":
            self.radio_local.setChecked(True)

        enabled = bool(self.settings.get("map.auto_calibration_enabled", True))
        self.auto_calibration_check.setChecked(enabled)
        self._refresh_auto_calibration_button_text(enabled)
        self.refresh_map_list()

    def _on_auto_calibration_toggled(self, enabled: bool):
        self._refresh_auto_calibration_button_text(enabled)
        self.settings.set("map.auto_calibration_enabled", bool(enabled))
        self.auto_calibration_toggled.emit(bool(enabled))

    def _refresh_auto_calibration_button_text(self, enabled: bool):
        self.auto_calibration_check.setText(
            tr("map_auto_calibration_on", "自动校准: 开")
            if enabled
            else tr("map_auto_calibration_off", "自动校准: 关")
        )

    def is_auto_calibration_enabled(self) -> bool:
        return bool(self.auto_calibration_check.isChecked())

    def set_auto_calibration_available(self, available: bool):
        self._auto_calibration_available = available
        self.auto_calibration_check.setEnabled(available)
        self._redraw_auto_calibration_hint()

    def update_calibration_status(self, text: str, ok: bool = False):
        self._calibration_text = text
        self._calibration_ok = ok
        self._redraw_calibration_status()

    def _redraw_auto_calibration_hint(self):
        if self._auto_calibration_available:
            self.auto_calibration_hint.setText(
                tr("map_auto_calibration_available_hint", "仅在线官方地图可用；启用后将自动获取坐标变换参数")
            )
        else:
            self.auto_calibration_hint.setText(
                tr("map_auto_calibration_unavailable_hint", "当前地图不支持自动校准（仅在线官方地图可用）")
            )

    def _redraw_calibration_status(self):
        self.calibration_status_label.setText(
            tr("map_calibration_status", "当前校准: {text}", text=self._calibration_text)
        )
        color = "#0f9d58" if self._calibration_ok else "#a66a00"
        self.calibration_status_label.setStyleSheet(f"color: {color};")

    def retranslate_ui(self):
        self.source_title_label.setText(tr("map_source_title", "地图源"))
        self.radio_official.setText(tr("map_source_official_full", "库街区官方地图"))
        self.radio_local.setText(tr("map_source_local", "本地地图"))
        self.local_title_label.setText(tr("map_local_management", "本地地图管理"))
        self.add_map_btn.setText(tr("map_add", "添加地图"))
        self.delete_map_btn.setText(tr("map_delete", "删除地图"))
        self.refresh_btn.setText(tr("map_refresh_list", "刷新列表"))
        self.calib_title_label.setText(tr("map_calibration_title", "地图校准"))
        self.calib_desc_label.setText(
            tr("map_calibration_desc", "校准地图坐标与游戏坐标的对应关系，需要至少2个校准点")
        )
        self.calib_btn.setText(tr("map_open_calibration_window", "打开校准窗口"))
        self._refresh_auto_calibration_button_text(self.auto_calibration_check.isChecked())
        self._redraw_auto_calibration_hint()
        self._redraw_calibration_status()

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager
        self.map_list.setStyleSheet(ThemeManager.get_list_widget_style())
