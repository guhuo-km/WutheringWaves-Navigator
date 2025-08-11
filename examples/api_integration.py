#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API集成示例
演示如何将WutheringWaves Navigator集成到其他应用中
"""

import sys
import os
import json
import time
import threading
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import LocalServerManager, CalibrationDataManager


class GameAssistant:
    """游戏助手示例类"""
    
    def __init__(self):
        self.calibration_mgr = CalibrationDataManager()
        self.server_mgr = LocalServerManager()
        self.transform_matrix = None
        self.running = False
        
    def initialize_map(self, map_name):
        """初始化地图"""
        print(f"初始化地图: {map_name}")
        
        # 加载校准数据
        self.transform_matrix = self.calibration_mgr.load_calibration('local', map_name)
        
        if not self.transform_matrix:
            print("警告: 未找到校准数据，请先进行地图校准")
            return False
            
        # 启动服务器
        success = self.server_mgr.start_servers()
        if success:
            print("服务器启动成功")
            self.running = True
        return success
    
    def navigate_to_target(self, game_x, game_y):
        """导航到游戏坐标"""
        if not self.transform_matrix:
            print("错误: 地图未校准")
            return
            
        from main_app import CalibrationSystem
        
        # 转换坐标
        lat, lon = CalibrationSystem.transform(game_x, game_y, self.transform_matrix)
        
        # 发送跳转指令
        command = {"type": "jumpTo", "lat": lat, "lng": lon}
        self.server_mgr.broadcast_command(command)
        
        print(f"导航到: ({game_x}, {game_y}) -> ({lat:.6f}, {lon:.6f})")
    
    def follow_path(self, waypoints, delay=2.0):
        """沿路径点自动导航"""
        print(f"开始路径导航，共{len(waypoints)}个点")
        
        for i, (x, y) in enumerate(waypoints):
            if not self.running:
                break
                
            print(f"导航到路径点 {i+1}/{len(waypoints)}: ({x}, {y})")
            self.navigate_to_target(x, y)
            
            if i < len(waypoints) - 1:  # 不是最后一个点
                time.sleep(delay)
                
        print("路径导航完成")
    
    def get_map_list(self):
        """获取可用地图列表"""
        return self.server_mgr.get_local_maps()
    
    def switch_map(self, map_name):
        """切换地图"""
        command = {"type": "mapChange", "mapName": map_name}
        self.server_mgr.broadcast_command(command)
        print(f"切换到地图: {map_name}")
    
    def cleanup(self):
        """清理资源"""
        self.running = False
        self.server_mgr.stop_servers()
        print("游戏助手已清理")


def websocket_client_example():
    """WebSocket客户端示例"""
    print("\n=== WebSocket客户端示例 ===")
    
    try:
        import websocket
        
        def on_message(ws, message):
            data = json.loads(message)
            print(f"收到消息: {data}")
        
        def on_open(ws):
            print("WebSocket连接已建立")
            # 发送地图切换指令
            command = {
                "type": "mapChange",
                "mapName": "example_map"
            }
            ws.send(json.dumps(command))
        
        def on_error(ws, error):
            print(f"WebSocket错误: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            print("WebSocket连接已关闭")
        
        # 连接到WebSocket服务器
        ws = websocket.WebSocketApp("ws://localhost:8080/ws",
                                   on_message=on_message,
                                   on_open=on_open,
                                   on_error=on_error,
                                   on_close=on_close)
        
        # 在后台线程中运行
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        return ws
        
    except ImportError:
        print("WebSocket客户端需要安装 websocket-client 包")
        print("pip install websocket-client")
        return None


def main():
    """主函数示例"""
    # 创建游戏助手实例
    assistant = GameAssistant()
    
    try:
        # 初始化地图（使用示例地图）
        if assistant.initialize_map("example_map"):
            
            # 单点导航示例
            assistant.navigate_to_target(1500, 2000)
            time.sleep(1)
            
            # 路径导航示例
            waypoints = [
                (1000, 1000),
                (1500, 1500), 
                (2000, 2000),
                (2500, 2500)
            ]
            assistant.follow_path(waypoints, delay=1.0)
            
            # 地图切换示例
            maps = assistant.get_map_list()
            print(f"可用地图: {maps}")
            
            if maps:
                assistant.switch_map(maps[0])
            
            # WebSocket客户端示例
            ws_client = websocket_client_example()
            
            # 保持运行一段时间
            print("运行中...（按Ctrl+C退出）")
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("用户中断")
    except Exception as e:
        print(f"运行出错: {e}")
    finally:
        # 清理资源
        assistant.cleanup()


if __name__ == "__main__":
    print("=== WutheringWaves Navigator API集成示例 ===")
    main()