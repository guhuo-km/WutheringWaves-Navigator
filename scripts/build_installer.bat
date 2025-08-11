@echo off
chcp 65001 >nul
echo ====================================================
echo           呜呜大地图 - 自动打包构建脚本
echo ====================================================
echo.

:: 设置构建目录
set BUILD_DIR=%~dp0
cd /d "%BUILD_DIR%"

echo [1/6] 检查Python环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到Python环境！
    pause
    exit /b 1
)

echo [2/6] 检查必要依赖...
python -c "import PyQt6" >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装PyInstaller...
    pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple/
)

echo [3/6] 清理旧的构建文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /q "*.spec"

echo [4/6] 使用PyInstaller打包程序...
echo 这可能需要几分钟时间，请耐心等待...
pyinstaller --clean ^
    --name="呜呜大地图" ^
    --icon="ico.ico" ^
    --add-data "languages;languages" ^
    --add-data "models;models" ^
    --add-data "tiles;tiles" ^
    --add-data "images;images" ^
    --add-data "recorded_routes;recorded_routes" ^
    --add-data "index.html;." ^
    --add-data "ico.png;." ^
    --hidden-import="PySide6.QtCore" ^
    --hidden-import="PySide6.QtWidgets" ^
    --hidden-import="PySide6.QtWebEngineWidgets" ^
    --hidden-import="PySide6.QtWebEngineCore" ^
    --hidden-import="PySide6.QtWebChannel" ^
    --hidden-import="numpy" ^
    --hidden-import="cv2" ^
    --hidden-import="ultralytics" ^
    --hidden-import="torch" ^
    --hidden-import="language_manager" ^
    --hidden-import="ocr_manager" ^
    --hidden-import="route_recorder" ^
    --hidden-import="transparent_overlay" ^
    --hidden-import="separated_map_window" ^
    --hidden-import="route_list_dialog" ^
    --exclude-module="tkinter" ^
    --exclude-module="matplotlib" ^
    --noconsole ^
    --onedir ^
    main_app.py

if %errorlevel% neq 0 (
    echo 错误: PyInstaller打包失败！
    pause
    exit /b 1
)

echo [5/6] 检查NSIS安装...
where makensis >nul 2>&1
if %errorlevel% neq 0 (
    echo 警告: 未找到NSIS，跳过安装程序制作
    echo 您可以手动下载NSIS并运行installer.nsi来制作安装程序
    goto skip_nsis
)

echo [6/6] 制作安装程序...
makensis installer.nsi
if %errorlevel% neq 0 (
    echo 警告: 安装程序制作失败，但可执行文件已成功打包
) else (
    echo 安装程序制作完成！
)

:skip_nsis

echo.
echo ====================================================
echo                   构建完成！
echo ====================================================
echo.
echo 可执行文件位置: dist\WutheringWaves_Navigator\
echo 主程序: dist\WutheringWaves_Navigator\呜呜大地图.exe
echo.
if exist "呜呜大地图_v2.0.0_安装程序.exe" (
    echo 安装程序: 呜呜大地图_v2.0.0_安装程序.exe
    echo.
)
echo 您可以将dist文件夹中的内容打包分发，或使用安装程序。
echo.
pause