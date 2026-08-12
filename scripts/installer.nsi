; 呜呜大地图 NSIS 安装脚本
; 编码: UTF-8

Unicode true

!define APP_NAME "呜呜大地图"
!define APP_VERSION "0.1.7"
!define APP_EXE "WutheringWaves-Navigator-Smart.exe"
!define APP_PUBLISHER "B站UP主 uid:1876277780"
!define APP_URL "https://space.bilibili.com/1876277780"
!define APP_DESCRIPTION "鸣潮地图导航工具 - 支持OCR坐标识别、路线录制、多语言"

; 包含现代UI
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "Sections.nsh"
!insertmacro GetSize

Var KeepUserDataCheckbox
Var KeepUserDataState
Var MigrationSource
Var MigrationTarget
Var MigrationConflictTarget
Var MigrationCandidate
Var MigrationIndex
Var ReplaceCheckSource
Var ReplaceCheckTarget

!macro MigrateLegacyFile SOURCE TARGET CONFLICT
  StrCpy $MigrationSource "${SOURCE}"
  StrCpy $MigrationTarget "${TARGET}"
  StrCpy $MigrationConflictTarget "${CONFLICT}"
  Call MigrateLegacyFile
!macroend

!macro MigrateLegacyDirectory SOURCE TARGET CONFLICT
  StrCpy $MigrationSource "${SOURCE}"
  StrCpy $MigrationTarget "${TARGET}"
  StrCpy $MigrationConflictTarget "${CONFLICT}"
  Call MigrateLegacyDirectory
!macroend

; 应用程序信息
Name "${APP_NAME}"
Caption "${APP_NAME} ${APP_VERSION} 安装程序"
OutFile "..\dist\呜呜大地图_v${APP_VERSION}_安装程序.exe"
InstallDir "$PROGRAMFILES\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallPath"
RequestExecutionLevel admin

; 界面设置
!define MUI_ABORTWARNING
!define MUI_ICON "..\assets\ico.ico"
!define MUI_UNICON "..\assets\ico.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "..\assets\ico.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\assets\ico.ico"

; 安装页面
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "installer_license.rtf"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH

; 卸载页面
!insertmacro MUI_UNPAGE_WELCOME
UninstPage custom un.KeepUserDataPage un.KeepUserDataPageLeave
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; 语言
!insertmacro MUI_LANGUAGE "SimpChinese"

; 版本信息
VIProductVersion "0.1.7.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Copyright (C) 2024 ${APP_PUBLISHER}. 免费开源软件"
VIAddVersionKey "FileDescription" "${APP_DESCRIPTION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"

; 安装类型
InstType "完整安装"
InstType "最小安装"

; 组件
Section "核心程序文件" SEC01
  SectionIn RO 1 2
  
  SetOutPath "$INSTDIR"
  SetOverwrite on
  StrCpy $ReplaceCheckSource "$INSTDIR\${APP_EXE}"
  StrCpy $ReplaceCheckTarget "$INSTDIR\${APP_EXE}.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\WutheringWaves-Updater.exe"
  StrCpy $ReplaceCheckTarget "$INSTDIR\WutheringWaves-Updater.exe.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\Uninstall.exe"
  StrCpy $ReplaceCheckTarget "$INSTDIR\Uninstall.exe.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\version.json"
  StrCpy $ReplaceCheckTarget "$INSTDIR\version.json.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\README.txt"
  StrCpy $ReplaceCheckTarget "$INSTDIR\README.txt.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\_internal"
  StrCpy $ReplaceCheckTarget "$INSTDIR\_internal.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\src"
  StrCpy $ReplaceCheckTarget "$INSTDIR\src.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\languages"
  StrCpy $ReplaceCheckTarget "$INSTDIR\languages.install-check"
  Call CheckReplaceablePath
  StrCpy $ReplaceCheckSource "$INSTDIR\cache\minimap_tiles"
  StrCpy $ReplaceCheckTarget "$INSTDIR\cache\minimap_tiles.install-check"
  Call CheckReplaceablePath
  Call MigrateLegacyUserData
  Delete "$INSTDIR\version.json"
  Delete "$INSTDIR\README.txt"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\src"
  RMDir /r "$INSTDIR\languages"
  RMDir /r "$INSTDIR\cache\minimap_tiles"
  IfFileExists "$INSTDIR\_internal\*.*" program_cleanup_failed
  IfFileExists "$INSTDIR\src\*.*" program_cleanup_failed
  IfFileExists "$INSTDIR\languages\*.*" program_cleanup_failed
  IfFileExists "$INSTDIR\cache\minimap_tiles\*.*" program_cleanup_failed
  Goto program_cleanup_done
  program_cleanup_failed:
    MessageBox MB_ICONSTOP|MB_OK "旧版程序文件仍被占用，安装已停止。请完全退出软件后重试。"
    Abort
  program_cleanup_done:
  
  ; 主程序文件
  File /r "..\dist\WutheringWaves-Navigator-Smart\*.*"
  
  ; 创建开始菜单快捷方式
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
  
  ; 写入注册表
  WriteRegStr HKLM "Software\${APP_NAME}" "InstallPath" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP_NAME}" "Version" "${APP_VERSION}"
  WriteRegStr HKLM "Software\${APP_NAME}" "UpdateMode" "installer"
  WriteRegStr HKLM "Software\${APP_NAME}" "AppId" "wutheringwaves-navigator"
  
  ; 添加到程序和功能
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1
  
  ; 计算安装大小
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "EstimatedSize" "$0"
  
  ; 创建卸载程序
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "桌面快捷方式" SEC_DESKTOP_SHORTCUT
  SectionIn 1 2

  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

Section -DesktopShortcutCleanup
  SectionGetFlags ${SEC_DESKTOP_SHORTCUT} $0
  IntOp $0 $0 & ${SF_SELECTED}
  IntCmp $0 0 remove_shortcut done done

  remove_shortcut:
    Delete "$DESKTOP\${APP_NAME}.lnk"

  done:
SectionEnd

Section "Visual C++ 运行库" SEC02
  SectionIn 1
  
  ; 检查是否需要安装VC++运行库
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Version"
  StrCmp $0 "" 0 vcredist_done
  
  DetailPrint "安装 Microsoft Visual C++ 运行库..."
  ; 这里可以添加VC++运行库的安装
  
  vcredist_done:
SectionEnd

; 组件描述
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC01} "安装 ${APP_NAME} 的核心程序文件和必要组件"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP_SHORTCUT} "在桌面创建 ${APP_NAME} 快捷方式"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC02} "安装 Microsoft Visual C++ 运行库（如果需要）"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; 安装前检查
Function .onInit
  ; 检查是否已经安装
  ReadRegStr $R0 HKLM "Software\${APP_NAME}" "InstallPath"
  StrCmp $R0 "" done

  StrCpy $INSTDIR "$R0"
  DetailPrint "检测到已安装版本，将执行覆盖升级并保留用户数据。"

  done:
FunctionEnd

Function CheckReplaceablePath
  IfFileExists "$ReplaceCheckSource" replace_check_start
  IfFileExists "$ReplaceCheckSource\*.*" replace_check_start replace_check_done
  replace_check_start:
    IfFileExists "$ReplaceCheckTarget" replace_check_temp_exists
    IfFileExists "$ReplaceCheckTarget\*.*" replace_check_temp_exists
    ClearErrors
    Rename "$ReplaceCheckSource" "$ReplaceCheckTarget"
    IfErrors replace_check_failed
    ClearErrors
    Rename "$ReplaceCheckTarget" "$ReplaceCheckSource"
    IfErrors replace_check_restore_failed
    Goto replace_check_done
  replace_check_temp_exists:
    MessageBox MB_ICONSTOP|MB_OK "发现上次安装检查残留，安装已停止: $ReplaceCheckTarget"
    Abort
  replace_check_failed:
    MessageBox MB_ICONSTOP|MB_OK "程序文件正在使用，安装已停止。请完全退出软件后重试: $ReplaceCheckSource"
    Abort
  replace_check_restore_failed:
    MessageBox MB_ICONSTOP|MB_OK "安装检查无法恢复原路径，安装已停止: $ReplaceCheckSource"
    Abort
  replace_check_done:
FunctionEnd

Function ResolveMigrationCandidate
  StrCpy $MigrationCandidate "$MigrationConflictTarget"
  StrCpy $MigrationIndex 1
  migration_candidate_loop:
    IfFileExists "$MigrationCandidate" migration_candidate_taken
    IfFileExists "$MigrationCandidate\*.*" migration_candidate_taken migration_candidate_done
  migration_candidate_taken:
    IntOp $MigrationIndex $MigrationIndex + 1
    StrCpy $MigrationCandidate "$MigrationConflictTarget.$MigrationIndex"
    Goto migration_candidate_loop
  migration_candidate_done:
    RMDir "$MigrationCandidate"
FunctionEnd

Function MigrateLegacyFile
  IfFileExists "$MigrationSource" 0 migration_file_done
  IfFileExists "$MigrationTarget" migration_file_conflict
  ClearErrors
  Rename "$MigrationSource" "$MigrationTarget"
  IfErrors migration_file_failed
  Goto migration_file_done
  migration_file_conflict:
    Call ResolveMigrationCandidate
    ClearErrors
    Rename "$MigrationSource" "$MigrationCandidate"
    IfErrors migration_file_failed
    Goto migration_file_done
  migration_file_failed:
    MessageBox MB_ICONSTOP|MB_OK "旧版用户数据迁移失败，安装已停止: $MigrationSource"
    Abort
  migration_file_done:
FunctionEnd

Function MigrateLegacyDirectory
  IfFileExists "$MigrationSource\*.*" 0 migration_directory_done
  IfFileExists "$MigrationTarget\*.*" migration_directory_conflict
  RMDir "$MigrationTarget"
  ClearErrors
  Rename "$MigrationSource" "$MigrationTarget"
  IfErrors migration_directory_failed
  Goto migration_directory_done
  migration_directory_conflict:
    Call ResolveMigrationCandidate
    ClearErrors
    Rename "$MigrationSource" "$MigrationCandidate"
    IfErrors migration_directory_failed
    Goto migration_directory_done
  migration_directory_failed:
    MessageBox MB_ICONSTOP|MB_OK "旧版用户数据目录迁移失败，安装已停止: $MigrationSource"
    Abort
  migration_directory_done:
FunctionEnd

Function MigrateLegacyUserData
  CreateDirectory "$INSTDIR\config"
  CreateDirectory "$INSTDIR\config\legacy\root"
  CreateDirectory "$INSTDIR\config\legacy\src"
  CreateDirectory "$INSTDIR\config\legacy\internal"
  CreateDirectory "$INSTDIR\logs\legacy\root"
  CreateDirectory "$INSTDIR\logs\legacy\src"
  CreateDirectory "$INSTDIR\logs\legacy\internal"

  !insertmacro MigrateLegacyFile "$INSTDIR\app_settings.json" "$INSTDIR\config\app_settings.json" "$INSTDIR\config\legacy\root\app_settings.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\ocr_config.json" "$INSTDIR\config\ocr_config.json" "$INSTDIR\config\legacy\root\ocr_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\language_config.json" "$INSTDIR\config\language_config.json" "$INSTDIR\config\legacy\root\language_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\calibration_data.json" "$INSTDIR\config\calibration_data.json" "$INSTDIR\config\legacy\root\calibration_data.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\maps.json" "$INSTDIR\config\maps.json" "$INSTDIR\config\legacy\root\maps.json"

  !insertmacro MigrateLegacyFile "$INSTDIR\src\app_settings.json" "$INSTDIR\config\app_settings.json" "$INSTDIR\config\legacy\src\app_settings.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\src\ocr_config.json" "$INSTDIR\config\ocr_config.json" "$INSTDIR\config\legacy\src\ocr_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\src\language_config.json" "$INSTDIR\config\language_config.json" "$INSTDIR\config\legacy\src\language_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\src\calibration_data.json" "$INSTDIR\config\calibration_data.json" "$INSTDIR\config\legacy\src\calibration_data.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\src\maps.json" "$INSTDIR\config\maps.json" "$INSTDIR\config\legacy\src\maps.json"

  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\app_settings.json" "$INSTDIR\config\app_settings.json" "$INSTDIR\config\legacy\internal\app_settings.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\ocr_config.json" "$INSTDIR\config\ocr_config.json" "$INSTDIR\config\legacy\internal\ocr_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\language_config.json" "$INSTDIR\config\language_config.json" "$INSTDIR\config\legacy\internal\language_config.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\calibration_data.json" "$INSTDIR\config\calibration_data.json" "$INSTDIR\config\legacy\internal\calibration_data.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\maps.json" "$INSTDIR\config\maps.json" "$INSTDIR\config\legacy\internal\maps.json"

  !insertmacro MigrateLegacyFile "$INSTDIR\ocr_logs.json" "$INSTDIR\logs\ocr_logs.json" "$INSTDIR\logs\legacy\root\ocr_logs.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\src\ocr_logs.json" "$INSTDIR\logs\ocr_logs.json" "$INSTDIR\logs\legacy\src\ocr_logs.json"
  !insertmacro MigrateLegacyFile "$INSTDIR\_internal\ocr_logs.json" "$INSTDIR\logs\ocr_logs.json" "$INSTDIR\logs\legacy\internal\ocr_logs.json"

  !insertmacro MigrateLegacyDirectory "$INSTDIR\src\recorded_routes" "$INSTDIR\recorded_routes" "$INSTDIR\recorded_routes\legacy-src"
  !insertmacro MigrateLegacyDirectory "$INSTDIR\src\tiles" "$INSTDIR\tiles" "$INSTDIR\tiles\legacy-src"
  !insertmacro MigrateLegacyDirectory "$INSTDIR\src\images" "$INSTDIR\images" "$INSTDIR\images\legacy-src"
  !insertmacro MigrateLegacyDirectory "$INSTDIR\_internal\recorded_routes" "$INSTDIR\recorded_routes" "$INSTDIR\recorded_routes\legacy-internal"
  !insertmacro MigrateLegacyDirectory "$INSTDIR\_internal\tiles" "$INSTDIR\tiles" "$INSTDIR\tiles\legacy-internal"
  !insertmacro MigrateLegacyDirectory "$INSTDIR\_internal\images" "$INSTDIR\images" "$INSTDIR\images\legacy-internal"
FunctionEnd

Function un.onInit
  StrCpy $KeepUserDataState ${BST_CHECKED}
FunctionEnd

Function un.KeepUserDataPage
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 24u "卸载 ${APP_NAME} 时可以保留用户数据和设置。"
  Pop $0
  ${NSD_CreateCheckbox} 0 34u 100% 12u "保留用户数据和设置"
  Pop $KeepUserDataCheckbox
  ${NSD_Check} $KeepUserDataCheckbox

  nsDialogs::Show
FunctionEnd

Function un.KeepUserDataPageLeave
  ${NSD_GetState} $KeepUserDataCheckbox $KeepUserDataState
FunctionEnd

; 卸载部分
Section "Uninstall"
  ; 删除开始菜单
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  
  ; 删除桌面快捷方式
  Delete "$DESKTOP\${APP_NAME}.lnk"
  
  ; 删除注册表项
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
  
  ; 删除程序文件。默认保留用户数据，不递归删除整个安装目录。
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\WutheringWaves-Updater.exe"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\version.json"
  Delete "$INSTDIR\Uninstall.exe"

  RMDir /r "$INSTDIR\languages"
  RMDir /r "$INSTDIR\src"
  RMDir /r "$INSTDIR\_internal"

  ; 小地图瓦片和索引属于程序管理缓存，不作为用户数据保留。
  RMDir /r "$INSTDIR\cache\minimap_tiles"

  StrCmp $KeepUserDataState ${BST_CHECKED} keep_userdata
    RMDir /r "$APPDATA\${APP_NAME}"
    RMDir /r "$INSTDIR\config"
    RMDir /r "$INSTDIR\logs"
    RMDir /r "$INSTDIR\.update"
    RMDir /r "$INSTDIR\recorded_routes"
    RMDir /r "$INSTDIR\tiles"
    RMDir /r "$INSTDIR\images"
    RMDir /r "$INSTDIR\downloads"
    RMDir /r "$INSTDIR\debug"
    RMDir /r "$INSTDIR\cache"
    Delete "$INSTDIR\app_settings.json"
    Delete "$INSTDIR\ocr_config.json"
    Delete "$INSTDIR\language_config.json"
    Delete "$INSTDIR\calibration_data.json"
    Delete "$INSTDIR\maps.json"
    RMDir /r "$INSTDIR\_internal\recorded_routes"
    RMDir /r "$INSTDIR\_internal\tiles"
    RMDir /r "$INSTDIR\_internal\images"
    Delete "$INSTDIR\_internal\app_settings.json"
    Delete "$INSTDIR\_internal\ocr_config.json"
    Delete "$INSTDIR\_internal\language_config.json"
    Delete "$INSTDIR\_internal\calibration_data.json"
    Delete "$INSTDIR\_internal\maps.json"
  keep_userdata:

  RMDir "$INSTDIR"
SectionEnd
