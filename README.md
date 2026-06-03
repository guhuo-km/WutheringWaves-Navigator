# 呜呜大地图 / WutheringWaves Navigator

一个面向《鸣潮》玩家的 Windows 桌面辅助工具，围绕大地图、坐标 OCR、地图同步、路线录制与路线编辑做自动化整合。

项目仍在快速迭代中，当前以 Windows 桌面端体验为主。

## 主要功能

- 桌面端主界面：基于 PySide6 + Fluent Widgets。
- 地图窗口：通过 QWebEngineView 加载地图，并使用 userscript 控制地图交互。
- 坐标 OCR：识别游戏画面坐标，支持 OCR 区域校准和动态 ROI。
- 地图同步：将识别坐标同步到地图，实现跳转和追踪。
- 路线录制：记录移动轨迹并管理路线。
- 路线导入与编辑：支持 V2 Graph 路线结构、节点/连线编辑、选择、连接、框选和节点样式。
- 热更新：包含文件级更新、更新器和发布元数据生成脚本。
- 多语言：当前主要维护简体中文和英文资源。

## 当前结构

```text
src/                         主程序、UI、OCR、更新器和核心逻辑
js/                          地图 userscript
templates/                   userscript / WebChannel 辅助模板
assets/                      图标和界面资源
languages/                   i18n 文本
config/                      配置模板
scripts/                     构建、安装器和 release 元数据脚本
tests/                       pytest 测试
docs/                        当前公开文档
version.json                 版本信息
```

更详细的运行时结构见 `docs/project_structure.md`。

## 环境

推荐环境：

```powershell
Python 3.12
Windows 10/11
```

安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements_fluent.txt
```

如果依赖解析遇到 Fluent Widgets 冲突，请优先安装 PySide6 版本：

```powershell
pip install "PySide6-Fluent-Widgets[full]"
```

## 运行

```powershell
python src/main_app.py
```

首次运行会自动生成必要的本地配置。

## OCR 模型

当前公开源码包含 ONNX OCR 模型：

```text
src/models/coord_ocr.onnx
src/models/class_names.txt
```

如果你替换自训练模型，请保持类别顺序与 `class_names.txt` 一致。

## 测试

运行主要测试：

```powershell
pip install pytest
pytest tests -q
```

针对 userscript 的语法检查：

```powershell
node --check js/wuwa_map_optimizer.js
node --check js/wuwa_map_optimizer_lite.js
```

## 打包

使用当前虚拟环境打包：

```powershell
python scripts\smart_build.py
```

常用参数：

```powershell
python scripts\smart_build.py --include-local-maps
python scripts\smart_build.py --include-images --include-runtime-configs
```

公开源码的 `version.json` 默认不内置更新地址。需要给正式打包产物写入更新源时，可以使用：

```powershell
python scripts\smart_build.py --update-base-url "https://example.com/wuwa-navigator/stable"
```

## 免责声明

本项目为个人开发的免费工具，仅用于学习、研究和便利化个人使用。请遵守游戏服务条款和相关法律法规。项目与游戏官方无关联。

## License

MIT License. See `LICENSE`.
