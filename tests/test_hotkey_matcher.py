from pathlib import Path

from src.core.hotkey_matcher import parse_hotkey, resolve_hotkey_action


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOTKEY_MANAGER = PROJECT_ROOT / "src" / "hotkey_manager.py"
HOTKEY_DISPLAY_WIDGET = PROJECT_ROOT / "src" / "ui" / "components" / "hotkey_display_widget.py"


def test_extra_modifiers_trigger_base_binding():
    bindings = {
        "open_nearest": "8",
        "close_popup": "ctrl+8",
    }

    assert resolve_hotkey_action(bindings, {"alt"}, "8") == "open_nearest"
    assert resolve_hotkey_action(bindings, {"shift"}, "8") == "open_nearest"


def test_more_specific_binding_wins():
    bindings = {
        "open_nearest": "8",
        "close_popup": "ctrl+8",
    }

    assert resolve_hotkey_action(bindings, {"ctrl"}, "8") == "close_popup"
    assert resolve_hotkey_action(bindings, {"ctrl", "alt"}, "8") == "close_popup"


def test_same_specificity_ambiguity_does_not_trigger():
    bindings = {
        "open_nearest": "8",
        "close_popup": "ctrl+8",
        "prev_route": "alt+8",
    }

    assert resolve_hotkey_action(bindings, {"ctrl", "alt"}, "8") is None


def test_mouse_hotkeys_use_same_matching_rules():
    bindings = {
        "open_nearest": "x1",
        "close_popup": "ctrl+x1",
    }

    assert resolve_hotkey_action(bindings, {"alt"}, "x1") == "open_nearest"
    assert resolve_hotkey_action(bindings, {"ctrl", "alt"}, "x1") == "close_popup"


def test_main_number_and_num_number_are_different_primary_keys():
    bindings = {
        "open_nearest": "8",
        "close_popup": "num8",
    }

    assert resolve_hotkey_action(bindings, set(), "8") == "open_nearest"
    assert resolve_hotkey_action(bindings, set(), "num8") == "close_popup"
    assert parse_hotkey("Ctrl+Num8").primary == "num8"


def test_plus_key_can_be_used_as_primary_key():
    bindings = {
        "next_route": "+",
        "zoom_in": "ctrl++",
    }

    assert parse_hotkey("+").primary == "+"
    assert parse_hotkey("Ctrl++").primary == "+"
    assert resolve_hotkey_action(bindings, set(), "+") == "next_route"
    assert resolve_hotkey_action(bindings, {"ctrl"}, "+") == "zoom_in"


def test_hotkey_manager_uses_resolver_for_keyboard_and_mouse():
    text = HOTKEY_MANAGER.read_text(encoding="utf-8")

    assert "from core.hotkey_matcher import parse_hotkey, resolve_hotkey_action" in text
    assert "resolve_hotkey_action(self.hotkeys, active_modifiers, primary)" in text
    assert "resolve_hotkey_action(self.mouse_hotkeys, self.current_modifiers, button_name)" in text


def test_hotkey_manager_normalizes_numpad_scan_codes():
    text = HOTKEY_MANAGER.read_text(encoding="utf-8")

    assert "NUMPAD_SCAN_CODES" in text
    assert "return NUMPAD_SCAN_CODES.get(scan_code, primary)" in text


def test_hotkey_display_widget_names_numpad_digits():
    text = HOTKEY_DISPLAY_WIDGET.read_text(encoding="utf-8")

    assert "Qt.KeypadModifier" in text
    assert 'return f"Num{digit}"' in text
