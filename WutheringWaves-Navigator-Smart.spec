# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('D:\\python2\\WutheringWaves-Navigator-github\\languages', 'languages'), ('D:\\python2\\WutheringWaves-Navigator-github\\src\\models\\class_names.txt', 'models'), ('D:\\python2\\WutheringWaves-Navigator-github\\src\\models\\coord_ocr.onnx', 'models'), ('D:\\python2\\WutheringWaves-Navigator-github\\src\\models\\README.md', 'models'), ('D:\\python2\\WutheringWaves-Navigator-github\\templates', 'templates'), ('D:\\python2\\WutheringWaves-Navigator-github\\js', 'js'), ('D:\\python2\\WutheringWaves-Navigator-github\\assets', 'assets'), ('D:\\python2\\WutheringWaves-Navigator-github\\version.json', '.'), ('D:\\python2\\WutheringWaves-Navigator-github\\src\\index.html', '.'), ('D:\\python2\\WutheringWaves-Navigator-github\\src\\jszip.min.js', '.')]
binaries = []
hiddenimports = ['PySide6.QtCore', 'PySide6.QtWidgets', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtGui', 'PySide6.QtNetwork', 'PySide6.QtWebChannel']
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('qfluentwidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('qframelesswindow')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:\\python2\\WutheringWaves-Navigator-github\\src\\main_app.py'],
    pathex=['D:\\python2\\WutheringWaves-Navigator-github\\src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'torch', 'torchvision', 'ultralytics', 'matplotlib', 'pandas', 'scipy', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WutheringWaves-Navigator-Smart',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:\\python2\\WutheringWaves-Navigator-github\\assets\\ico.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WutheringWaves-Navigator-Smart',
)
