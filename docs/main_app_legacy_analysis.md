# main_app_legacy.py 完整解析文档

> 本文档深入分析旧版 `src/main_app_legacy.py`（4351行）的完整架构，作为UI重构参考。

---

## 目录

1. [文件概述](#1-文件概述)
2. [类结构总览](#2-类结构总览)
3. [数据类与核心逻辑类](#3-数据类与核心逻辑类)
4. [UI类详细解析](#4-ui类详细解析)
   - [DisclaimerDialog](#41-disclaimerdialog-免责声明对话框)
   - [CalibrationWindow](#42-calibrationwindow-校准窗口)
   - [MapCalibrationMainWindow](#43-mapcalibrationmainwindow-主窗口)
   - [MapManagerDialog](#44-mapmanagerdialog-地图管理器)
5. [信号槽系统](#5-信号槽系统)
6. [功能模块分析](#6-功能模块分析)
7. [外部依赖模块](#7-外部依赖模块)
8. [WebChannel通信](#8-webchannel通信)
9. [配置与持久化](#9-配置与持久化)

---

## 1. 文件概述

### 基本信息
- **文件路径**: `src/main_app_legacy.py`
- **总行数**: 4351行
- **主要职责**: 集成UI初始化、多线程管理、网络请求代理、WebChannel通信和复杂的事件信号链路

### 核心架构
该文件是典型的**信号驱动混合架构**应用，核心逻辑围绕**坐标同步**展开：
1. **OCR模块** - 从游戏画面中"抓取"原始数据
2. **校准模块** - 建立"游戏坐标"到"地图经纬度"的数学映射
3. **WebChannel** - 充当桥梁，将计算后的经纬度实时推送给地图前端
4. **服务器管理** - 允许应用在无互联网环境下加载本地瓦片图

---

## 2. 类结构总览

```
main_app_legacy.py
├── 数据类
│   ├── CalibrationPoint          # 校准点数据结构
│   └── TransformMatrix           # 变换矩阵
├── 核心逻辑类
│   ├── CalibrationSystem         # 校准系统（静态方法）
│   ├── CalibrationDataManager    # 校准数据管理器
│   └── LocalServerManager        # 本地服务器管理
├── Web相关类
│   ├── CustomWebEnginePage       # 自定义WebPage（捕获JS日志）
│   └── MapBackend                # WebChannel后端通信
├── 工作线程类
│   └── MapGeneratorWorker        # 地图生成工作线程
└── UI类
    ├── DisclaimerDialog          # 免责声明对话框
    ├── CalibrationWindow         # 校准窗口
    ├── MapCalibrationMainWindow  # 主窗口（核心）
    └── MapManagerDialog          # 地图管理器对话框
```

---

## 3. 数据类与核心逻辑类

### 3.1 CalibrationPoint（校准点）
```python
class CalibrationPoint:
    """校准点数据结构"""
    def __init__(self, x, y, lat, lon):
        self.x = x      # 游戏X坐标
        self.y = y      # 游戏Y坐标
        self.lat = lat  # 纬度
        self.lon = lon  # 经度
```

### 3.2 TransformMatrix（变换矩阵）
```python
class TransformMatrix:
    """仿射变换矩阵 - 用于游戏坐标到地理坐标的转换"""
    def __init__(self, a=0, b=0, c=0, d=0, e=0, f=0):
        # lat = a*x + b*y + c
        self.a = a
        self.b = b
        self.c = c
        # lon = d*x + e*y + f
        self.d = d
        self.e = e
        self.f = f
```

### 3.3 CalibrationSystem（校准系统）
```python
class CalibrationSystem:
    """地图校准系统核心逻辑"""
    
    @staticmethod
    def calculate_transform_matrix(points) -> TransformMatrix:
        """基于校准点计算仿射变换矩阵（最小二乘法）"""
        # 构建线性方程组 Ax = b
        # 使用 np.linalg.lstsq 求解
        
    @staticmethod
    def transform(x, y, matrix) -> tuple[float, float]:
        """使用变换矩阵将游戏坐标转换为地理坐标"""
        lat = matrix.a * x + matrix.b * y + matrix.c
        lon = matrix.d * x + matrix.e * y + matrix.f
        return lat, lon
```

### 3.4 CalibrationDataManager（校准数据管理）
```python
class CalibrationDataManager:
    """校准数据持久化管理"""
    
    def __init__(self):
        self.calibration_file = "calibration_data.json"
    
    def get_map_key(mode, provider_or_map_name, area_id=None) -> str
    def load_all_calibrations() -> dict
    def save_calibration(mode, provider_or_map_name, matrix, area_id=None) -> bool
    def load_calibration(mode, provider_or_map_name, area_id=None) -> TransformMatrix
    def has_calibration(mode, provider_or_map_name, area_id=None) -> bool
    def delete_calibration(mode, provider_or_map_name, area_id=None) -> bool
```

### 3.5 LocalServerManager（本地服务器管理）
```python
class LocalServerManager:
    """本地HTTP文件服务器管理（端口58427）"""
    
    def start_servers() -> bool
    def stop_servers()
    def is_running() -> bool
    def get_local_maps() -> list[str]
```

---

## 4. UI类详细解析

### 4.1 DisclaimerDialog（免责声明对话框）

**继承**: `QDialog`

**控件列表**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `title_label` | `BodyLabel` | 标题："欢迎使用《呜呜大地图》！" | - |
| `content_label` | `BodyLabel` | 免责声明内容（支持HTML样式） | - |
| `cancel_btn` | `PushButton` | "拒绝条款" | `clicked` → `self.reject` |
| `accept_btn` | `PrimaryPushButton` | "同意条款" | `clicked` → `self.accept` |

**布局结构**:
```
QVBoxLayout (主布局)
├── title_label
├── content_label
└── QHBoxLayout (按钮布局)
    ├── cancel_btn
    └── accept_btn
```

---

### 4.2 CalibrationWindow（校准窗口）

**继承**: `QDialog`  
**行号**: 696-999

**自定义信号**:
```python
calibrationFinished = Signal(object)  # 传递 TransformMatrix
```

**控件列表**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `crosshair_label` | `BodyLabel` | 红色"+"十字准星 | - |
| `web_view` | `QWebEngineView` | 地图视图 | `loadFinished` → `on_load_finished` |
| `capture_status_label` | `BodyLabel` | 捕获状态显示 | - |
| `lat_lng_label` | `BodyLabel` | 经纬度显示 | - |
| `zoom_label` | `BodyLabel` | 缩放等级显示 | - |
| `x_input` | `LineEdit` | 游戏X坐标输入 | - |
| `y_input` | `LineEdit` | 游戏Y坐标输入 | - |
| `calib_btn1` | `PushButton` | "设定校准点 1" | `clicked` → `lambda: add_calibration_point(1)` |
| `calib_btn2` | `PushButton` | "设定校准点 2" | `clicked` → `lambda: add_calibration_point(2)` |
| `calib_btn3` | `PushButton` | "设定校准点 3" | `clicked` → `lambda: add_calibration_point(3)` |
| `finish_btn` | `PushButton` | "计算并完成校准" | `clicked` → `finish_calibration` |
| `data_table` | `QTableWidget` | 校准数据表格（5列） | - |

**布局结构**:
```
QHBoxLayout (主布局)
├── 左侧: QGridLayout (地图区域)
│   ├── QVBoxLayout
│   │   └── web_view
│   └── crosshair_label (叠加在中心)
└── 右侧: QVBoxLayout (控制面板，固定宽度350px)
    ├── QGroupBox "地图状态"
    │   └── QVBoxLayout
    │       ├── capture_status_label
    │       ├── lat_lng_label
    │       └── zoom_label
    ├── QGroupBox "游戏坐标输入"
    │   └── QGridLayout
    │       ├── BodyLabel "X坐标:" + x_input
    │       └── BodyLabel "Y坐标:" + y_input
    ├── QGroupBox "校准操作"
    │   └── QVBoxLayout
    │       ├── calib_btn1
    │       ├── calib_btn2
    │       ├── calib_btn3
    │       └── finish_btn
    └── QGroupBox "校准数据"
        └── QVBoxLayout
            └── data_table
```

**关键方法**:
| 方法名 | 功能 |
|--------|------|
| `setup_ui()` | 初始化UI布局 |
| `setup_web_channel()` | 创建独立WebChannel和MapBackend |
| `load_map()` | 加载与主窗口相同的地图 |
| `start_capture()` | 启动地图实例捕获定时器 |
| `add_calibration_point(n)` | 添加校准点到表格 |
| `finish_calibration()` | 计算变换矩阵并发射信号 |

---

### 4.3 MapCalibrationMainWindow（主窗口）

**继承**: `QMainWindow`  
**行号**: 1001-4100+

**默认快捷键配置**:
```python
DEFAULT_HOTKEYS = {
    "toggle_ocr": "",        # 切换OCR识别
    "toggle_recording": "",  # 切换路线录制
    "mark_next": "",         # 标记下一个
    "undo": ""               # 撤销
}
```

#### 4.3.1 控件分类列表

**顶部控制区（top_layout）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `language_combo` | `ComboBox` | 语言选择 | `currentTextChanged` → `on_language_combo_changed` |
| `radio_online` | `QRadioButton` | "在线地图"模式 | `buttonClicked` → `on_mode_changed` |
| `radio_local` | `QRadioButton` | "本地地图"模式 | `buttonClicked` → `on_mode_changed` |
| `radio_kuro` | `QRadioButton` | "官方地图" | `buttonClicked` → `load_current_map` |
| `radio_ghzs` | `QRadioButton` | "光环助手" | `buttonClicked` → `load_current_map` |
| `add_map_btn` | `PushButton` | "添加地图" | `clicked` → `add_local_maps` |
| `delete_map_btn` | `PushButton` | "管理地图" | `clicked` → `open_map_manager` |

**状态信息区（status_layout）**:
| 控件名 | 类型 | 功能 |
|--------|------|------|
| `status_label` | `BodyLabel` | 系统状态显示 |
| `url_status_label` | `BodyLabel` | 当前地图/区域显示 |
| `map_status_label` | `BodyLabel` | 实时状态（经纬度、缩放） |

**地图控制面板（map_control_group）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `up_btn` | `PushButton` | "↑ 向北" | `clicked` → `pan_map_direction("north")` |
| `down_btn` | `PushButton` | "↓ 向南" | `clicked` → `pan_map_direction("south")` |
| `left_btn` | `PushButton` | "← 向西" | `clicked` → `pan_map_direction("west")` |
| `right_btn` | `PushButton` | "→ 向东" | `clicked` → `pan_map_direction("east")` |
| `zoom_in_btn` | `PushButton` | "放大 (+)" | `clicked` → `zoom_in_map` |
| `zoom_out_btn` | `PushButton` | "缩小 (-)" | `clicked` → `zoom_out_map` |
| `recapture_btn` | `PushButton` | "强制重捕获" | `clicked` → `trigger_capture_sequence` |

**坐标定位面板（coord_group）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `x_coord_input` | `LineEdit` | 游戏X坐标输入 | - |
| `y_coord_input` | `LineEdit` | 游戏Y坐标输入 | - |
| `jump_btn` | `PushButton` | "跳转到坐标" | `clicked` → `jump_to_coordinates` |

**校准功能面板（calib_group）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `ocr_control_btn` | `PushButton` | "OCR坐标识别" | `clicked` → `show_ocr_control_panel` |
| `toggle_ocr_btn` | `PushButton` | "开始识别"/"停止识别" | `clicked` → `toggle_ocr_recognition` |
| `ocr_region_btn` | `PushButton` | "校准OCR区域" | `clicked` → `setup_ocr_region` |
| `ocr_status_label` | `BodyLabel` | OCR状态显示 | - |
| `circle_size_spinbox` | `SpinBox` | 圆点大小（1-50px） | `valueChanged` → `on_circle_size_changed` |
| `z_color_mapping_checkbox` | `CheckBox` | Z轴颜色映射开关 | `toggled` → `on_z_color_mapping_toggled` |
| `overlay_visible_checkbox` | `CheckBox` | 显示中心圆点 | `toggled` → `on_overlay_visibility_toggled` |
| `calibration_status_label` | `BodyLabel` | 校准状态显示 | - |
| `calib_auto_radio` | `QRadioButton` | "自动获取" | `buttonClicked` → `on_calibration_mode_changed` |
| `calib_manual_radio` | `QRadioButton` | "手动校准" | `buttonClicked` → `on_calibration_mode_changed` |
| `calibration_btn` | `PushButton` | "启动地图校准" | `clicked` → `open_calibration_window` |
| `current_position_label` | `BodyLabel` | 当前位置显示 | - |

**路线录制面板（recording_group）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `route_name_input` | `LineEdit` | 路线名称输入 | - |
| `toggle_recording_btn` | `PushButton` | "开始录制"/"停止录制" | `clicked` → `toggle_route_recording` |
| `view_routes_btn` | `PushButton` | "查看路线" | `clicked` → `show_recorded_routes` |
| `open_routes_folder_btn` | `PushButton` | "打开路线文件夹" | `clicked` → `open_routes_folder` |
| `recording_status_label` | `BodyLabel` | 录制状态显示 | - |

**窗口控制面板（window_control_group）**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `map_topmost_checkbox` | `CheckBox` | "地图顶置" | `toggled` → `toggle_map_topmost` |
| `map_passthrough_checkbox` | `CheckBox` | "鼠标穿透" | `toggled` → `toggle_map_passthrough` |
| `map_frameless_checkbox` | `CheckBox` | "无边框模式" | `toggled` → `toggle_map_frameless` |
| `main_topmost_checkbox` | `CheckBox` | "主界面顶置" | `toggled` → `toggle_main_topmost` |
| `map_opacity_slider` | `Slider` | 透明度滑块（10-100%） | `valueChanged` → `on_map_opacity_changed` |
| `map_opacity_label` | `BodyLabel` | 透明度百分比显示 | - |

**快捷键配置区**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `hotkey_toggle_ocr_label` | `BodyLabel` | 切换识别快捷键显示 | - |
| `hotkey_toggle_rec_label` | `BodyLabel` | 切换录制快捷键显示 | - |
| `hotkey_mark_next_label` | `BodyLabel` | 标记下一个快捷键显示 | - |
| `hotkey_undo_label` | `BodyLabel` | 撤销快捷键显示 | - |
| `hotkey_config_btn` | `PushButton` | "自定义快捷键" | `clicked` → `show_hotkey_config_dialog` |

**日志区域**:
| 控件名 | 类型 | 功能 |
|--------|------|------|
| `log_area` | `TextEdit` | 事件日志显示（只读，最大高度200px） |

**Web视图**:
| 控件名 | 类型 | 功能 | 信号连接 |
|--------|------|------|----------|
| `web_view` | `QWebEngineView` | 地图显示 | `urlChanged` → `on_url_changed` |
| `web_page` | `CustomWebEnginePage` | 自定义页面 | `loadFinished` → `on_page_load_finished` |
| `web_profile` | `QWebEngineProfile` | 持久化配置 | `downloadRequested` → `on_download_requested` |

#### 4.3.2 布局结构

```
QMainWindow
└── central_widget (QWidget)
    └── main_layout (QVBoxLayout)
        ├── top_layout (QHBoxLayout)
        │   ├── language_group (QGroupBox "语言")
        │   │   └── language_combo
        │   ├── mode_group (QGroupBox "模式选择")
        │   │   ├── radio_online
        │   │   └── radio_local
        │   ├── online_map_group (QGroupBox "在线地图源")
        │   │   ├── radio_kuro
        │   │   └── radio_ghzs
        │   ├── local_map_group (QGroupBox "本地地图") [默认隐藏]
        │   │   ├── add_map_btn
        │   │   └── delete_map_btn
        │   └── stretch
        ├── status_layout (QHBoxLayout)
        │   ├── status_label
        │   └── url_status_label
        ├── map_status_label
        ├── control_layout (QHBoxLayout)
        │   ├── window_control_group (QGroupBox "窗口与捕获控制")
        │   │   └── QGridLayout
        │   │       ├── recapture_btn
        │   │       ├── checkbox_layout (QHBoxLayout) [4个CheckBox]
        │   │       ├── opacity_layout (QHBoxLayout)
        │   │       ├── hotkey_info_label
        │   │       ├── hotkey_display_layout (QGridLayout) [快捷键显示]
        │   │       └── hotkey_config_btn
        │   └── calib_group (QGroupBox "校准功能")
        │       └── QVBoxLayout
        │           ├── ocr_control_btn
        │           ├── toggle_ocr_btn
        │           ├── ocr_region_btn
        │           ├── ocr_status_label
        │           ├── overlay_group (QGroupBox "中心圆点设置")
        │           ├── calib_status_layout (QHBoxLayout) [校准模式选择]
        │           ├── calibration_btn
        │           ├── current_position_label
        │           ├── recording_group (QGroupBox "路线录制")
        │           └── login_status_btn
        └── log_layout (QVBoxLayout)
            ├── BodyLabel "捕获与事件日志:"
            └── log_area
```

#### 4.3.3 关键方法列表

| 方法名 | 功能 | 行号 |
|--------|------|------|
| `__init__()` | 初始化所有管理器和UI | 1013 |
| `setup_ui()` | 构建完整UI布局 | 1481 |
| `setup_persistent_login_system()` | 设置登录状态持久化 | 1890 |
| `setup_script_injection()` | 配置Greasemonkey脚本注入 | 1933 |
| `setup_web_channel()` | 设置QWebChannel | 2593 |
| `connect_signals()` | 连接所有信号槽 | 2635 |
| `on_mode_changed()` | 在线/本地模式切换处理 | 2737 |
| `load_current_map()` | 加载当前选择的地图 | 2793 |
| `trigger_capture_sequence()` | 启动地图捕获序列 | 2964 |
| `open_calibration_window()` | 打开校准窗口 | 3137 |
| `toggle_ocr_recognition()` | 切换OCR识别状态 | 3474 |
| `toggle_route_recording()` | 切换路线录制状态 | 3300 |
| `ocr_auto_jump()` | OCR自动跳转功能 | 3781 |
| `closeEvent()` | 窗口关闭清理 | 1321, 4062 |

---

### 4.4 MapManagerDialog（地图管理器）

**继承**: `QDialog`  
**行号**: 4092+

**控件列表**:
| 控件名 | 类型 | 功能 |
|--------|------|------|
| `map_list` | `QListWidget` | 本地地图列表 |
| `delete_btn` | `PushButton` | 删除选中地图 |
| `refresh_btn` | `PushButton` | 刷新列表 |

---

## 5. 信号槽系统

### 5.1 自定义Signal定义

**MapBackend类**:
```python
class MapBackend(QObject):
    statusUpdated = Signal(float, float, int)           # lat, lng, zoom
    localMapChangedSignal = Signal(str)                 # 本地地图切换
    proxyResponse = Signal(str, int, str, str)          # req_id, status, text, headers
    _internalProxyResponse = Signal(str, int, str, str) # 内部跨线程安全信号
```

**CalibrationWindow类**:
```python
class CalibrationWindow(QDialog):
    calibrationFinished = Signal(object)  # 传递 TransformMatrix
```

**MapGeneratorWorker类**:
```python
class MapGeneratorWorker(QThread):
    progress_updated = Signal(int)        # 进度百分比
    status_updated = Signal(str)          # 状态描述
    finished = Signal(bool, str)          # 成功/失败，消息
```

### 5.2 外部模块信号

| 模块 | 信号 | 参数 | 用途 |
|------|------|------|------|
| `OCRManager` | `coordinates_detected` | `(int, int, int)` | 检测到的游戏坐标 x, y, z |
| `OCRManager` | `state_changed` | `(str)` | 状态：LOCKED/LOST/SEARCHING/STOPPED |
| `OCRManager` | `error_occurred` | `(str)` | 错误信息 |
| `RouteRecorder` | `recording_started` | `(str)` | 路线名称 |
| `RouteRecorder` | `recording_stopped` | `(str, int)` | 路线名称，点数 |
| `RouteRecorder` | `point_recorded` | `(int, int, int, int)` | x, y, z, 总点数 |
| `RouteRecorder` | `error_occurred` | `(str)` | 错误信息 |
| `GlobalHotkeyManager` | `hotkey_triggered` | `(str)` | 动作名称 |
| `LanguageManager` | `language_changed` | `(str)` | 语言代码 |
| `SeparatedMapWindow` | `window_closed` | `()` | 窗口关闭通知 |

### 5.3 核心信号连接关系

```python
# 语言管理
self.language_manager.language_changed -> self.on_language_changed

# OCR功能
self.ocr_manager.coordinates_detected -> self.on_ocr_coordinates_detected
self.ocr_manager.state_changed -> self.on_ocr_state_changed
self.ocr_manager.error_occurred -> self.on_ocr_error

# 路线录制
self.route_recorder.recording_started -> self.on_recording_started
self.route_recorder.recording_stopped -> self.on_recording_stopped
self.route_recorder.point_recorded -> self.on_point_recorded
self.route_recorder.error_occurred -> self.on_recording_error

# 快捷键
self.hotkey_manager.hotkey_triggered -> self.on_hotkey_triggered

# WebChannel
self.backend.statusUpdated -> self.on_map_status_updated
self.backend.localMapChangedSignal -> self.on_local_map_changed_from_js
self.backend.proxyResponse -> self._deliver_proxy_response_via_js

# Web视图
self.web_view.urlChanged -> self.on_url_changed
self.web_view.urlChanged -> self.on_url_changed_for_history
self.web_view.loadFinished -> self.on_page_load_finished
self.web_profile.downloadRequested -> self.on_download_requested

# 分离地图窗口
self.separated_map_window.window_closed -> self.on_separated_map_closed

# 校准窗口
calibration_window.calibrationFinished -> self.on_calibration_finished

# 模式切换
self.radio_mode_group.buttonClicked -> self.on_mode_changed
self.radio_online_map_group.buttonClicked -> self.load_current_map
self.calib_mode_group.buttonClicked -> self.on_calibration_mode_changed
```

### 5.4 信号流向分析

#### UI事件触发流
```
用户点击按钮 
  → 信号发射 (clicked)
  → 槽函数处理 (toggle_xxx / on_xxx_clicked)
  → 状态更新
  → UI刷新
```

#### OCR到地图跳转流
```
OCR线程捕获画面
  → 检测坐标 (x, y, z)
  → coordinates_detected 信号
  → on_ocr_coordinates_detected 槽
  → CalibrationSystem.transform() 坐标转换
  → runJavaScript() 调用地图API
  → 地图平移到目标位置
```

#### WebChannel双向通信流
```
Python → JavaScript:
  web_view.page().runJavaScript("window.discoveredMap.setView([lat, lon])")

JavaScript → Python:
  window.backend.updateStatus(lat, lng, zoom)
  → MapBackend.updateStatus() [Slot]
  → statusUpdated 信号
  → on_map_status_updated 槽
  → UI更新经纬度显示
```

#### 代理请求流（绕过CORS）
```
JS发起跨域请求
  → window.backend.proxyRequest(req_id, method, url, headers, body)
  → MapBackend.proxyRequest() [Slot]
  → threading.Thread 发送 requests 请求
  → _internalProxyResponse 信号（跨线程安全）
  → _do_emit_proxy_response 槽
  → proxyResponse 信号
  → _deliver_proxy_response_via_js()
  → runJavaScript("window._handleProxyResponse(...)")
  → JS接收响应数据
```

---

## 6. 功能模块分析

### 6.1 OCR功能

**入口**:
- UI按钮：`toggle_ocr_btn`
- 全局快捷键：`toggle_ocr`

**流程**:
1. 用户触发开关 → `toggle_ocr_recognition()`
2. `OCRManager` 启动/停止工作线程
3. 工作线程循环捕获游戏窗口画面
4. 使用YOLO模型或Tesseract检测屏幕左上角坐标
5. 检测到坐标后发射 `coordinates_detected(x, y, z)` 信号
6. 主窗口接收信号 → `on_ocr_coordinates_detected()`
7. 通过变换矩阵将游戏坐标转换为地图经纬度
8. 调用JS函数更新地图中心

**涉及控件**: `TogglePushButton`, `BodyLabel` (状态显示)

**依赖模块**: `ocr_manager.py`, `cv2`, `numpy`, `PyTorch` (YOLO)

---

### 6.2 路线录制功能

**入口**:
- UI按钮：`toggle_recording_btn`
- 全局快捷键：`toggle_recording`

**流程**:
1. 调用 `toggle_route_recording()`
2. 检查OCR是否启动（路线录制依赖OCR）
3. `RouteRecorder` 开始监听OCR坐标更新
4. 每次OCR检测到有效坐标时调用 `route_recorder.record_point(x, y, z)`
5. 录制结束时弹出对话框提示输入名称并保存为JSON
6. 用户可通过 `RouteListDialog` 查看和加载历史路线

**涉及控件**: `PushButton`, `LineEdit`, `RouteListDialog`

**依赖模块**: `route_recorder.py`, `route_list_dialog.py`

---

### 6.3 地图校准功能

**入口**: `calibration_btn` → `open_calibration_window()`

**流程**:
1. 弹出 `CalibrationWindow` 对话框，加载当前地图
2. 用户在游戏中移动到特定点，在软件中输入该点的X, Y游戏坐标
3. 在地图上移动十字准星到对应位置，点击"设定校准点"
4. 重复至少2个点（推荐3个）
5. 调用 `CalibrationSystem.calculate_transform_matrix(points)` 计算仿射变换矩阵
6. 发射 `calibrationFinished` 信号，主窗口保存矩阵到 `calibration_data.json`

**涉及控件**: `CalibrationWindow`, `QTableWidget`, `LineEdit`, `PushButton`

**依赖模块**: `numpy` (矩阵运算), `json`

---

### 6.4 全局快捷键功能

**入口**: 系统级键盘事件

**流程**:
1. 在 `__init__` 中初始化 `GlobalHotkeyManager`
2. 从配置文件加载快捷键字符串（如 `ctrl+f1`）
3. 监听系统热键，触发时发射 `hotkey_triggered(action_name)` 信号
4. 主窗口 `on_hotkey_triggered()` 执行对应逻辑

**支持的动作**:
| 动作名 | 功能 |
|--------|------|
| `toggle_ocr` | 切换OCR识别 |
| `toggle_recording` | 切换路线录制 |
| `mark_next` | 触发JS按钮 `#btn-mark-smart` |
| `undo` | 触发JS按钮 `#btn-undo-smart` |

**涉及控件**: `HotkeyConfigDialog`

**依赖模块**: `hotkey_manager.py`, `keyboard` (底层库)

---

### 6.5 透明覆盖层功能

**入口**:
- `circle_size_spinbox` 调整大小
- `overlay_visible_checkbox` 控制显示

**流程**:
1. `OverlayManager` 创建无边框、鼠标穿透、置顶的透明窗口
2. 当OCR检测到位置更新时，主窗口通知 `OverlayManager` 更新位置
3. 覆盖层在屏幕指定位置渲染圆点（支持Z轴颜色映射）

**依赖模块**: `transparent_overlay.py`

---

### 6.6 地图切换功能

**入口**: `radio_mode_group` (在线/本地) + `radio_online_map_group` (官方/光环)

**流程**:
1. 用户选择"官方地图"、"本地地图"或"第三方地图"
2. 根据选择调用 `get_map_urls()` 获取URL
3. 如果选择本地地图，检查 `server_manager` 是否运行（端口58427）
4. `web_view.setUrl()` 加载对应URL
5. 地图加载后，脚本通过WebProfile自动注入

**涉及控件**: `QRadioButton`, `QButtonGroup`, `QWebEngineView`

**依赖模块**: `http.server` (本地服务), `greasemonkey_manager.py`

---

### 6.7 窗口控制功能

**入口**: `window_control_group` 中的4个CheckBox和1个Slider

| 功能 | 方法 | 效果 |
|------|------|------|
| 地图顶置 | `toggle_map_topmost()` | 设置 `WindowStaysOnTopHint` |
| 鼠标穿透 | `toggle_map_passthrough()` | 设置 `WindowTransparentForInput` |
| 无边框 | `toggle_map_frameless()` | 设置 `FramelessWindowHint` |
| 主界面顶置 | `toggle_main_topmost()` | 主窗口置顶 |
| 透明度 | `on_map_opacity_changed()` | 调整窗口透明度 |

---

## 7. 外部依赖模块

### 7.1 模块导入和可用性检查

```python
# OCR模块
try:
    from ocr_manager import OCRManager
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# 路线录制
try:
    from route_recorder import RouteRecorder
    from route_list_dialog import RouteListDialog
    ROUTE_RECORDER_AVAILABLE = True
except ImportError:
    ROUTE_RECORDER_AVAILABLE = False

# 全局快捷键
try:
    from hotkey_manager import GlobalHotkeyManager
    HOTKEY_AVAILABLE = True
except ImportError:
    HOTKEY_AVAILABLE = False

# 透明覆盖层
try:
    from transparent_overlay import OverlayManager
    OVERLAY_AVAILABLE = True
except ImportError:
    OVERLAY_AVAILABLE = False

# 分离地图窗口
try:
    from separated_map_window import SeparatedMapWindow
    SEPARATED_MAP_AVAILABLE = True
except ImportError:
    SEPARATED_MAP_AVAILABLE = False

# 语言管理
try:
    from language_manager import get_language_manager, tr
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
```

### 7.2 模块职责表

| 模块 | 文件 | 职责 |
|------|------|------|
| OCRManager | `ocr_manager.py` | 屏幕坐标检测，YOLO模型推理 |
| RouteRecorder | `route_recorder.py` | 路线录制与JSON存储 |
| RouteListDialog | `route_list_dialog.py` | 路线查看对话框 |
| GlobalHotkeyManager | `hotkey_manager.py` | 系统级快捷键监听 |
| HotkeyConfigDialog | `hotkey_config_dialog.py` | 快捷键配置对话框 |
| OverlayManager | `transparent_overlay.py` | 透明覆盖层窗口 |
| SeparatedMapWindow | `separated_map_window.py` | 独立地图窗口 |
| GreasemonkeyManager | `greasemonkey_manager.py` | JS脚本注入管理 |
| LanguageManager | `language_manager.py` | 多语言支持 |

---

## 8. WebChannel通信

### 8.1 MapBackend类

```python
class MapBackend(QObject):
    """WebChannel后端通信类"""
    
    # 信号
    statusUpdated = Signal(float, float, int)
    localMapChangedSignal = Signal(str)
    proxyResponse = Signal(str, int, str, str)
    _internalProxyResponse = Signal(str, int, str, str)
    
    # 槽方法
    @Slot(float, float, int)
    def updateStatus(self, lat, lng, zoom):
        """接收JS发送的地图状态更新"""
        self.statusUpdated.emit(lat, lng, zoom)
    
    @Slot(str)
    def localMapChanged(self, map_name):
        """接收JS发送的本地地图切换通知"""
        self.localMapChangedSignal.emit(map_name)
    
    @Slot(str, str, str, str, str, str)
    def proxyRequest(self, req_id, method, url, headers_json, body, response_type="text"):
        """代理HTTP请求（解决CORS问题）"""
        # 在后台线程执行requests请求
        # 通过_internalProxyResponse信号跨线程安全地返回结果
```

### 8.2 通信初始化

```python
def setup_web_channel(self):
    self.backend = MapBackend(self)
    self.channel = QWebChannel()
    self.web_page.setWebChannel(self.channel)
    self.channel.registerObject("backend", self.backend)
    
    # 连接信号
    self.backend.statusUpdated.connect(self.on_map_status_updated)
    self.backend.localMapChangedSignal.connect(self.on_local_map_changed_from_js)
    self.backend.proxyResponse.connect(self._deliver_proxy_response_via_js)
```

### 8.3 JS端调用示例

```javascript
// 初始化WebChannel连接
new QWebChannel(qt.webChannelTransport, function(channel) {
    window.backend = channel.objects.backend;
});

// Python → JS: 地图操作
// (Python端调用)
self.web_view.page().runJavaScript("window.discoveredMap.setView([lat, lon])")

// JS → Python: 状态更新
window.backend.updateStatus(lat, lng, zoom);

// JS → Python: 代理请求
window.backend.proxyRequest(reqId, "GET", url, JSON.stringify(headers), "", "text");
```

---

## 9. 配置与持久化

### 9.1 配置文件

| 文件 | 用途 | 格式 |
|------|------|------|
| `app_settings.json` | 应用设置（快捷键、免责声明状态等） | JSON |
| `calibration_data.json` | 校准数据（变换矩阵） | JSON |
| `login_history.json` | 登录历史（URL、域名） | JSON |
| `maps.json` | 本地地图列表 | JSON |

### 9.2 WebProfile持久化

```python
def setup_persistent_login_system(self):
    # 创建持久化WebProfile
    profile_dir = os.path.join(script_dir, "web_profile")
    self.web_profile = QWebEngineProfile("WutheringWavesNavigator", self)
    self.web_profile.setPersistentStoragePath(profile_dir)
    self.web_profile.setCachePath(os.path.join(profile_dir, "cache"))
    
    # 启用持久化Cookie
    self.web_profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    
    # 启用磁盘缓存
    self.web_profile.setHttpCacheType(
        QWebEngineProfile.HttpCacheType.DiskHttpCache
    )
```

### 9.3 应用设置示例

```json
{
  "disclaimer_accepted": true,
  "first_run_date": "2024-01-01T00:00:00",
  "global_hotkeys": {
    "enabled": true,
    "hotkeys": {
      "toggle_ocr": "ctrl+f1",
      "toggle_recording": "ctrl+f2",
      "mark_next": "ctrl+f3",
      "undo": "ctrl+f4"
    }
  }
}
```

### 9.4 校准数据示例

```json
{
  "online_官方地图_8": {
    "a": 0.0,
    "b": -0.00123,
    "c": 45.678,
    "d": 0.00123,
    "e": 0.0,
    "f": 123.456
  },
  "local_我的地图": {
    "a": 0.0,
    "b": -0.001,
    "c": 50.0,
    "d": 0.001,
    "e": 0.0,
    "f": 100.0
  }
}
```

---

## 附录：关键行号索引

| 内容 | 起始行 |
|------|--------|
| 导入语句 | 1-100 |
| CalibrationDataManager | 450 |
| CalibrationPoint | 523 |
| TransformMatrix | 531 |
| CalibrationSystem | 541 |
| CustomWebEnginePage | 583 |
| MapBackend | 607 |
| CalibrationWindow | 696 |
| CalibrationWindow.setup_ui() | 717 |
| MapCalibrationMainWindow | 1001 |
| MapCalibrationMainWindow.__init__() | 1013 |
| MapCalibrationMainWindow.setup_ui() | 1481 |
| setup_persistent_login_system() | 1890 |
| setup_script_injection() | 1933 |
| setup_web_channel() | 2593 |
| connect_signals() | 2635 |
| on_mode_changed() | 2737 |
| load_current_map() | 2793 |
| trigger_capture_sequence() | 2964 |
| open_calibration_window() | 3137 |
| toggle_route_recording() | 3300 |
| toggle_ocr_recognition() | 3474 |
| ocr_auto_jump() | 3781 |
| on_language_changed() | 4020 |
| closeEvent() | 4062 |
| open_map_manager() | 4092 |

---

*文档生成时间: 2026-01-15*  
*源文件: `src/main_app_legacy.py` (4351行)*
