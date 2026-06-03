# hotkey_manager.py
# 全局快捷键管理器模块 - 支持键盘和鼠标快捷键

import keyboard
from PySide6.QtCore import QObject, Signal, QThread
from typing import Optional

from core.hotkey_matcher import parse_hotkey, resolve_hotkey_action


NUMPAD_SCAN_CODES = {
    82: "num0",
    79: "num1",
    80: "num2",
    81: "num3",
    75: "num4",
    76: "num5",
    77: "num6",
    71: "num7",
    72: "num8",
    73: "num9",
}


class MouseHotkeyListener(QThread):
    """
    鼠标快捷键监听线程
    使用 pynput 库监听鼠标按键
    """

    mouse_hotkey_triggered = Signal(str)  # 发出鼠标快捷键触发信号

    def __init__(self):
        super().__init__()
        self.running = False
        self.mouse_hotkeys = {}  # {action_name: hotkey_str}
        self.current_modifiers = set()  # 当前按下的修饰键
        self._listener = None

    def run(self):
        """启动鼠标监听"""
        try:
            from pynput import mouse, keyboard as pynput_keyboard

            def on_click(x, y, button, pressed):
                if not pressed:  # 只在按键释放时触发
                    return

                # 获取鼠标按键名称
                button_name = self._get_button_name(button)
                if not button_name:
                    return

                action_name = resolve_hotkey_action(self.mouse_hotkeys, self.current_modifiers, button_name)
                if action_name:
                    self.mouse_hotkey_triggered.emit(action_name)

            def on_key_press(key):
                """键盘按下 - 记录修饰键"""
                mod_name = self._get_modifier_name(key)
                if mod_name:
                    self.current_modifiers.add(mod_name)

            def on_key_release(key):
                """键盘释放 - 移除修饰键"""
                mod_name = self._get_modifier_name(key)
                if mod_name:
                    self.current_modifiers.discard(mod_name)

            # 创建监听器
            mouse_listener = mouse.Listener(on_click=on_click)
            keyboard_listener = pynput_keyboard.Listener(
                on_press=on_key_press,
                on_release=on_key_release
            )

            self.running = True
            mouse_listener.start()
            keyboard_listener.start()

            print("鼠标快捷键监听器已启动")

            # 等待线程结束
            while self.running:
                self.msleep(100)

            # 停止监听器
            print("正在停止鼠标监听器...")
            mouse_listener.stop()
            keyboard_listener.stop()
            print("鼠标监听器已停止")

        except ImportError:
            print("警告: pynput 库未安装，鼠标快捷键功能不可用")
            print("请运行: pip install pynput")
        except Exception as e:
            print(f"鼠标监听器异常: {e}")
            import traceback
            traceback.print_exc()

    def stop(self):
        """停止监听"""
        self.running = False

    def register_mouse_hotkey(self, action_name: str, hotkey_str: str):
        """
        注册鼠标快捷键

        Args:
            action_name: 动作名称
            hotkey_str: 鼠标快捷键字符串，如 'middle' 或 'ctrl+x1'
        """
        self.mouse_hotkeys[action_name] = hotkey_str
        print(f"注册鼠标快捷键: {action_name} = {hotkey_str}")

    def unregister_mouse_hotkey(self, action_name: str):
        """注销鼠标快捷键"""
        if action_name in self.mouse_hotkeys:
            del self.mouse_hotkeys[action_name]

    def clear_all(self):
        """清空所有鼠标快捷键"""
        self.mouse_hotkeys.clear()

    def _get_button_name(self, button) -> Optional[str]:
        """获取鼠标按键名称"""
        try:
            from pynput import mouse
            button_map = {
                mouse.Button.middle: 'middle',
                mouse.Button.x1: 'x1',
                mouse.Button.x2: 'x2',
            }
            return button_map.get(button, None)
        except:
            return None

    def _get_modifier_name(self, key) -> Optional[str]:
        """获取修饰键名称"""
        try:
            from pynput import keyboard as pynput_keyboard
            if key == pynput_keyboard.Key.ctrl or key == pynput_keyboard.Key.ctrl_l or key == pynput_keyboard.Key.ctrl_r:
                return 'ctrl'
            elif key == pynput_keyboard.Key.alt or key == pynput_keyboard.Key.alt_l or key == pynput_keyboard.Key.alt_r:
                return 'alt'
            elif key == pynput_keyboard.Key.shift or key == pynput_keyboard.Key.shift_l or key == pynput_keyboard.Key.shift_r:
                return 'shift'
            return None
        except:
            return None


class GlobalHotkeyManager(QObject):
    """全局快捷键管理器 - 支持键盘和鼠标快捷键"""

    hotkey_triggered = Signal(str)  # 发出快捷键触发信号(action_name)

    def __init__(self):
        super().__init__()
        self.hotkeys = {}  # {action_name: hotkey_str}
        self._keyboard_hook = keyboard.hook(self._on_keyboard_event, suppress=False)

        # 鼠标快捷键监听器
        self.mouse_listener = MouseHotkeyListener()
        self.mouse_listener.mouse_hotkey_triggered.connect(self.hotkey_triggered.emit)
        self.mouse_listener.start()

        print("全局快捷键管理器已启动（支持键盘和鼠标快捷键）")

    def register_hotkey(self, action_name, hotkey_str):
        """
        注册快捷键（自动识别键盘或鼠标快捷键）

        参数:
            action_name: 动作名称 (如 'toggle_ocr', 'toggle_recording')
            hotkey_str: 快捷键字符串 (如 'ctrl+f1' 或 'middle' 或 'ctrl+x1')

        返回:
            bool: 注册成功返回 True，失败返回 False
        """
        try:
            # 检查是否是鼠标快捷键
            if self._is_mouse_hotkey(hotkey_str):
                return self._register_mouse_hotkey(action_name, hotkey_str)
            else:
                return self._register_keyboard_hotkey(action_name, hotkey_str)
        except Exception as e:
            print(f"注册快捷键失败 {action_name}: {e}")
            return False

    def _is_mouse_hotkey(self, hotkey_str: str) -> bool:
        """检查是否是鼠标快捷键"""
        hotkey_lower = hotkey_str.lower()
        mouse_buttons = ['middle', 'x1', 'x2', 'back', 'forward']
        return any(btn in hotkey_lower for btn in mouse_buttons)

    def _register_keyboard_hotkey(self, action_name: str, hotkey_str: str) -> bool:
        """注册键盘快捷键"""
        try:
            # 如果该动作已有快捷键，先注销
            if action_name in self.hotkeys:
                self.unregister_hotkey(action_name)

            parsed = parse_hotkey(hotkey_str)
            if not parsed.primary:
                print(f"无效的键盘快捷键格式: {hotkey_str}")
                return False
            self.hotkeys[action_name] = hotkey_str
            print(f"注册键盘快捷键: {action_name} = {hotkey_str}")
            return True
        except Exception as e:
            print(f"注册键盘快捷键失败 {action_name}: {e}")
            return False

    def _register_mouse_hotkey(self, action_name: str, hotkey_str: str) -> bool:
        """注册鼠标快捷键"""
        try:
            parsed = parse_hotkey(hotkey_str)
            if parsed.primary not in {"middle", "x1", "x2"}:
                print(f"无效的鼠标快捷键格式: {hotkey_str}")
                return False

            # 注册到鼠标监听器
            self.mouse_listener.register_mouse_hotkey(action_name, hotkey_str)
            self.hotkeys[action_name] = hotkey_str
            return True

        except Exception as e:
            print(f"注册鼠标快捷键失败 {action_name}: {e}")
            return False

    def unregister_hotkey(self, action_name):
        """
        注销指定动作的快捷键

        参数:
            action_name: 动作名称

        返回:
            bool: 注销成功返回 True
        """
        try:
            if action_name in self.hotkeys:
                hotkey_str = self.hotkeys[action_name]

                # 检查是否是鼠标快捷键
                if self._is_mouse_hotkey(hotkey_str):
                    self.mouse_listener.unregister_mouse_hotkey(action_name)

                del self.hotkeys[action_name]
            return True
        except Exception as e:
            print(f"注销快捷键失败 {action_name}: {e}")
            return False

    def unregister_all(self):
        """
        注销所有快捷键
        """
        try:
            # 注销鼠标快捷键
            self.mouse_listener.clear_all()

            self.hotkeys.clear()
        except Exception as e:
            print(f"注销快捷键失败: {e}")

    def _on_keyboard_event(self, event):
        if getattr(event, "event_type", None) != "down":
            return
        primary = self._normalize_keyboard_event_name(
            getattr(event, "name", ""),
            getattr(event, "scan_code", None),
        )
        if not primary:
            return
        active_modifiers = {
            name for name in ("ctrl", "alt", "shift")
            if keyboard.is_pressed(name)
        }
        action_name = resolve_hotkey_action(self.hotkeys, active_modifiers, primary)
        if action_name:
            self.hotkey_triggered.emit(action_name)

    def _normalize_keyboard_event_name(self, name: str, scan_code=None) -> str:
        primary = parse_hotkey(name).primary
        return NUMPAD_SCAN_CODES.get(scan_code, primary)

    def get_hotkeys(self):
        """
        获取当前快捷键配置

        返回:
            dict: 快捷键配置字典的副本 {action_name: hotkey_str}
        """
        return self.hotkeys.copy()

    def is_registered(self, action_name):
        """
        检查指定动作是否已注册快捷键

        参数:
            action_name: 动作名称

        返回:
            bool: 已注册返回 True
        """
        return action_name in self.hotkeys

    def cleanup(self):
        """清理资源"""
        try:
            print("开始清理快捷键管理器...")

            # 注销所有快捷键
            self.unregister_all()
            if self._keyboard_hook is not None:
                keyboard.unhook(self._keyboard_hook)
                self._keyboard_hook = None

            # 停止鼠标监听线程
            if self.mouse_listener and self.mouse_listener.isRunning():
                print("停止鼠标监听线程...")
                self.mouse_listener.stop()
                if not self.mouse_listener.wait(3000):  # 等待最多3秒
                    print("警告: 鼠标监听线程未能在3秒内停止")
                    self.mouse_listener.terminate()  # 强制终止
                else:
                    print("鼠标监听线程已停止")

            print("快捷键管理器清理完成")

        except Exception as e:
            print(f"清理快捷键管理器失败: {e}")
            import traceback
            traceback.print_exc()
