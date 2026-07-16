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


def test_core_install_overwrites_existing_program_files():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert "SetOverwrite on" in core_section
    assert core_section.index("SetOverwrite on") < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')


def test_core_install_removes_stale_root_version_before_copying_files():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert 'Delete "$INSTDIR\\version.json"' in core_section
    assert core_section.index('Delete "$INSTDIR\\version.json"') < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')


def test_core_install_removes_known_legacy_root_program_artifacts():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert 'Delete "$INSTDIR\\README.txt"' in core_section
    assert 'RMDir /r "$INSTDIR\\languages"' in core_section
    assert core_section.index('Delete "$INSTDIR\\README.txt"') < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')
    assert core_section.index('RMDir /r "$INSTDIR\\languages"') < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')


def test_core_install_replaces_old_minimap_tile_cache_before_copying_files():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert 'RMDir /r "$INSTDIR\\cache\\minimap_tiles"' in core_section
    assert core_section.index('RMDir /r "$INSTDIR\\cache\\minimap_tiles"') < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')


def test_core_install_migrates_legacy_user_data_then_replaces_program_trees():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert "Call MigrateLegacyUserData" in core_section
    assert 'RMDir /r "$INSTDIR\\_internal"' in core_section
    assert 'RMDir /r "$INSTDIR\\src"' in core_section
    assert core_section.index("Call MigrateLegacyUserData") < core_section.index('RMDir /r "$INSTDIR\\_internal"')
    assert core_section.index('RMDir /r "$INSTDIR\\_internal"') < core_section.index('File /r "..\\dist\\WutheringWaves-Navigator-Smart\\*.*"')


def test_installer_migrates_known_legacy_ocr_logs():
    text = installer_text()
    migration_function = text.split("Function MigrateLegacyUserData", 1)[1].split("FunctionEnd", 1)[0]

    assert '"$INSTDIR\\ocr_logs.json" "$INSTDIR\\logs\\ocr_logs.json"' in migration_function
    assert '"$INSTDIR\\src\\ocr_logs.json" "$INSTDIR\\logs\\ocr_logs.json"' in migration_function
    assert '"$INSTDIR\\_internal\\ocr_logs.json" "$INSTDIR\\logs\\ocr_logs.json"' in migration_function


def test_legacy_migration_preserves_conflicts_before_program_tree_cleanup():
    text = installer_text()
    resolver = text.split("Function ResolveMigrationCandidate", 1)[1].split("FunctionEnd", 1)[0]
    file_function = text.split("Function MigrateLegacyFile", 1)[1].split("FunctionEnd", 1)[0]
    directory_function = text.split("Function MigrateLegacyDirectory", 1)[1].split("FunctionEnd", 1)[0]

    assert "$MigrationConflictTarget" in resolver
    assert "Call ResolveMigrationCandidate" in file_function
    assert 'Rename "$MigrationSource" "$MigrationCandidate"' in file_function
    assert "Call ResolveMigrationCandidate" in directory_function
    assert 'Rename "$MigrationSource" "$MigrationCandidate"' in directory_function


def test_uninstall_removes_program_managed_internal_tree_recursively():
    text = installer_text()
    uninstall_section = text.split('Section "Uninstall"', 1)[1].split("SectionEnd", 1)[0]

    assert 'RMDir /r "$INSTDIR\\_internal"' in uninstall_section


def test_core_install_aborts_when_program_tree_cleanup_is_incomplete():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert 'IfFileExists "$INSTDIR\\_internal\\*.*" program_cleanup_failed' in core_section
    assert 'IfFileExists "$INSTDIR\\src\\*.*" program_cleanup_failed' in core_section
    assert 'IfFileExists "$INSTDIR\\cache\\minimap_tiles\\*.*" program_cleanup_failed' in core_section
    assert "program_cleanup_failed:" in core_section
    assert "Abort" in core_section


def test_core_install_checks_replaceability_before_migration_or_deletion():
    text = installer_text()
    core_section = text.split('Section "核心程序文件" SEC01', 1)[1].split("SectionEnd", 1)[0]

    assert "Call CheckReplaceablePath" in core_section
    first_check = core_section.index("Call CheckReplaceablePath")
    assert first_check < core_section.index("Call MigrateLegacyUserData")
    assert first_check < core_section.index('RMDir /r "$INSTDIR\\_internal"')
    assert 'StrCpy $ReplaceCheckSource "$INSTDIR\\${APP_EXE}"' in core_section
    assert 'StrCpy $ReplaceCheckSource "$INSTDIR\\WutheringWaves-Updater.exe"' in core_section
    assert 'StrCpy $ReplaceCheckSource "$INSTDIR\\Uninstall.exe"' in core_section
    assert 'StrCpy $ReplaceCheckSource "$INSTDIR\\version.json"' in core_section
    assert 'StrCpy $ReplaceCheckSource "$INSTDIR\\README.txt"' in core_section


def test_legacy_migration_aborts_when_a_rename_fails():
    text = installer_text()
    file_function = text.split("Function MigrateLegacyFile", 1)[1].split("FunctionEnd", 1)[0]
    directory_function = text.split("Function MigrateLegacyDirectory", 1)[1].split("FunctionEnd", 1)[0]

    assert "ClearErrors" in file_function
    assert "IfErrors migration_file_failed" in file_function
    assert "Abort" in file_function
    assert "ClearErrors" in directory_function
    assert "IfErrors migration_directory_failed" in directory_function
    assert "Abort" in directory_function


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


def test_uninstall_always_removes_managed_minimap_cache():
    text = installer_text()
    uninstall_section = text.split('Section "Uninstall"', 1)[1].split("SectionEnd", 1)[0]

    assert 'RMDir /r "$INSTDIR\\cache\\minimap_tiles"' in uninstall_section
    assert uninstall_section.index('RMDir /r "$INSTDIR\\cache\\minimap_tiles"') < uninstall_section.index("StrCmp $KeepUserDataState")
