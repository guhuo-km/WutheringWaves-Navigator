# Contributing to WutheringWaves Navigator

感谢您对 WutheringWaves Navigator 项目的兴趣！我们欢迎所有形式的贡献。

## 🤝 如何贡献

### 报告问题 (Bug Reports)

如果您发现了错误，请在 [Issues](https://github.com/your-username/WutheringWaves-Navigator/issues) 中报告：

1. **搜索现有问题** - 确保您的问题尚未被报告
2. **使用清晰的标题** - 简洁描述问题
3. **详细描述** - 包含以下信息：
   - 操作系统版本
   - Python版本
   - 错误的完整描述
   - 重现步骤
   - 预期行为 vs 实际行为
   - 截图（如果适用）

### 功能请求 (Feature Requests)

我们欢迎新功能建议：

1. **检查现有请求** - 避免重复建议
2. **详细说明用例** - 解释为什么需要这个功能
3. **提供mockup或示例** - 如果可能的话

### 代码贡献

#### 准备工作

1. **Fork 仓库**
2. **创建开发环境**：
   ```bash
   git clone https://github.com/your-username/WutheringWaves-Navigator.git
   cd WutheringWaves-Navigator
   pip install -r requirements.txt
   ```

3. **创建功能分支**：
   ```bash
   git checkout -b feature/your-feature-name
   ```

#### 代码规范

- **Python代码**：遵循 PEP 8 规范
- **注释**：使用中文注释，重要函数添加docstring
- **导入顺序**：标准库 → 第三方库 → 本地模块
- **类型提示**：推荐使用类型提示

示例代码风格：
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块说明
"""

import os
import sys
from typing import Optional, Dict, Any

import numpy as np
from PySide6.QtWidgets import QWidget

from .local_module import LocalClass


class ExampleClass:
    """示例类说明"""
    
    def __init__(self, name: str):
        """
        初始化方法
        
        Args:
            name: 名称参数
        """
        self.name = name
    
    def process_data(self, data: Dict[str, Any]) -> Optional[str]:
        """处理数据方法"""
        # 具体实现...
        return result
```

#### 提交规范

使用清晰的提交信息：
```
类型(范围): 简短描述

详细描述（如果需要）
```

类型包括：
- `feat`: 新功能
- `fix`: 错误修复
- `docs`: 文档更新
- `style`: 代码格式化
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建/工具相关

示例：
```
feat(ocr): 添加新的OCR识别算法

实现基于Transformer的OCR识别，提高准确率15%
```

#### 拉取请求 (Pull Request)

1. **确保代码质量**：
   - 所有测试通过
   - 代码格式规范
   - 没有明显的性能问题

2. **更新文档**：
   - 更新相关README
   - 添加必要的注释
   - 更新CHANGELOG.md

3. **PR描述**：
   ```markdown
   ## 变更类型
   - [ ] Bug 修复
   - [ ] 新功能
   - [ ] 代码重构
   - [ ] 文档更新
   
   ## 描述
   详细描述您的更改
   
   ## 测试
   描述您如何测试这些更改
   
   ## 截图
   如果适用，添加截图
   ```

## 🌐 多语言支持

如果您想贡献翻译：

1. 复制 `languages/zh_CN.json` 作为模板
2. 翻译所有字符串值（保持键名不变）
3. 将新文件命名为对应的语言代码（如 `es_ES.json`）
4. 更新 `src/language_manager.py` 中的 `SUPPORTED_LANGUAGES`

## 🧪 测试

在提交PR之前，请确保：

1. **手动测试**：
   - 核心功能正常工作
   - UI界面显示正确
   - 没有明显的错误

2. **构建测试**：
   ```bash
   # 测试基本运行
   python src/main_app.py
   
   # 测试打包
   python scripts/build_spec.py
   ```

## 📋 开发环境设置

### 必需软件
- Python 3.8+
- Git

### 推荐工具
- VS Code 或 PyCharm
- Git GUI客户端

### 依赖安装
```bash
pip install -r requirements.txt
```

## 🎯 优先开发领域

我们特别欢迎以下方面的贡献：

1. **OCR准确率提升**
2. **性能优化**
3. **新语言翻译**
4. **文档完善**
5. **测试用例**
6. **UI/UX改进**

## ❓ 获得帮助

如果您在贡献过程中遇到问题：

1. **查看文档** - 阅读 `docs/` 目录中的文档
2. **搜索Issues** - 查看是否有相关讨论
3. **创建Discussion** - 在 GitHub Discussions 中提问
4. **加入社区** - 参与项目讨论

## 🏆 贡献者

感谢所有贡献者！您的名字将出现在项目的贡献者列表中。

## 📄 许可证

通过贡献代码，您同意您的贡献将在与项目相同的 [MIT License](LICENSE) 下授权。

---

再次感谢您的贡献！🚀