; 呜呜大地图 NSIS 安装脚本
; 编码: UTF-8

!define APP_NAME "呜呜大地图"
!define APP_VERSION "2.0.0"
!define APP_PUBLISHER "B站UP主 uid:1876277780"
!define APP_URL "https://space.bilibili.com/1876277780"
!define APP_DESCRIPTION "鸣潮地图导航工具 - 支持OCR坐标识别、路线录制、多语言"

; 包含现代UI
!include "MUI2.nsh"
!include "FileAssociation.nsh"

; 应用程序信息
Name "${APP_NAME}"
Caption "${APP_NAME} ${APP_VERSION} 安装程序"
OutFile "呜呜大地图_v${APP_VERSION}_安装程序.exe"
InstallDir "$PROGRAMFILES\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallPath"
RequestExecutionLevel admin

; 界面设置
!define MUI_ABORTWARNING
!define MUI_ICON "ico.ico"
!define MUI_UNICON "ico.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "ico.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "ico.ico"

; 安装页面
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\呜呜大地图.exe"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH

; 卸载页面
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; 语言
!insertmacro MUI_LANGUAGE "SimpChinese"

; 版本信息
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Copyright (C) 2024 ${APP_PUBLISHER}. 免费开源软件"
VIAddVersionKey "FileDescription" "${APP_DESCRIPTION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey "ProductVersion" "${APP_VERSION}.0"

; 安装类型
InstType "完整安装"
InstType "最小安装"

; 组件
Section "核心程序文件" SEC01
  SectionIn RO 1 2
  
  SetOutPath "$INSTDIR"
  
  ; 主程序文件
  File /r "dist\WutheringWaves_Navigator\*.*"
  
  ; 创建开始菜单快捷方式
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\呜呜大地图.exe" "" "$INSTDIR\呜呜大地图.exe" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
  
  ; 创建桌面快捷方式
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\呜呜大地图.exe" "" "$INSTDIR\呜呜大地图.exe" 0
  
  ; 写入注册表
  WriteRegStr HKLM "Software\${APP_NAME}" "InstallPath" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP_NAME}" "Version" "${APP_VERSION}"
  
  ; 添加到程序和功能
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon" "$INSTDIR\呜呜大地图.exe"
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
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC02} "安装 Microsoft Visual C++ 运行库（如果需要）"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; 安装前检查
Function .onInit
  ; 检查是否已经安装
  ReadRegStr $R0 HKLM "Software\${APP_NAME}" "InstallPath"
  StrCmp $R0 "" done
  
  MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
  "${APP_NAME} 已经安装在 $R0$\n$\n点击 '确定' 卸载已有版本，或点击 '取消' 退出安装。" \
  IDOK uninst
  Abort
  
  uninst:
    ClearErrors
    ExecWait '"$R0\Uninstall.exe" /S _?=$R0'
    IfErrors no_remove_uninstaller done
    no_remove_uninstaller:
  
  done:
FunctionEnd

; 卸载部分
Section "Uninstall"
  ; 删除程序文件
  RMDir /r "$INSTDIR"
  
  ; 删除开始菜单
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  
  ; 删除桌面快捷方式
  Delete "$DESKTOP\${APP_NAME}.lnk"
  
  ; 删除注册表项
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
  
  ; 删除用户数据（可选）
  MessageBox MB_YESNO "是否删除用户数据和设置？" IDNO skip_userdata
  RMDir /r "$APPDATA\${APP_NAME}"
  skip_userdata:
SectionEnd