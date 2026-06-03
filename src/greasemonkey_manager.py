# -*- coding: utf-8 -*-
import os
import re
import json
from jinja2 import Environment, FileSystemLoader
from PySide6.QtWebEngineCore import QWebEngineScript

from core import paths

class GreasemonkeyManager:
    """
    油猴脚本管理器 (Greasemonkey Manager)
    负责管理 JS 模板的加载、渲染和注入逻辑。
    使用 Jinja2 引擎处理复杂的字符串替换，避免 Python f-string 冲突。
    """
    def __init__(self, template_dir=None):
        if template_dir is None:
            template_dir = paths.resource_root() / "templates"

        self.template_dir = str(template_dir)
        self.env = Environment(loader=FileSystemLoader(self.template_dir))

        print(f"GreasemonkeyManager 初始化完成，模板目录: {self.template_dir}")

    def render_script(self, template_name, **kwargs):
        """渲染 JS 模板"""
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            print(f"渲染脚本模板失败 ({template_name}): {e}")
            return ""

    def parse_metadata(self, source):
        """解析脚本元数据，提取 @match, @include, @exclude"""
        metadata = {"matches": [], "excludes": []}

        # 只检查前 2000 个字符以提高性能
        header = source[:5000]
        match_lines = re.findall(r"//\s+@match\s+(.+)", header)
        exclude_lines = re.findall(r"//\s+@exclude\s+(.+)", header)

        metadata["matches"] = [line.strip() for line in match_lines]
        metadata["excludes"] = [line.strip() for line in exclude_lines]
        return metadata

    def wrap_source_with_match_logic(self, name, source, metadata):
        """为脚本包装 URL 匹配检查逻辑"""
        if not metadata["matches"]:
            return source  # 如果没有设置 @match，默认在所有页面运行（或保持原样）

        # 将油猴 match 模式转换为 JS 正则表达式
        # 简化版转换逻辑
        patterns = []
        for p in metadata["matches"]:
            # 处理 *://, http://, https://
            regex = p.replace(".", r"\.").replace("*", ".*").replace("/", r"\/")
            patterns.append(f"^{regex}$")

        exclude_patterns = []
        for p in metadata["excludes"]:
            regex = p.replace(".", r"\.").replace("*", ".*").replace("/", r"\/")
            exclude_patterns.append(f"^{regex}$")

        matches_json = json.dumps(patterns)
        excludes_json = json.dumps(exclude_patterns)

        # 包装代码
        wrapped = f"""
(function() {{
    const name = "{name}";
    const matches = {matches_json};
    const excludes = {excludes_json};
    const currentUrl = window.location.href;

    function checkMatch(url, patternList) {{
        return patternList.some(p => new RegExp(p).test(url));
    }}

    if (checkMatch(currentUrl, matches)) {{
        if (!checkMatch(currentUrl, excludes)) {{
            console.log(`[ScriptManager] 匹配成功，启动脚本: ${name}`);
            try {{
                {source}
            }} catch (e) {{
                console.error(`[ScriptManager] 脚本执行出错 ${name}:`, e);
            }}
        }} else {{
            console.log(`[ScriptManager] URL 在排除列表中，跳过脚本: ${name}`);
        }}
    }}
}})();
"""
        return wrapped

    def create_script(self, name, source, injection_point=QWebEngineScript.Deferred):
        """创建一个 QWebEngineScript 对象（带匹配逻辑）"""
        metadata = self.parse_metadata(source)
        final_source = self.wrap_source_with_match_logic(name, source, metadata)

        script = QWebEngineScript()
        script.setName(name)
        script.setSourceCode(final_source)
        script.setInjectionPoint(injection_point)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(True)
        return script

    def get_standard_scripts(self, user_scripts=None):
        """
        获取一组标准的注入脚本
        包括：QWebChannel, Polyfill, UniversalInjector
        """
        scripts = []

        # 1. QWebChannel 核心库
        qweb_js = self.render_script("qwebchannel.js")
        if qweb_js:
            scripts.append(self.create_script("QWebChannel", qweb_js, QWebEngineScript.DocumentCreation))

        # 2. GM Polyfill (提供 GM_xxx API)
        polyfill_js = self.render_script("gm_polyfill.js")
        if polyfill_js:
            scripts.append(self.create_script("GMPolyfill", polyfill_js, QWebEngineScript.DocumentCreation))

        # 3. Universal Injector (地图拦截逻辑)
        # 使用 Deferred 确保 DOM 准备就绪
        injector_js = self.render_script("universal_injector.js")
        if injector_js:
            scripts.append(self.create_script("UniversalInjector", injector_js, QWebEngineScript.Deferred))

        # 4. Enhanced Storage (存储增强)
        storage_js = self.render_script("enhanced_storage.js")
        if storage_js:
            scripts.append(self.create_script("EnhancedStorage", storage_js, QWebEngineScript.Deferred))

        # 5. 用户自定义脚本 (如 wuwa_map_optimizer.js)
        if user_scripts:
            for i, script_path in enumerate(user_scripts):
                try:
                    with open(script_path, 'r', encoding='utf-8') as f:
                        source = f.read()
                    scripts.append(self.create_script(f"UserScript_{i}", source, QWebEngineScript.Deferred))
                except Exception as e:
                    print(f"加载用户脚本失败 ({script_path}): {e}")

        return scripts
