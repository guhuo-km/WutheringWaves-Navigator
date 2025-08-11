#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路线录制管理器
实现从录制按钮启动到停止按钮停止期间的路线录制功能
记录OCR识别的所有成功坐标数据并存储到JSON文件
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox, QFileDialog

# 多语言支持
try:
    from language_manager import get_language_manager, tr
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
    def tr(key, default=None, **kwargs):
        return default if default is not None else key


class RoutePoint:
    """路线点数据结构"""
    
    def __init__(self, x: int, y: int, z: int, timestamp: str = None):
        self.x = x
        self.y = y
        self.z = z
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RoutePoint':
        """从字典创建路线点"""
        return cls(data["x"], data["y"], data["z"], data.get("timestamp"))


class RouteData:
    """路线数据结构"""
    
    def __init__(self, name: str = None):
        self.name = name or f"路线_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.points: List[RoutePoint] = []
        self.total_points = 0
        self.duration = "00:00:00"
        self.start_time = None
        self.end_time = None
    
    def add_point(self, x: int, y: int, z: int):
        """添加路线点"""
        point = RoutePoint(x, y, z)
        self.points.append(point)
        self.total_points = len(self.points)
        
        # 更新时间信息
        if self.start_time is None:
            self.start_time = point.timestamp
        self.end_time = point.timestamp
        
        # 计算持续时间
        if self.start_time and self.end_time:
            try:
                start_dt = datetime.strptime(self.start_time, "%Y-%m-%d %H:%M:%S.%f")
                end_dt = datetime.strptime(self.end_time, "%Y-%m-%d %H:%M:%S.%f")
                duration_seconds = (end_dt - start_dt).total_seconds()
                
                hours = int(duration_seconds // 3600)
                minutes = int((duration_seconds % 3600) // 60)
                seconds = int(duration_seconds % 60)
                self.duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            except:
                self.duration = "00:00:00"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "route_info": {
                "name": self.name,
                "created_time": self.created_time,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "duration": self.duration,
                "total_points": self.total_points
            },
            "points": [point.to_dict() for point in self.points]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RouteData':
        """从字典创建路线数据"""
        route_info = data.get("route_info", {})
        route = cls(route_info.get("name"))
        route.created_time = route_info.get("created_time", route.created_time)
        route.start_time = route_info.get("start_time")
        route.end_time = route_info.get("end_time")
        route.duration = route_info.get("duration", "00:00:00")
        route.total_points = route_info.get("total_points", 0)
        
        # 加载路线点
        points_data = data.get("points", [])
        route.points = [RoutePoint.from_dict(point_data) for point_data in points_data]
        
        return route


class RouteRecorder(QObject):
    """路线录制管理器"""
    
    # 信号定义
    recording_started = Signal(str)  # 录制开始，参数：路线名称
    recording_stopped = Signal(str, int)  # 录制停止，参数：路线名称，点数
    point_recorded = Signal(int, int, int, int)  # 记录点，参数：x, y, z, 总点数
    error_occurred = Signal(str)  # 错误发生
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 录制状态
        self.is_recording = False
        self.current_route: Optional[RouteData] = None
        
        # 配置
        self.routes_dir = "recorded_routes"  # 路线存储目录
        self.ensure_routes_directory()
        
        # 统计信息
        self.last_point_time = None
        self.duplicate_filter_interval = 1.0  # 1秒内的重复点过滤
        
    def ensure_routes_directory(self):
        """确保路线存储目录存在"""
        if not os.path.exists(self.routes_dir):
            os.makedirs(self.routes_dir)
            print(f"创建路线存储目录: {self.routes_dir}")
    
    def start_recording(self, route_name: str = None) -> bool:
        """开始录制路线"""
        if self.is_recording:
            self.error_occurred.emit("已在录制中，请先停止当前录制")
            return False
        
        try:
            # 创建新路线
            self.current_route = RouteData(route_name)
            self.is_recording = True
            self.last_point_time = None
            
            self.recording_started.emit(self.current_route.name)
            print(f"开始录制路线: {self.current_route.name}")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"开始录制失败: {e}")
            return False
    
    def stop_recording(self) -> Optional[str]:
        """停止录制路线"""
        if not self.is_recording or not self.current_route:
            self.error_occurred.emit("当前没有在录制")
            return None
        
        try:
            # 保存路线数据
            filepath = self.save_route(self.current_route)
            route_name = self.current_route.name
            point_count = self.current_route.total_points
            
            # 重置状态
            self.is_recording = False
            self.current_route = None
            self.last_point_time = None
            
            self.recording_stopped.emit(route_name, point_count)
            print(f"录制完成: {route_name}, 共{point_count}个点, 保存至: {filepath}")
            return filepath
            
        except Exception as e:
            self.error_occurred.emit(f"停止录制失败: {e}")
            return None
    
    def record_point(self, x: int, y: int, z: int) -> bool:
        """记录坐标点"""
        if not self.is_recording or not self.current_route:
            return False
        
        try:
            current_time = datetime.now()
            
            # 重复点过滤
            if self.last_point_time:
                time_diff = (current_time - self.last_point_time).total_seconds()
                if time_diff < self.duplicate_filter_interval:
                    # 时间间隔太短，跳过
                    return False
            
            # 记录点
            self.current_route.add_point(x, y, z)
            self.last_point_time = current_time
            
            # 发送信号
            self.point_recorded.emit(x, y, z, self.current_route.total_points)
            
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"记录坐标点失败: {e}")
            return False
    
    def save_route(self, route_data: RouteData) -> str:
        """保存路线数据到JSON文件"""
        filename = f"{route_data.name}.json"
        # 清理文件名中的非法字符
        filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        filepath = os.path.join(self.routes_dir, filename)
        
        # 如果文件已存在，添加序号
        counter = 1
        original_filepath = filepath
        while os.path.exists(filepath):
            name_part = os.path.splitext(original_filepath)[0]
            filepath = f"{name_part}_{counter}.json"
            counter += 1
        
        # 保存数据
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(route_data.to_dict(), f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def load_route(self, filepath: str) -> Optional[RouteData]:
        """从JSON文件加载路线数据"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return RouteData.from_dict(data)
        except Exception as e:
            self.error_occurred.emit(f"加载路线文件失败: {e}")
            return None
    
    def get_recording_status(self) -> Dict[str, Any]:
        """获取录制状态信息"""
        if not self.is_recording or not self.current_route:
            return {
                "is_recording": False,
                "route_name": None,
                "point_count": 0,
                "duration": "00:00:00"
            }
        
        return {
            "is_recording": True,
            "route_name": self.current_route.name,
            "point_count": self.current_route.total_points,
            "duration": self.current_route.duration
        }
    
    def list_recorded_routes(self) -> List[str]:
        """列出已录制的路线文件"""
        try:
            files = []
            for filename in os.listdir(self.routes_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.routes_dir, filename)
                    files.append(filepath)
            return sorted(files, key=os.path.getmtime, reverse=True)  # 按修改时间倒序
        except Exception as e:
            self.error_occurred.emit(f"列出路线文件失败: {e}")
            return []
    
    def get_route_summary(self, filepath: str) -> Optional[Dict[str, Any]]:
        """获取路线文件摘要信息"""
        try:
            route_data = self.load_route(filepath)
            if route_data:
                return {
                    "filepath": filepath,
                    "filename": os.path.basename(filepath),
                    "name": route_data.name,
                    "created_time": route_data.created_time,
                    "duration": route_data.duration,
                    "point_count": route_data.total_points,
                    "file_size": f"{os.path.getsize(filepath) / 1024:.1f} KB"
                }
        except Exception as e:
            self.error_occurred.emit(f"获取路线摘要失败: {e}")
        return None
    
    def export_route_to_custom_location(self, route_data: RouteData, parent_widget=None) -> Optional[str]:
        """导出路线到用户指定位置"""
        try:
            # 打开文件保存对话框
            filename, _ = QFileDialog.getSaveFileName(
                parent_widget,
                "保存路线文件",
                f"{route_data.name}.json",
                "JSON files (*.json);;All files (*.*)"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(route_data.to_dict(), f, ensure_ascii=False, indent=2)
                return filename
            
        except Exception as e:
            self.error_occurred.emit(f"导出路线失败: {e}")
        
        return None
    
    def cleanup(self):
        """清理资源"""
        if self.is_recording:
            self.stop_recording()
        print("路线录制器资源已清理")