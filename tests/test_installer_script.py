from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "scripts" / "installer.nsi"


def installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_license_page_is_configured():
    text = installer_text()

    assert "!insertmacro MUI_PAGE_LICENSE" in text
    assert "installer_license.rtf" in text


def test_installer_outputs_to_dist_directory():
    text = installer_text()

    assert 'OutFile "..\\dist\\呜呜大地图_v${APP_VERSION}_安装程序.exe"' in text


def test_desktop_shortcut_is_optional_and_default_selected():
    text = installer_text()

    assert 'Section "桌面快捷方式" SEC_DESKTOP_SHORTCUT' in text
    assert "SectionIn 1 2" in text
    assert 'CreateShortCut "$DESKTOP\\${APP_NAME}.lnk"' in text
    assert 'Delete "$DESKTOP\\${APP_NAME}.lnk"' in text


def test_upgrade_does_not_run_old_uninstaller():
    text = installer_text()

    assert "Uninstall.exe" not in text.split("Function .onInit", 1)[1].split("FunctionEnd", 1)[0]
    assert "检测到已安装版本，将执行覆盖升级并保留用户数据。" in text


def test_uninstall_has_keep_user_data_checkbox():
    text = installer_text()

    assert '!include "nsDialogs.nsh"' in text
    assert "Function un.KeepUserDataPage" in text
    assert "保留用户数据和设置" in text
    assert "StrCmp $KeepUserDataState ${BST_CHECKED} keep_userdata" in text


def test_uninstall_does_not_delete_install_dir_recursively_first():
    text = installer_text()

    assert 'RMDir /r "$INSTDIR"' not in text
    assert 'RMDir "$INSTDIR"' in text


def test_uninstall_does_not_wildcard_delete_internal_json_configs():
    text = installer_text()

    assert 'Delete "$INSTDIR\\_internal\\*.json"' not in text
