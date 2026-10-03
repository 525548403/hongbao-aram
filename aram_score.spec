# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['aram_web.py'],
    pathex=['.'],
    binaries=[],
    datas=[('index.html', '.'), ('vendor/chart.umd.min.js', 'vendor')],
    hiddenimports=['requests', 'urllib3', 'sqlite3'],
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
    name='aram_score',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
