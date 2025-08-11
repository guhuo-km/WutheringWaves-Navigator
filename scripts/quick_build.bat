@echo off
chcp 65001 >nul
echo ====================================================
echo           呜呜大地图 - 快速打包脚本
echo ====================================================
echo.

:: 设置当前目录
cd /d "%~dp0"

echo [1/3] 安装依赖...
pip install pyinstaller PySide6 opencv-python numpy ultralytics torch werkzeug requests -i https://pypi.tuna.tsinghua.edu.cn/simple/

echo [2/3] 清理旧文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /q "*.spec"

echo [3/3] 打包程序...
pyinstaller --onedir --noconsole --name="呜呜大地图" --icon="ico.ico" --add-data "languages;languages" --add-data "models;models" --add-data "tiles;tiles" --add-data "images;images" --add-data "index.html;." main_app.py

echo.
echo ====================================================
echo                   打包完成！
echo ====================================================
echo.
echo 程序位置: dist\呜呜大地图\呜呜大地图.exe
echo.
echo 您可以将整个dist\呜呜大地图文件夹复制给其他用户使用
echo.
pause