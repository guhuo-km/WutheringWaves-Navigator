import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Bootstrap test environment (offscreen Qt + vendored qfluentwidgets)
import os as _os
import sys as _sys

_tests_dir = _os.path.dirname(__file__)
if _tests_dir not in _sys.path:
    _sys.path.insert(0, _tests_dir)

import test_bootstrap  # noqa: F401

from PySide6.QtWidgets import QApplication

# Singleton QApp
app = QApplication.instance() or QApplication([])

class TestOCRSettingsToggle(unittest.TestCase):
    """Test OCR Settings Auto Detect Toggle"""

    def setUp(self):
        # Ensure path is set
        src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

    @patch('ui.interfaces.ocr_settings_interface.SwitchButton')
    @patch('ui.interfaces.ocr_settings_interface.SpinBox')
    @patch('ui.interfaces.ocr_settings_interface.ComboBox')
    @patch('ui.interfaces.ocr_settings_interface.LineEdit')
    @patch('ui.interfaces.ocr_settings_interface.PushButton')
    @patch('ui.interfaces.ocr_settings_interface.BodyLabel')
    @patch('ui.interfaces.ocr_settings_interface.SubtitleLabel')
    @patch('ui.interfaces.ocr_settings_interface.QFrame')
    @patch('ui.interfaces.ocr_settings_interface.QGridLayout')
    @patch('ui.interfaces.ocr_settings_interface.QHBoxLayout')
    @patch('ui.interfaces.ocr_settings_interface.QVBoxLayout')
    @patch('ui.interfaces.ocr_settings_interface.CardWidget')
    @patch('ui.interfaces.ocr_settings_interface.SettingsManager')
    def test_toggle_exists_default_on(self, mock_settings_cls, mock_card, mock_vbox, mock_hbox, mock_grid, mock_frame, 
                                     mock_subtitle, mock_body, mock_push, mock_line, mock_combo, mock_spin, mock_switch):
        """Test toggle widget exists and has correct default state"""
        # Ensure QApp
        if QApplication.instance() is None:
            global app
            app = QApplication([])

        # Lazy import
        from ui.interfaces.ocr_settings_interface import OCRSettingsInterface

        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings_cls.return_value = mock_settings
        mock_settings.get.side_effect = lambda k, d=None: d
        
        # Setup mock switch to simulate state
        mock_switch_instance = MagicMock()
        mock_switch.return_value = mock_switch_instance
        # Default isChecked should be False unless set, but our code sets it
        mock_switch_instance.isChecked.return_value = True 

        # Initialize interface
        interface = OCRSettingsInterface()
        
        # Verify switch was created
        assert mock_switch.called
        assert hasattr(interface, '_auto_detect_switch')
        
        # Verify default state logic
        # The code: self._auto_detect_switch.setChecked(auto_detect)
        # We verify setChecked was called with True (default)
        mock_switch_instance.setChecked.assert_called_with(True)

    @patch('ui.interfaces.ocr_settings_interface.SwitchButton')
    @patch('ui.interfaces.ocr_settings_interface.SpinBox')
    @patch('ui.interfaces.ocr_settings_interface.ComboBox')
    @patch('ui.interfaces.ocr_settings_interface.LineEdit')
    @patch('ui.interfaces.ocr_settings_interface.PushButton')
    @patch('ui.interfaces.ocr_settings_interface.BodyLabel')
    @patch('ui.interfaces.ocr_settings_interface.SubtitleLabel')
    @patch('ui.interfaces.ocr_settings_interface.QFrame')
    @patch('ui.interfaces.ocr_settings_interface.QGridLayout')
    @patch('ui.interfaces.ocr_settings_interface.QHBoxLayout')
    @patch('ui.interfaces.ocr_settings_interface.QVBoxLayout')
    @patch('ui.interfaces.ocr_settings_interface.CardWidget')
    @patch('ui.interfaces.ocr_settings_interface.SettingsManager')
    def test_toggle_persistence(self, mock_settings_cls, mock_card, mock_vbox, mock_hbox, mock_grid, mock_frame, 
                               mock_subtitle, mock_body, mock_push, mock_line, mock_combo, mock_spin, mock_switch):
        """Test toggle state persists to settings"""
        # Ensure QApp
        if QApplication.instance() is None:
            global app
            app = QApplication([])

        from ui.interfaces.ocr_settings_interface import OCRSettingsInterface

        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings_cls.return_value = mock_settings
        
        # Setup mock switch
        mock_switch_instance = MagicMock()
        mock_switch.return_value = mock_switch_instance
        
        # Initialize interface
        interface = OCRSettingsInterface()
        
        # 1. Verify initial load
        mock_settings.get.side_effect = lambda k, d=None: True if k == 'ocr.auto_detect_region_enabled' else d
        interface.load_settings() 
        mock_switch_instance.setChecked.assert_called_with(True)
        
        # 2. Simulate toggle change -> save
        # We simulate checking the switch
        mock_switch_instance.isChecked.return_value = False
        interface.on_settings_changed() # Trigger save
        
        # Verify save called
        mock_settings.set.assert_any_call("ocr.auto_detect_region_enabled", False)
        
        # 3. Verify load from saved value
        mock_settings.get.side_effect = lambda k, d=None: False if k == 'ocr.auto_detect_region_enabled' else d
        interface.load_settings()
        
        mock_switch_instance.setChecked.assert_called_with(False)

if __name__ == '__main__':
    unittest.main()
