#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路线列表对话框
用于查看、管理已录制的路线文件
"""

import os
from datetime import datetime
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                               QTableWidgetItem, QPushButton, QLabel, QMessageBox,
                               QHeaderView, QFileDialog, QTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, Slot
from route_recorder import RouteRecorder, RouteData


class RouteDetailDialog(QDialog):
    """路线详情对话框"""
    
    def __init__(self, route_data: RouteData, parent=None):
        super().__init__(parent)
        self.route_data = route_data
        self.setWindowTitle(f"路线详情 - {route_data.name}")
        self.setGeometry(200, 200, 600, 500)
        
        layout = QVBoxLayout(self)
        
        # 路线信息
        info_text = f"""路线名称: {route_data.name}
创建时间: {route_data.created_time}
开始时间: {route_data.start_time or '未知'}
结束时间: {route_data.end_time or '未知'}
录制时长: {route_data.duration}
坐标点数: {route_data.total_points}"""
        
        info_label = QLabel(info_text)
        info_label.setStyleSheet("font-family: monospace; background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6;")
        layout.addWidget(info_label)
        
        # 坐标点列表
        layout.addWidget(QLabel("坐标点详情:"))
        
        self.points_table = QTableWidget()
        self.points_table.setColumnCount(4)
        self.points_table.setHorizontalHeaderLabels(["时间", "X坐标", "Y坐标", "Z坐标"])
        
        # 填充数据
        self.points_table.setRowCount(len(route_data.points))
        for row, point in enumerate(route_data.points):
            self.points_table.setItem(row, 0, QTableWidgetItem(point.timestamp))
            self.points_table.setItem(row, 1, QTableWidgetItem(str(point.x)))
            self.points_table.setItem(row, 2, QTableWidgetItem(str(point.y)))
            self.points_table.setItem(row, 3, QTableWidgetItem(str(point.z)))
        
        # 调整列宽
        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.points_table)
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class RouteListDialog(QDialog):
    """路线列表对话框"""
    
    def __init__(self, route_recorder: RouteRecorder, parent=None):
        super().__init__(parent)
        self.route_recorder = route_recorder
        self.setWindowTitle("已录制的路线")
        self.setGeometry(150, 150, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("已录制的路线文件")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # 路线列表表格
        self.routes_table = QTableWidget()
        self.routes_table.setColumnCount(6)
        self.routes_table.setHorizontalHeaderLabels([
            "路线名称", "创建时间", "录制时长", "坐标点数", "文件大小", "文件路径"
        ])
        
        # 设置表格属性
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.setAlternatingRowColors(True)
        
        # 调整列宽
        header = self.routes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.routes_table)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self.load_routes)
        button_layout.addWidget(self.refresh_btn)
        
        self.view_detail_btn = QPushButton("查看详情")
        self.view_detail_btn.clicked.connect(self.view_route_detail)
        self.view_detail_btn.setEnabled(False)
        button_layout.addWidget(self.view_detail_btn)
        
        self.export_btn = QPushButton("导出路线")
        self.export_btn.clicked.connect(self.export_route)
        self.export_btn.setEnabled(False)
        button_layout.addWidget(self.export_btn)
        
        self.delete_btn = QPushButton("删除路线")
        self.delete_btn.clicked.connect(self.delete_route)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
        button_layout.addWidget(self.delete_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        # 状态标签
        self.status_label = QLabel("加载路线列表中...")
        layout.addWidget(self.status_label)
        
        # 连接表格选择事件
        self.routes_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        # 加载路线列表
        self.load_routes()
    
    def load_routes(self):
        """加载路线列表"""
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
            
            self.status_label.setText(f"找到 {len(route_files)} 个路线文件")
            
        except Exception as e:
            self.status_label.setText(f"加载失败: {e}")
            QMessageBox.critical(self, "错误", f"加载路线列表失败: {e}")
    
    def on_selection_changed(self):
        """选择改变时的处理"""
        has_selection = len(self.routes_table.selectedItems()) > 0
        self.view_detail_btn.setEnabled(has_selection)
        self.export_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
    
    def get_selected_filepath(self):
        """获取选中的文件路径"""
        current_row = self.routes_table.currentRow()
        if current_row >= 0:
            item = self.routes_table.item(current_row, 0)
            if item:
                return item.data(Qt.ItemDataRole.UserRole)
        return None
    
    def view_route_detail(self):
        """查看路线详情"""
        filepath = self.get_selected_filepath()
        if not filepath:
            return
        
        try:
            route_data = self.route_recorder.load_route(filepath)
            if route_data:
                detail_dialog = RouteDetailDialog(route_data, self)
                detail_dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载路线详情失败: {e}")
    
    def export_route(self):
        """导出路线"""
        filepath = self.get_selected_filepath()
        if not filepath:
            return
        
        try:
            route_data = self.route_recorder.load_route(filepath)
            if route_data:
                exported_path = self.route_recorder.export_route_to_custom_location(route_data, self)
                if exported_path:
                    QMessageBox.information(
                        self, 
                        "导出成功", 
                        f"路线已导出到:\n{exported_path}"
                    )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出路线失败: {e}")
    
    def delete_route(self):
        """删除路线"""
        filepath = self.get_selected_filepath()
        if not filepath:
            return
        
        current_row = self.routes_table.currentRow()
        route_name = self.routes_table.item(current_row, 0).text()
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除路线 '{route_name}' 吗？\n\n文件路径: {filepath}\n\n此操作无法撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(filepath)
                QMessageBox.information(self, "删除成功", f"路线 '{route_name}' 已删除")
                self.load_routes()  # 刷新列表
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"删除路线失败: {e}")
    
    def closeEvent(self, event):
        """关闭事件"""
        event.accept()