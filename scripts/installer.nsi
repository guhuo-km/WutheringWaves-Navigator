; 呜呜大地图 NSIS 安装脚本
; 编码: UTF-8

Unicode true

!define APP_NAME "呜呜大地图"
!define APP_VERSION "0.1.6.21"
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
VIProductVersion "0.1.6.21"
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
  Delete "$INSTDIR\version.json"
  RMDir /r "$INSTDIR\cache\minimap_tiles"
  
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
  RMDir /r "$INSTDIR\_internal\_polars_runtime_32"
  RMDir /r "$INSTDIR\_internal\_tcl_data"
  RMDir /r "$INSTDIR\_internal\_tk_data"
  RMDir /r "$INSTDIR\_internal\assets"
  RMDir /r "$INSTDIR\_internal\certifi"
  RMDir /r "$INSTDIR\_internal\charset_normalizer"
  RMDir /r "$INSTDIR\_internal\contourpy"
  RMDir /r "$INSTDIR\_internal\cv2"
  RMDir /r "$INSTDIR\_internal\dateutil"
  RMDir /r "$INSTDIR\_internal\js"
  RMDir /r "$INSTDIR\_internal\kiwisolver"
  RMDir /r "$INSTDIR\_internal\lap"
  RMDir /r "$INSTDIR\_internal\markupsafe"
  RMDir /r "$INSTDIR\_internal\matplotlib"
  RMDir /r "$INSTDIR\_internal\models"
  RMDir /r "$INSTDIR\_internal\numpy"
  RMDir /r "$INSTDIR\_internal\numpy.libs"
  RMDir /r "$INSTDIR\_internal\pandas"
  RMDir /r "$INSTDIR\_internal\pandas.libs"
  RMDir /r "$INSTDIR\_internal\PIL"
  RMDir /r "$INSTDIR\_internal\psutil"
  RMDir /r "$INSTDIR\_internal\PySide6"
  RMDir /r "$INSTDIR\_internal\qfluentwidgets"
  RMDir /r "$INSTDIR\_internal\qframelesswindow"
  RMDir /r "$INSTDIR\_internal\scipy"
  RMDir /r "$INSTDIR\_internal\scipy.libs"
  RMDir /r "$INSTDIR\_internal\setuptools"
  RMDir /r "$INSTDIR\_internal\shiboken6"
  RMDir /r "$INSTDIR\_internal\tcl8"
  RMDir /r "$INSTDIR\_internal\templates"
  RMDir /r "$INSTDIR\_internal\torch"
  RMDir /r "$INSTDIR\_internal\torchvision"
  RMDir /r "$INSTDIR\_internal\tzdata"
  RMDir /r "$INSTDIR\_internal\ui"
  RMDir /r "$INSTDIR\_internal\ultralytics"
  RMDir /r "$INSTDIR\_internal\win32"
  RMDir /r "$INSTDIR\_internal\win32com"
  RMDir /r "$INSTDIR\_internal\yaml"

  Delete "$INSTDIR\_internal\*.pyd"
  Delete "$INSTDIR\_internal\*.dll"
  Delete "$INSTDIR\_internal\*.py"

  StrCmp $KeepUserDataState ${BST_CHECKED} keep_userdata
    RMDir /r "$APPDATA\${APP_NAME}"
    RMDir /r "$INSTDIR\logs"
    RMDir /r "$INSTDIR\.update"
    RMDir /r "$INSTDIR\recorded_routes"
    RMDir /r "$INSTDIR\tiles"
    RMDir /r "$INSTDIR\images"
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

  RMDir "$INSTDIR\_internal"
  RMDir "$INSTDIR"
SectionEnd
