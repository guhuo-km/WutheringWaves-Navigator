# 鸣潮地图导航系统 (WutheringWaves Navigator)

一个基于 PySide6 + QWebEngineView 开发的《鸣潮》游戏地图导航和校准系统，支持在线地图和本地地图的实时同步、坐标转换和精确导航。

## ✨ 核心功能

### 🗺️ 双模式地图支持
- **在线地图模式**: 支持官方地图和光环助手地图
- **本地地图模式**: 支持自定义地图瓦片和图片

### 🎯 地图校准系统
- **多点校准**: 支持2-3个校准点的仿射变换
- **数据持久化**: 自动保存和加载校准数据
- **坐标转换**: 游戏坐标到地理坐标的精确转换

### 🚀 实时同步功能
- **WebSocket通信**: 多客户端地图状态实时同步
- **状态管理**: 地图位置、缩放级别实时共享
- **远程控制**: 通过Web控制面板远程操作地图

### 🔧 高级功能
- **登录状态持久化**: 支持Cookie和会话自动保存
- **地图生成工具**: 自动将大图片切分为瓦片
- **稳健的错误处理**: 完善的异常捕获和恢复机制

## 📁 项目结构

```
地图校准与跳转模块/
├── main_app.py              # 主程序入口 - PySide6 GUI应用
├── server.py                # Flask WebSocket后端服务器
├── tile_generator.py        # 地图瓦片生成工具
├── index.html               # 本地地图客户端页面
├── calibration_data.json    # 校准数据存储
├── maps.json                # 地图配置文件
├── login_history.json       # 登录历史记录
├── images/                  # 普通地图图片目录
├── tiles/                   # 瓦片地图目录
└── web_profile/             # 浏览器配置文件存储
```

## 🚀 快速开始

### 环境要求

```bash
Python 3.8+
pip install PySide6 Flask flask-sock Pillow numpy
```

### 启动步骤

1. **运行主程序**
   ```bash
   python main_app.py
   ```

2. **添加本地地图** (可选)
   ```bash
   python tile_generator.py your_map_image.jpg
   ```

3. **使用**
   - 选择在线或本地地图模式
   - 进行地图校准（设置校准点）
   - 使用坐标跳转功能

## 📚 API 和集成指南

### 🔌 将地图导航功能集成到你的程序

#### 方案1: 直接使用核心类

```python
from main_app import CalibrationSystem, CalibrationDataManager, TransformMatrix, CalibrationPoint

# 1. 创建校准管理器
calibration_mgr = CalibrationDataManager()

# 2. 创建校准点 (游戏坐标 -> 地理坐标)
points = [
    CalibrationPoint(x=1000, y=2000, lat=31.123456, lon=121.654321),
    CalibrationPoint(x=1500, y=2500, lat=31.133456, lon=121.664321),
    CalibrationPoint(x=2000, y=3000, lat=31.143456, lon=121.674321)
]

# 3. 计算变换矩阵
transform_matrix = CalibrationSystem.calculate_transform_matrix(points)

# 4. 保存校准数据
calibration_mgr.save_calibration('online', 'official_map', transform_matrix, 'area_8')

# 5. 坐标转换
game_x, game_y = 1750, 2750
lat, lon = CalibrationSystem.transform(game_x, game_y, transform_matrix)
print(f"游戏坐标 ({game_x}, {game_y}) -> 地理坐标 ({lat:.6f}, {lon:.6f})")
```

#### 方案2: 使用本地服务器API

```python
from main_app import LocalServerManager
import requests
import json

# 1. 启动本地服务器
server_mgr = LocalServerManager()
server_mgr.start_servers()

# 2. 通过WebSocket发送指令
command = {
    "type": "jumpTo",
    "lat": 31.123456,
    "lng": 121.654321
}
server_mgr.broadcast_command(command)

# 3. 获取地图列表
maps = server_mgr.get_local_maps()
print(f"可用地图: {maps}")
```

#### 方案3: 嵌入式WebView组件

```python
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl
from main_app import MapBackend, QWebChannel

class MyMapWidget(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        # 创建WebView
        self.web_view = QWebEngineView()
        
        # 设置后端通信
        self.backend = MapBackend(self)
        self.channel = QWebChannel()
        self.web_view.page().setWebChannel(self.channel)
        self.channel.registerObject("backend", self.backend)
        
        # 加载地图页面
        self.web_view.setUrl(QUrl("http://localhost:8000/index.html"))
        
        # 设置布局
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.web_view)
        self.setCentralWidget(widget)

# 使用示例
app = QApplication([])
map_widget = MyMapWidget()
map_widget.show()
app.exec()
```

### 🔧 地图生成工具集成

```python
from tile_generator import process_image, get_image_info, update_map_config

# 1. 处理地图图片
def add_custom_map(image_path):
    try:
        # 获取图片信息
        file_size_mb, width, height = get_image_info(image_path)
        print(f"图片尺寸: {width}x{height}, 大小: {file_size_mb:.2f}MB")
        
        # 处理图片（自动决定是否需要瓦片化）
        process_image(image_path)
        print("地图添加成功!")
        
    except Exception as e:
        print(f"地图添加失败: {e}")

# 使用示例
add_custom_map("my_game_map.jpg")
```

### 📡 WebSocket通信协议

#### 消息格式

```python
# 地图状态更新
{
    "type": "stateUpdate",
    "lat": 31.123456,
    "lng": 121.654321,
    "zoom": 2
}

# 地图切换
{
    "type": "mapChange", 
    "mapName": "map1-41mb",
    "lat": 0,
    "lng": 0,
    "zoom": 0
}

# 移动指令
{
    "type": "panBy",
    "x": 50,    # 可选
    "y": -50    # 可选
}

# 缩放指令
{
    "type": "zoomIn"    # 或 "zoomOut"
}

# 跳转指令
{
    "type": "jumpTo",
    "lat": 31.123456,
    "lng": 121.654321
}
```

#### WebSocket客户端示例

```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(f"收到消息: {data}")

def on_open(ws):
    # 发送地图切换指令
    command = {
        "type": "mapChange",
        "mapName": "my_custom_map"
    }
    ws.send(json.dumps(command))

# 连接到WebSocket服务器
ws = websocket.WebSocketApp("ws://localhost:8080/ws",
                           on_message=on_message,
                           on_open=on_open)
ws.run_forever()
```

## 🎮 实际应用示例

### 游戏助手集成

```python
class GameAssistant:
    def __init__(self):
        self.calibration_mgr = CalibrationDataManager()
        self.server_mgr = LocalServerManager()
        self.transform_matrix = None
        
    def initialize_map(self, map_name):
        """初始化地图"""
        # 加载校准数据
        self.transform_matrix = self.calibration_mgr.load_calibration(
            'local', map_name
        )
        
        if not self.transform_matrix:
            print("警告: 未找到校准数据，请先进行地图校准")
            return False
            
        # 启动服务器
        return self.server_mgr.start_servers()
    
    def navigate_to_target(self, game_x, game_y):
        """导航到游戏坐标"""
        if not self.transform_matrix:
            print("错误: 地图未校准")
            return
            
        # 转换坐标
        lat, lon = CalibrationSystem.transform(game_x, game_y, self.transform_matrix)
        
        # 发送跳转指令
        command = {"type": "jumpTo", "lat": lat, "lng": lon}
        self.server_mgr.broadcast_command(command)
        
        print(f"导航到: ({game_x}, {game_y}) -> ({lat:.6f}, {lon:.6f})")
    
    def cleanup(self):
        """清理资源"""
        self.server_mgr.stop_servers()

# 使用示例
assistant = GameAssistant()
if assistant.initialize_map("my_game_map"):
    assistant.navigate_to_target(1500, 2000)
    assistant.cleanup()
```

### 自动寻路系统集成

```python
class PathFinder:
    def __init__(self, game_assistant):
        self.assistant = game_assistant
        
    def follow_path(self, waypoints, delay=2.0):
        """沿路径点自动导航"""
        import time
        
        for i, (x, y) in enumerate(waypoints):
            print(f"导航到路径点 {i+1}/{len(waypoints)}: ({x}, {y})")
            self.assistant.navigate_to_target(x, y)
            
            if i < len(waypoints) - 1:  # 不是最后一个点
                time.sleep(delay)

# 使用示例
waypoints = [(1000, 1000), (1500, 1500), (2000, 2000)]
pathfinder = PathFinder(assistant)
pathfinder.follow_path(waypoints)
```

## ⚙️ 配置和自定义

### 自定义地图源

在 `main_app.py` 中修改 `MAP_URLS` 字典：

```python
MAP_URLS = {
    "官方地图": "https://www.kurobbs.com/mc/map",
    "光环助手": "https://www.ghzs666.com/wutheringwaves-map#/?map=default",
    "自定义地图": "https://your-custom-map-url.com"
}
```

### 调整校准精度

修改校准系统参数：

```python
# 在 CalibrationSystem 类中
@staticmethod
def calculate_transform_matrix(points, method='lstsq'):
    # 可以选择不同的拟合方法
    # method: 'lstsq' (最小二乘), 'ridge' (岭回归), 'lasso' (套索回归)
    pass
```

### 性能优化配置

```python
# 在 tile_generator.py 中调整参数
TILE_SIZE = 256          # 瓦片大小
MAX_IMAGE_SIZE_MB = 12   # 最大图片大小
MAX_DIMENSION = 8192     # 最大尺寸
```

## 🐛 故障排除

### 常见问题

1. **WebView不显示**
   - 检查是否安装了完整的Qt WebEngine
   - 确认网络连接正常

2. **服务器启动失败**
   - 检查端口8080和8000是否被占用
   - 确认防火墙设置

3. **校准数据丢失**
   - 检查 `calibration_data.json` 文件权限
   - 确认程序有写入权限

4. **地图加载失败**
   - 检查 `maps.json` 格式是否正确
   - 确认地图文件是否存在

### 调试模式

启用详细日志：

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 在主程序中添加
main_window = MapCalibrationMainWindow()
main_window.log("调试模式已启用")
```

## 📄 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 联系方式

如有问题或建议，请通过以下方式联系：
- GitHub Issues
- 项目讨论区

---

**注意**: 本项目仅供学习和研究使用，请遵守游戏相关条款和法律法规。