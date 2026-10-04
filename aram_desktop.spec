# -*- mode: python ; coding: utf-8 -*-
# 红包乱斗 · 桌面常驻程序打包配置(main_desktop.py)
# 产出: 单文件 exe(无黑框), 常驻系统托盘, 自动弹战绩结果。

from PyInstaller.utils.hooks import collect_all

# 收集 PySide6 全部子模块 + 数据 + 二进制(含 Qt 平台插件 qwindows 等)
datas_qt, binaries_qt, hiddenimports_qt = collect_all("PySide6")

a = Analysis(
    ["main_desktop.py"],
    pathex=["."],
    binaries=binaries_qt,
    datas=datas_qt,
    hiddenimports=[
        "requests", "urllib3", "sqlite3", "websocket",
    ] + hiddenimports_qt,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aram_score_desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # 无黑框
    windowed=True,       # Windows GUI 子系统
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
