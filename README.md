# 🌊 鸣潮地图导航系统 (WutheringWaves Navigator)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)](https://www.qt.io/qt-for-python)

一个基于 PySide6 + QWebEngineView 开发的《鸣潮》游戏地图导航和校准系统，支持在线地图和本地地图的实时同步、坐标转换和精确导航。

## ✨ 核心功能

### 🗺️ 双模式地图支持
- **在线地图模式**: 支持官方地图和光环助手地图
- **本地地图模式**: 支持自定义地图瓦片和图片

### 🎯 地图校准系统
- **多点校准**: 支持2-3个校准点的仿射变换
- **数据持久化**: 自动保存和加载校准数据
- **坐标转换**: 游戏坐标到地理坐标的精确转换

### 🔍 智能OCR识别
- **深度学习**: 基于YOLO模型的字符检测
- **智能聚类**: 自动处理检测结果
- **多模式截图**: 支持BitBlt和PrintWindow模式

### 📍 路线录制功能
- **实时记录**: 自动记录OCR识别的坐标点
- **路线管理**: 支持查看、导出和管理路线
- **时间戳**: 详细的时间记录

### 🌐 多语言支持
- 支持7种语言：🇨🇳中文 🇺🇸English 🇯🇵日本語 🇰🇷한국어 🇷🇺Русский 🇫🇷Français 🇩🇪Deutsch
- 完整UI界面翻译
- 动态语言切换

### 🚀 实时同步功能
- **WebSocket通信**: 多客户端地图状态实时同步
- **状态管理**: 地图位置、缩放级别实时共享
- **远程控制**: 通过Web控制面板远程操作地图

## 📁 项目结构

```
WutheringWaves-Navigator/
├── src/                          # 源代码
│   ├── main_app.py              # 主程序入口
│   ├── control_console.py       # 控制台界面
│   ├── map_window.py            # 地图窗口
│   ├── ocr_engine.py            # OCR识别引擎
│   ├── route_recorder.py        # 路线录制器
│   └── ...                      # 其他模块
├── docs/                         # 文档
│   ├── README.md                # 详细文档
│   └── BUILD_GUIDE.md           # 构建指南
├── languages/                    # 多语言文件
├── models/                       # OCR模型文件
├── scripts/                      # 构建脚本
├── config/                       # 配置模板
├── examples/                     # 示例代码
├── assets/                       # 资源文件
└── web/                          # Web文件
```

## 🚀 快速开始

### 环境要求

```bash
Python 3.8+
```

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行程序

```bash
python src/main_app.py
```

### 添加自定义地图（可选）

```bash
python src/tile_generator.py your_map_image.jpg
```

## 📚 使用指南

### 1. 基本使用
1. 启动程序选择地图模式（在线/本地）
2. 进行地图校准（设置2-3个校准点）  
3. 启动OCR坐标识别
4. 使用坐标跳转和路线录制功能

### 2. OCR设置
- 校准OCR识别区域
- 调整置信度阈值
- 选择截图模式

### 3. 路线录制
- 开始录制前先启动OCR
- 录制过程中自动保存坐标点
- 可查看和管理录制的路线

## 🔧 API 集成

### 核心类使用

```python
from src.main_app import CalibrationSystem, CalibrationDataManager

# 创建校准管理器
calibration_mgr = CalibrationDataManager()

# 坐标转换
lat, lon = CalibrationSystem.transform(game_x, game_y, transform_matrix)
```

### WebSocket API

```python
# 地图跳转
{
    "type": "jumpTo",
    "lat": 31.123456,
    "lng": 121.654321
}

# 地图切换
{
    "type": "mapChange",
    "mapName": "custom_map"
}
```

更多API文档请参考 [docs/README.md](docs/README.md)

## 🛠️ 构建打包

### 快速打包

```bash
# Windows
scripts/quick_build.bat

# Linux/Mac  
python scripts/build_spec.py
```

### 制作安装程序

```bash
scripts/build_installer.bat
```

详细构建指南请参考 [docs/BUILD_GUIDE.md](docs/BUILD_GUIDE.md)

## 🌟 示例代码

查看 [examples/](examples/) 目录中的示例：
- `basic_usage.py` - 基本使用示例
- `api_integration.py` - API集成示例  
- `custom_map_example.py` - 自定义地图示例

## 🤝 贡献指南

我们欢迎所有形式的贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何参与项目。

### 快速贡献
1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📝 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解项目更新历史。

## ⚠️ 免责声明

本项目仅供学习和研究使用，请遵守游戏相关条款和法律法规。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。

## 🔗 相关链接

- [问题反馈](https://github.com/guhuo-km/WutheringWaves-Navigator/issues)
- [功能建议](https://github.com/guhuo-km/WutheringWaves-Navigator/discussions)
- [详细文档](docs/README.md)

## 🙏 致谢

感谢所有为这个项目做出贡献的开发者和用户！

---

<div align="center">

**如果这个项目对你有帮助，请给我们一个 ⭐ Star！**

Made with ❤️ for Wuthering Waves community

</div>