#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多语言管理器
支持中文、英文、日文、韩文、俄文、法文、德文
"""

import json
import os
from typing import Dict, Optional
from PySide6.QtCore import QObject, Signal


class LanguageManager(QObject):
    """多语言管理器"""
    
    # 语言切换信号
    language_changed = Signal(str)  # 参数：新语言代码
    
    # 支持的语言列表
    SUPPORTED_LANGUAGES = {
        'zh_CN': '简体中文',
        'en_US': 'English',
        'ja_JP': '日本語',
        'ko_KR': '한국어',
        'ru_RU': 'Русский',
        'fr_FR': 'Français',
        'de_DE': 'Deutsch'
    }
    
    def __init__(self):
        super().__init__()
        self.current_language = 'zh_CN'  # 默认简体中文
        self.translations: Dict[str, Dict[str, str]] = {}
        self.config_file = 'language_config.json'
        
        # 创建语言文件目录
        self.lang_dir = 'languages'
        if not os.path.exists(self.lang_dir):
            os.makedirs(self.lang_dir)
        
        # 加载所有语言翻译
        self.load_all_translations()
        
        # 加载用户设置
        self.load_language_config()
    
    def load_all_translations(self):
        """加载所有语言的翻译文件"""
        for lang_code in self.SUPPORTED_LANGUAGES.keys():
            self.load_language_file(lang_code)
    
    def load_language_file(self, lang_code: str):
        """加载指定语言的翻译文件"""
        lang_file = os.path.join(self.lang_dir, f'{lang_code}.json')
        
        if os.path.exists(lang_file):
            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    self.translations[lang_code] = json.load(f)
                print(f"已加载语言文件: {lang_code}")
            except Exception as e:
                print(f"加载语言文件失败 {lang_code}: {e}")
                self.translations[lang_code] = {}
        else:
            print(f"语言文件不存在: {lang_file}")
            self.translations[lang_code] = {}
    
    def load_language_config(self):
        """加载语言配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.current_language = config.get('current_language', 'zh_CN')
                    
                    # 验证语言代码是否支持
                    if self.current_language not in self.SUPPORTED_LANGUAGES:
                        self.current_language = 'zh_CN'
                        
            except Exception as e:
                print(f"加载语言配置失败: {e}")
                self.current_language = 'zh_CN'
    
    def save_language_config(self):
        """保存语言配置"""
        try:
            config = {
                'current_language': self.current_language,
                'available_languages': list(self.SUPPORTED_LANGUAGES.keys())
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"保存语言配置失败: {e}")
    
    def set_language(self, lang_code: str):
        """设置当前语言"""
        if lang_code in self.SUPPORTED_LANGUAGES:
            old_language = self.current_language
            self.current_language = lang_code
            
            # 保存配置
            self.save_language_config()
            
            # 发送语言变更信号
            if old_language != lang_code:
                self.language_changed.emit(lang_code)
                print(f"语言已切换: {old_language} -> {lang_code}")
            
            return True
        else:
            print(f"不支持的语言代码: {lang_code}")
            return False
    
    def get_current_language(self) -> str:
        """获取当前语言代码"""
        return self.current_language
    
    def get_current_language_name(self) -> str:
        """获取当前语言名称"""
        return self.SUPPORTED_LANGUAGES.get(self.current_language, '简体中文')
    
    def get_supported_languages(self) -> Dict[str, str]:
        """获取支持的语言列表"""
        return self.SUPPORTED_LANGUAGES.copy()
    
    def translate(self, key: str, default: str = None, **kwargs) -> str:
        """
        翻译文本
        
        Args:
            key: 翻译键
            default: 默认文本（如果未找到翻译）
            **kwargs: 格式化参数
        
        Returns:
            str: 翻译后的文本
        """
        # 获取当前语言的翻译
        current_translations = self.translations.get(self.current_language, {})
        
        # 尝试获取翻译
        text = current_translations.get(key)
        
        # 如果没有找到翻译，尝试使用默认语言（中文）
        if text is None and self.current_language != 'zh_CN':
            fallback_translations = self.translations.get('zh_CN', {})
            text = fallback_translations.get(key)
        
        # 如果仍然没有找到，使用提供的默认值或键本身
        if text is None:
            text = default if default is not None else key
        
        # 应用格式化参数
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError) as e:
                print(f"翻译格式化失败 '{key}': {e}")
        
        return text
    
    def tr(self, key: str, default: str = None, **kwargs) -> str:
        """translate方法的简写形式"""
        return self.translate(key, default, **kwargs)
    
    def has_translation(self, key: str, lang_code: str = None) -> bool:
        """检查是否存在指定键的翻译"""
        if lang_code is None:
            lang_code = self.current_language
        
        translations = self.translations.get(lang_code, {})
        return key in translations
    
    def get_translation_keys(self, lang_code: str = None) -> list:
        """获取指定语言的所有翻译键"""
        if lang_code is None:
            lang_code = self.current_language
        
        translations = self.translations.get(lang_code, {})
        return list(translations.keys())
    
    def reload_translations(self):
        """重新加载所有翻译文件"""
        self.translations.clear()
        self.load_all_translations()
        print("已重新加载所有翻译文件")
    
    def get_language_info(self) -> Dict:
        """获取当前语言信息"""
        return {
            'current_language': self.current_language,
            'current_language_name': self.get_current_language_name(),
            'supported_languages': self.SUPPORTED_LANGUAGES,
            'translation_count': len(self.translations.get(self.current_language, {}))
        }


# 全局语言管理器实例
_language_manager = None


def get_language_manager() -> LanguageManager:
    """获取全局语言管理器实例"""
    global _language_manager
    if _language_manager is None:
        _language_manager = LanguageManager()
    return _language_manager


def tr(key: str, default: str = None, **kwargs) -> str:
    """全局翻译函数"""
    return get_language_manager().translate(key, default, **kwargs)


def set_language(lang_code: str) -> bool:
    """全局设置语言函数"""
    return get_language_manager().set_language(lang_code)


def get_current_language() -> str:
    """获取当前语言"""
    return get_language_manager().get_current_language()


def get_supported_languages() -> Dict[str, str]:
    """获取支持的语言列表"""
    return get_language_manager().get_supported_languages()


# 使用示例
if __name__ == "__main__":
    # 创建语言管理器
    lang_mgr = LanguageManager()
    
    # 打印支持的语言
    print("支持的语言:")
    for code, name in lang_mgr.get_supported_languages().items():
        try:
            print(f"  {code}: {name}")
        except UnicodeEncodeError:
            print(f"  {code}: [编码问题]")
    
    # 测试翻译功能
    print(f"\n当前语言: {lang_mgr.get_current_language_name()}")
    print(f"翻译测试: {lang_mgr.tr('app_title', 'WutheringWaves Navigator')}")
    
    # 切换到英文
    lang_mgr.set_language('en_US')
    print(f"\n语言切换后: {lang_mgr.get_current_language_name()}")
    print(f"翻译测试: {lang_mgr.tr('app_title', 'WutheringWaves Navigator')}")