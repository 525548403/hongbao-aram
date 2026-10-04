# -*- mode: python ; coding: utf-8 -*-
# 红包乱斗 · 桌面常驻程序打包配置(main_desktop.py)
# 产出: 单文件 exe(无黑框), 常驻系统托盘, 自动弹战绩结果。
#
# 体积优化(2026-10-04): 原 spec 用 collect_all("PySide6") 把整个 PySide6
# (含 WebEngine / Quick3D / Multimedia / 3D 等)全量打进包, 产物 256MB。
# 本程序只用 QtCore/QtGui/QtWidgets, 故改为只收集这三个子模块, 并在
# excludes 中显式排除所有用不到的重型 Qt 模块 —— 体积从 ~256MB 降到 ~30MB,
# 发行版安装包因此可以正常上传。

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

# 只收集实际用到的三个核心模块
NEEDED = ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets")

datas_qt, binaries_qt, hiddenimports_qt = [], [], []
for mod in NEEDED:
    d, b, h = collect_submodules(mod), collect_dynamic_libs(mod), []
    hiddenimports_qt += list(h) + [mod]
    binaries_qt += b

# 显式排除用不到的重型模块(这是减体积的关键)
EXCLUDES = [
    # 3D / 着色器
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.Qt3D",
    # 浏览器引擎(体积最大的一块)
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    # 多媒体 / 位置 / 蓝牙 / NFC 等无关模块
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtLocation", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtTextToSpeech",
    # 其它用不到的
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
    "PySide6.QtQuickWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtTest", "PySide6.QtSql",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtSvgWidgets", "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
    "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtPositioning",
]

a = Analysis(
    ["main_desktop.py"],
    pathex=["."],
    binaries=binaries_qt,
    # 战绩面板首页 index.html + 其依赖 vendor/(chart.js) 必须打进 onefile 包
    # (运行时在 sys._MEIPASS 下, Handler 用 resource_path 读取)。
    datas=datas_qt + [("index.html", "."), ("vendor", "vendor")],
    hiddenimports=[
        "requests", "urllib3", "sqlite3", "websocket",
    ] + hiddenimports_qt,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
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
