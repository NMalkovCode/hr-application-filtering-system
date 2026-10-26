# PyInstaller recipe for HRScreening.exe (single file, no console window).
# Build with packaging\build.ps1 rather than calling PyInstaller directly.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / "hr_screening" / "resources"), "hr_screening/resources")]
datas += collect_data_files("docx")          # python-docx's default Word template
datas += collect_data_files("anthropic")
datas += collect_data_files("certifi")
datas += copy_metadata("keyring")            # keyring finds its backends through package metadata
datas += copy_metadata("anthropic")

hiddenimports = [
    "keyring.backends.Windows",
    "win32ctypes.core",
    "truststore",
]

# Qt modules the app never uses - excluded to keep the exe small and quick to start.
qt_unused = [
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets",
    "QtPdf", "QtPdfWidgets", "QtQml", "QtQuick", "QtQuickWidgets", "QtQuick3D", "QtQuickControls2",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtMultimedia", "QtMultimediaWidgets", "QtCharts", "QtDataVisualization", "QtGraphs",
    "QtBluetooth", "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialPort", "QtSerialBus",
    "QtSql", "QtTest", "QtDesigner", "QtHelp", "QtOpenGL", "QtOpenGLWidgets", "QtSvgWidgets",
    "QtRemoteObjects", "QtScxml", "QtStateMachine", "QtTextToSpeech", "QtHttpServer", "QtSpatialAudio",
    "QtNetworkAuth", "QtUiTools", "QtAxContainer", "QtConcurrent", "QtDBus",
]
excludes = [f"PySide6.{m}" for m in qt_unused] + [
    "tkinter", "unittest", "pydoc", "pytest", "pytestqt", "fpdf", "PyInstaller", "IPython", "matplotlib",
]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HRScreening",
    icon=str(ROOT / "packaging" / "app.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,                 # UPX-compressed exes are often flagged by antivirus software
    runtime_tmpdir=None,
)
