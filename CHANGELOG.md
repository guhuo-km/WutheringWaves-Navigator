# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-01

### Added
- 🗺️ **双模式地图支持**
  - 在线地图模式（官方地图、光环助手地图）
  - 本地地图模式（自定义地图瓦片和图片）

- 🎯 **地图校准系统**
  - 多点校准（支持2-3个校准点的仿射变换）
  - 数据持久化（自动保存和加载校准数据）
  - 坐标转换（游戏坐标到地理坐标的精确转换）

- 🔍 **OCR坐标识别**
  - 基于YOLO深度学习模型的字符检测
  - 智能聚类算法处理检测结果
  - 多种截图模式支持（BitBlt, PrintWindow）
  - 高级参数调节和调试输出

- 📍 **路线录制功能**
  - 实时记录OCR识别的坐标点
  - 路线命名和时间戳记录
  - 路线数据查看、管理和导出

- 🌐 **多语言支持**
  - 支持7种语言：中文、英文、日文、韩文、俄文、法文、德文
  - 完整的UI界面翻译
  - 动态语言切换

- 🚀 **实时同步功能**
  - WebSocket服务器支持多客户端连接
  - 地图状态、坐标、缩放级别实时同步
  - Web控制面板支持远程操作

- 🎮 **透明覆盖层**
  - 游戏内透明覆盖层指示
  - 中心圆点显示
  - Z轴颜色映射

- 🔧 **高级功能**
  - 登录状态持久化
  - 地图生成工具（自动将大图片切分为瓦片）
  - 稳健的错误处理和恢复机制

### Technical Features
- 基于PySide6 (Qt6) 的现代GUI界面
- PyTorch + Ultralytics YOLO 的深度学习OCR
- Flask + WebSocket 的多客户端同步
- OpenCV + Pillow 的图像处理
- 模块化架构设计

### Build & Deployment
- PyInstaller 自动打包
- NSIS Windows安装程序制作
- 自动化构建脚本
- 完整的依赖管理