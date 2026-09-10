# PyInstaller spec for the portable "ROK Farm" folder.
#
# onedir, not onefile. onefile unpacks ~500 MB of opencv/onnxruntime into a
# temp directory on EVERY launch, which costs 10-30 s each time and leaves the
# app unable to write next to itself. onedir starts in about two seconds and
# keeps templates/, profiles/, data/ and firmware/ visible as ordinary folders
# beside the exe -- which is exactly what rok_farm/__init__.py expects when
# frozen, and what lets a user look at a captured template or edit a profile.
#
# Build with packaging/build.py, not `pyinstaller` directly: the script also
# stages the data folders, which this spec deliberately does not bundle.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent          # noqa: F821  (SPECPATH is injected)

# Roles the exe dispatches to are imported by name at runtime, so PyInstaller's
# static analysis cannot see them. Every one of these is a role in
# rok_farm/roles.py or something a role reaches for lazily.
hiddenimports = [
    "run_farm",
    "app.main", "app.menu", "app.wizard", "app.ui", "app.gui", "app.stats",
    "tkinter", "tkinter.ttk", "tkinter.messagebox",
    "rok_farm.roles", "rok_farm.session_control",
    "tools.flash_board",
    "tools.dev.overnight.farm_full",
    "tools.dev.overnight.watchdog2",
    "tools.dev.overnight.report",
    "tools.remote.discord_bot",
    # Reached through importlib / plugin lookup rather than a plain import.
    "esptool", "serial.tools.list_ports", "winreg",
    "win32gui", "win32con", "win32process", "win32api",
]

datas = []
binaries = []

# esptool ships the ROM stub loaders as package data; without them a flash
# fails at "Downloading stub flasher" with no obvious cause.
datas += collect_data_files("esptool")

# rapidocr carries its ONNX models and a config.yaml next to the code.
for pkg in ("rapidocr_onnxruntime",):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:                                    # noqa: BLE001
        print(f"[spec] WARNING: could not collect {pkg}: {exc}")

a = Analysis(                                                   # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # PlatformIO's toolchain, the test suite and the dev probes have no place
    # in a user's download.
    # tkinter is NOT excluded: app/gui.py is the whole point of the build.
    excludes=["pytest", "playwright", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure)                                               # noqa: F821

exe = EXE(                                                      # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ROK Farm",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed exes are a reliable antivirus false positive
    # Windowed. A console build flashes a black window every time the GUI
    # spawns a role (farm, watchdog, bot are all `cmd /c start` of this same
    # exe), and closing that window would look like the way to stop a run.
    # Every role already writes to logs/overnight/*.log, and builtins.print()
    # is a no-op when sys.stdout is None, so nothing is lost.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(                                                 # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ROK Farm",
)
