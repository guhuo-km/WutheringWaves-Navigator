# -*- coding: utf-8 -*-
"""
地图校准窗口
从 main_app_legacy.py 提取
"""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QGridLayout,
    QGroupBox, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from qfluentwidgets import BodyLabel, PushButton, LineEdit

# 多语言支持
try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

# 核心模块
from core.map_backend import MapBackend
from core.calibration import CalibrationPoint, CalibrationSystem

def get_map_urls(current_language="zh_CN"):
    """根据当前语言返回地图URL映射"""
    # 中文使用旧域名，其他语言使用新域名
    if current_language == "zh_CN":
        aura_url = "https://static-web.ghzs.com/cspage_pro/mingchao-map.html#/?map=default"
    else:
        aura_url = "https://www.ghzs666.com/wutheringwaves-map#/?map=default"

    return {
        "official_map": "https://www.kurobbs.com/mc/map",
        "aura_helper": aura_url
    }

class CalibrationWindow(QDialog):
    calibrationFinished = Signal(object)  # 传递变换矩阵

    def __init__(self, parent=None, current_map_provider="官方地图", current_map_url=None):
        super().__init__(parent)
        self.setWindowTitle(tr('map_calibration', '地图校准'))
        self.setGeometry(200, 200, 1200, 800)
        self.setModal(True)
        
        self.calibration_points = []
        self.transform_matrix = None
        self.current_lat = 0.0
        self.current_lng = 0.0
        self.current_zoom = 1
        self.current_map_provider = current_map_provider  # 记录当前地图提供商
        self.current_map_url = current_map_url  # 记录当前具体URL（包含副本信息）
        
        self.setup_ui()
        self.setup_web_channel()
        self.load_map()

    def setup_ui(self):
        # Theme adaptation for standard Qt widgets used in this dialog
        try:
            from core.theme_manager import ThemeManager

            # Base background
            self.setStyleSheet(ThemeManager.get_page_background_style())
        except Exception:
            ThemeManager = None  # type: ignore

        main_layout = QHBoxLayout(self)
        
        # 左侧: 地图视图
        map_layout = QVBoxLayout()
        
        # 十字准星标签
        self.crosshair_label = BodyLabel("+")
        self.crosshair_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crosshair_label.setStyleSheet("""
            BodyLabel { 
                color: red; 
                font-size: 24px; 
                font-weight: bold; 
                background: transparent; 
                border: none;
            }
        """)
        self.crosshair_label.setFixedSize(32, 32)
        
        # 地图视图 - 使用主窗口的WebProfile创建独立页面（避免页面共享冲突）
        try:
            parent_window = self.parent()
            # 检查 _web_profile（带下划线）属性
            if (parent_window and
                hasattr(parent_window, '_web_profile') and
                parent_window._web_profile):
                # 使用主窗口的profile创建新页面，保持session and cookie一致
                from PySide6.QtWebEngineCore import QWebEnginePage
                web_page = QWebEnginePage(parent_window._web_profile, self)
                self.web_view = QWebEngineView()
                self.web_view.setPage(web_page)
                self.shared_profile = True  # 标记使用共享profile
                self.log("Calibration window using main window's WebProfile to create independent page")
            else:
                # 降级方案：创建完全独立的页面
                self.web_view = QWebEngineView()
                self.shared_profile = False
                self.log("Calibration window using default web view")
        except Exception as e:
            self.web_view = QWebEngineView()
            self.shared_profile = False
            self.log(f"Calibration window web view setup failed, using default: {e}")
        
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        
        # 创建叠加布局，将十字准星放在地图中心
        map_container = QWidget()
        overlay_layout = QVBoxLayout(map_container)
        overlay_layout.addWidget(self.web_view)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用grid layout将十字准星定位到中心
        grid_layout = QGridLayout()
        grid_layout.addWidget(map_container, 0, 0, 3, 3)
        grid_layout.addWidget(self.crosshair_label, 1, 1, Qt.AlignmentFlag.AlignCenter)
        
        map_widget = QWidget()
        map_widget.setLayout(grid_layout)
        map_layout.addWidget(map_widget)

        # Ensure map container stays dark in dark theme
        if ThemeManager:
            try:
                map_widget.setStyleSheet(ThemeManager.get_page_background_style())
            except Exception:
                pass
        
        # 右侧: 控制面板
        control_layout = QVBoxLayout()
        control_widget = QWidget()
        control_widget.setFixedWidth(350)
        control_widget.setLayout(control_layout)

        # Ensure right control panel matches theme
        if ThemeManager:
            try:
                control_widget.setStyleSheet(ThemeManager.get_page_background_style())
            except Exception:
                pass
        
        # 状态信息组
        status_group = QGroupBox(tr('map_status', '地图状态'))
        status_layout = QVBoxLayout(status_group)

        # GroupBox theme
        if ThemeManager:
            try:
                if ThemeManager.is_dark_theme():
                    group_style = (
                        "QGroupBox {"
                        "  color: #EDEDED;"
                        "  border: 1px solid #3F3F3F;"
                        "  border-radius: 8px;"
                        "  margin-top: 12px;"
                        "  background-color: #2D2D2D;"
                        "}"
                        "QGroupBox::title {"
                        "  subcontrol-origin: margin;"
                        "  left: 10px;"
                        "  padding: 0 6px;"
                        "  color: #EDEDED;"
                        "}"
                        "QGroupBox QLabel {"
                        "  background-color: transparent;"
                        "  color: #EDEDED;"
                        "}"
                    )
                else:
                    group_style = (
                        "QGroupBox {"
                        "  border: 1px solid #E5E5E5;"
                        "  border-radius: 8px;"
                        "  margin-top: 12px;"
                        "  background-color: #FFFFFF;"
                        "}"
                        "QGroupBox::title {"
                        "  subcontrol-origin: margin;"
                        "  left: 10px;"
                        "  padding: 0 6px;"
                        "  color: #333333;"
                        "}"
                        "QGroupBox QLabel {"
                        "  background-color: transparent;"
                        "  color: #333333;"
                        "}"
                    )

                status_group.setStyleSheet(group_style)
            except Exception:
                pass
        
        self.capture_status_label = BodyLabel(tr('capture_status_capturing', '捕获状态: 正在捕获...'))
        self.lat_lng_label = BodyLabel(tr('lat_lng_waiting', '经纬度: 等待数据...'))
        self.zoom_label = BodyLabel(tr('zoom_level_waiting', '缩放等级: 等待数据...'))

        # Avoid patchy dark blocks behind labels in status panel
        self.capture_status_label.setStyleSheet("background-color: transparent;")
        self.lat_lng_label.setStyleSheet("background-color: transparent;")
        self.zoom_label.setStyleSheet("background-color: transparent;")
        
        status_layout.addWidget(self.capture_status_label)
        status_layout.addWidget(self.lat_lng_label)
        status_layout.addWidget(self.zoom_label)
        
        # 坐标输入组
        input_group = QGroupBox(tr('game_coordinate_input', '游戏坐标输入'))
        input_layout = QGridLayout(input_group)

        if ThemeManager:
            try:
                input_group.setStyleSheet(status_group.styleSheet())
            except Exception:
                pass
        
        self.x_label = BodyLabel(tr('x_coordinate', 'X坐标:'))
        self.x_label.setStyleSheet("background-color: transparent;")
        input_layout.addWidget(self.x_label, 0, 0)
        self.x_input = LineEdit()
        input_layout.addWidget(self.x_input, 0, 1)

        self.y_label = BodyLabel(tr('y_coordinate', 'Y坐标:'))
        self.y_label.setStyleSheet("background-color: transparent;")
        input_layout.addWidget(self.y_label, 1, 0)
        self.y_input = LineEdit()
        input_layout.addWidget(self.y_input, 1, 1)
        
        # 校准操作组
        calib_group = QGroupBox(tr('calibration_operations', '校准操作'))
        calib_layout = QVBoxLayout(calib_group)

        if ThemeManager:
            try:
                calib_group.setStyleSheet(status_group.styleSheet())
            except Exception:
                pass
        
        self.calib_btn1 = PushButton(tr('set_calibration_point_1', '设定校准点 1'))
        self.calib_btn2 = PushButton(tr('set_calibration_point_2', '设定校准点 2'))
        self.calib_btn3 = PushButton(tr('set_calibration_point_3', '设定校准点 3'))
        self.finish_btn = PushButton(tr('calculate_and_finish_calibration', '计算并完成校准'))
        self.finish_btn.setEnabled(False)
        
        calib_layout.addWidget(self.calib_btn1)
        calib_layout.addWidget(self.calib_btn2)
        calib_layout.addWidget(self.calib_btn3)
        calib_layout.addWidget(self.finish_btn)
        
        # 校准数据表格
        table_group = QGroupBox(tr('calibration_data', '校准数据'))
        table_layout = QVBoxLayout(table_group)

        if ThemeManager:
            try:
                table_group.setStyleSheet(status_group.styleSheet())
            except Exception:
                pass
        
        self.data_table = QTableWidget(0, 5)
        self.data_table.setHorizontalHeaderLabels([
            tr('number', '序号'),
            tr('game_x', '游戏X'),
            tr('game_y', '游戏Y'),
            tr('latitude', '纬度'),
            tr('longitude', '经度')
        ])
        # 隐藏左侧默认行号，避免占用宽度导致数据被裁剪
        self.data_table.verticalHeader().setVisible(False)

        # 列宽策略：前3列固定，后2列拉伸（给经纬度更多空间）
        header = self.data_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.data_table.setColumnWidth(0, 46)
        self.data_table.setColumnWidth(1, 78)
        self.data_table.setColumnWidth(2, 78)
        if ThemeManager:
            try:
                self.data_table.setStyleSheet(
                    ThemeManager.get_route_table_style()
                    + "QTableWidget::item { padding: 4px 6px; }"
                    + "QHeaderView::section { padding: 6px; }"
                )
            except Exception:
                pass
        table_layout.addWidget(self.data_table)
        
        # 组装右侧布局
        control_layout.addWidget(status_group)
        control_layout.addWidget(input_group)
        control_layout.addWidget(calib_group)
        control_layout.addWidget(table_group)
        control_layout.addStretch()
        
        # 组装主布局
        main_layout.addWidget(map_widget, stretch=3)
        main_layout.addWidget(control_widget, stretch=1)
        
        # 连接信号
        self.calib_btn1.clicked.connect(lambda: self.add_calibration_point(1))
        self.calib_btn2.clicked.connect(lambda: self.add_calibration_point(2))
        self.calib_btn3.clicked.connect(lambda: self.add_calibration_point(3))
        self.finish_btn.clicked.connect(self.finish_calibration)

    def setup_web_channel(self):
        # 为校准窗口创建独立的WebChannel和MapBackend
        self.backend = MapBackend(self)
        self.channel = QWebChannel(self.web_view.page())
        self.web_view.page().setWebChannel(self.channel)
        self.channel.registerObject("backend", self.backend)
        self.backend.statusUpdated.connect(self.on_map_status_updated)
        self.log("Calibration window created independent WebChannel")

    def load_map(self):
        # 校准窗口需要加载与主窗口相同的地图
        if self.current_map_url:
            map_url = self.current_map_url
            self.log(f"Calibration window loading current URL: {map_url}")
        else:
            if self.current_map_provider == tr('local_map', '本地地图'):
                map_url = "http://localhost:8000/index.html"
                self.log(f"Calibration window loading local map: {map_url}")
            elif self.current_map_provider in get_map_urls(self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN"):
                map_urls = get_map_urls(self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN")
                map_url = map_urls[self.current_map_provider]
                self.log(f"Calibration window loading default map: {self.current_map_provider} -> {map_url}")
            else:
                self.log(f"Error: Unknown map provider '{self.current_map_provider}'")
                return
        
        self.web_view.setUrl(QUrl(map_url))
        self.web_view.loadFinished.connect(self.on_load_finished)

    @Slot(bool)
    def on_load_finished(self, ok):
        if ok:
            self.log("Calibration map loaded, starting capture...")
            # 脚本已通过 WebProfile 自动注入
            QTimer.singleShot(500, self.start_capture)

    def start_capture(self):
        self.capture_timer = QTimer(self)
        self.capture_timer.timeout.connect(self.run_capture)
        self.capture_timer.start(500)
        self.capture_attempts = 0

    def run_capture(self):
        self.capture_attempts += 1

        if self.capture_attempts > 60:  # 30秒超时
            self.capture_status_label.setText(tr('capture_status_timeout', '捕获状态: 捕获超时!'))
            self.capture_timer.stop()
            return

        # 检查是否捕获成功
        check_script = "!!(window.discoveredMap && typeof window.discoveredMap.getCenter === 'function')"
        self.web_view.page().runJavaScript(check_script, self.on_capture_result)

    @Slot(object)
    def on_capture_result(self, success):
        if success:
            self.capture_status_label.setText("捕获状态: 捕获成功!")
            self.capture_timer.stop()
            # 通用脚本已经处理了事件监听，这里不需要额外部署
            self.log("校准窗口地图捕获成功")

    def deploy_listeners(self):
        #已弃用，由 JS_UNIVERSAL_INJECTOR 统一处理
        pass

    @Slot(float, float, int)
    def on_map_status_updated(self, lat, lng, zoom):
        self.current_lat = lat
        self.current_lng = lng
        self.current_zoom = zoom
        self.lat_lng_label.setText(f"经纬度: {lat:.6f}, {lng:.6f}")
        self.zoom_label.setText(f"缩放等级: {zoom}")

    def add_calibration_point(self, point_num):
        try:
            x = float(self.x_input.text())
            y = float(self.y_input.text())
        except ValueError:
            self._show_message("warning", "输入错误", "请输入有效的数值坐标!")
            return

        if self.current_lat == 0 and self.current_lng == 0:
            self._show_message("warning", "地图未就绪", "请等待地图加载完成!")
            return

        # 创建校准点
        point = CalibrationPoint(x, y, self.current_lat, self.current_lng)
        self.calibration_points.append(point)

        # 添加到表格
        row = self.data_table.rowCount()
        self.data_table.insertRow(row)
        self.data_table.setItem(row, 0, QTableWidgetItem(str(point_num)))
        self.data_table.setItem(row, 1, QTableWidgetItem(f"{x:.2f}"))
        self.data_table.setItem(row, 2, QTableWidgetItem(f"{y:.2f}"))
        # 使用4位小数，减少在窄面板中的文本裁剪
        self.data_table.setItem(row, 3, QTableWidgetItem(f"{self.current_lat:.4f}"))
        self.data_table.setItem(row, 4, QTableWidgetItem(f"{self.current_lng:.4f}"))

        # 清空输入框
        self.x_input.clear()
        self.y_input.clear()

        # 禁用当前按钮
        if point_num == 1:
            self.calib_btn1.setEnabled(False)
        elif point_num == 2:
            self.calib_btn2.setEnabled(False)
        elif point_num == 3:
            self.calib_btn3.setEnabled(False)

        # 检查是否可以完成校准
        if len(self.calibration_points) >= 2:
            self.finish_btn.setEnabled(True)

        self.log(f"已添加校准点 {point_num}: ({x}, {y}) -> ({self.current_lat:.6f}, {self.current_lng:.6f})")

    def finish_calibration(self):
        try:
            self.transform_matrix = CalibrationSystem.calculate_transform_matrix(self.calibration_points)
            
            # 发射校准完成信号
            self.calibrationFinished.emit(self.transform_matrix)
            
            self._show_message(
                "information",
                "校准完成",
                f"校准成功完成!\n使用了 {len(self.calibration_points)} 个校准点"
            )
            
            self.accept()
            
        except Exception as e:
            self._show_message("critical", "校准失败", f"校准计算失败: {str(e)}")

    def _show_message(self, level: str, title: str, text: str) -> None:
        """Theme-aware message dialog for calibration window."""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.setMinimumWidth(420)

        if level == "warning":
            msg.setIcon(QMessageBox.Icon.Warning)
        elif level == "critical":
            msg.setIcon(QMessageBox.Icon.Critical)
        else:
            msg.setIcon(QMessageBox.Icon.Information)

        try:
            from core.theme_manager import ThemeManager
            if ThemeManager.is_dark_theme():
                msg.setStyleSheet(
                    "QMessageBox { background-color: #2D2D2D; color: #EDEDED; }"
                    "QLabel { background-color: transparent; color: #EDEDED; }"
                    "QPushButton { min-width: 90px; min-height: 28px; }"
                )
        except Exception:
            pass

        msg.exec()

    def closeEvent(self, event):
        """重写关闭事件，正确清理资源"""
        try:
            # 停止捕获定时器
            if hasattr(self, 'capture_timer') and self.capture_timer:
                self.capture_timer.stop()
            
            # 清理独立页面资源
            if hasattr(self, 'web_view') and self.web_view:
                self.web_view.close()
            
            self.log("校准窗口关闭，清理资源完成")
        except Exception as e:
            self.log(f"关闭校准窗口时出错: {e}")
        
        super().closeEvent(event)

    def log(self, message):
        print(f"[校准窗口] {message}")
