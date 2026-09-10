r"""Build the portable "ROK Farm" folder and zip it for distribution.

    .venv\Scripts\python packaging\build.py
    .venv\Scripts\python packaging\build.py --no-zip     # faster while iterating
    .venv\Scripts\python packaging\build.py --clean      # discard old build state

What comes out is a folder the recipient extracts anywhere and double-clicks --
no Python, no pip, no PlatformIO, no internet.

    ROK Farm/
      ROK Farm.exe        the menu, and every background role
      firmware/           prebuilt board images + manifest.json
      templates/          the CV templates the runner matches against
      profiles/           behaviour profiles
      data/               the gem classifier
      docs/               the setup guide, VI and EN
      _internal/          python, opencv, onnxruntime, ...

Only _internal comes from PyInstaller. The rest is staged here, deliberately
NOT bundled into the exe, because rok_farm/__init__.py resolves PROJECT_ROOT to
the exe's own folder when frozen -- so the runner reads and WRITES those paths
exactly as it does from source. Bundling them would make templates read-only
and hide a captured template inside a temp directory.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP = DIST / "ROK Farm"
SPEC = ROOT / "packaging" / "rok_farm.spec"

# (source, destination-relative-to-app). Directories are copied whole.
STAGE = [
    ("templates", "templates"),
    ("profiles/default.json", "profiles/default.json"),
    ("profiles/cautious.json", "profiles/cautious.json"),
    ("profiles/aggressive.json", "profiles/aggressive.json"),
    ("firmware", "firmware"),
    ("data/gem_classifier.npz", "data/gem_classifier.npz"),
    ("docs/SETUP.vi.md", "docs/SETUP.vi.md"),
    ("docs/SETUP.en.md", "docs/SETUP.en.md"),
    (".env.example", ".env.example"),
]

# Staged only if present -- a source tree that has never run has neither.
OPTIONAL = {"firmware", "data/gem_classifier.npz"}


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def run_pyinstaller(clean: bool) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--distpath", str(DIST), "--workpath", str(BUILD), str(SPEC)]
    if clean:
        cmd.insert(3, "--clean")
    log(" ".join(cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"[build] PyInstaller failed ({proc.returncode})")
    log(f"PyInstaller finished in {time.time() - t0:.0f}s")


def stage_data() -> list[str]:
    missing = []
    for src_rel, dst_rel in STAGE:
        src = ROOT / src_rel
        dst = APP / dst_rel
        if not src.exists():
            if src_rel in OPTIONAL:
                missing.append(src_rel)
                continue
            raise SystemExit(f"[build] missing required input: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        log(f"staged {src_rel}")

    # Folders the app writes into. Creating them here means the first run does
    # not have to, and an empty folder in the zip tells the user where to look.
    for d in ("logs", "screenshots", "data"):
        (APP / d).mkdir(parents=True, exist_ok=True)
    return missing


def write_readme() -> None:
    (APP / "DOC DAY TRUOC.txt").write_text(
        "ROK FARM -- BAT DAU O DAY\r\n"
        "=========================\r\n\r\n"
        "1. Nhay dup vao 'ROK Farm.exe'\r\n"
        "2. Chon muc 1 (Cai dat lan dau) va lam theo huong dan tren man hinh\r\n"
        "3. Xong thi chon muc 2 de bat dau farm\r\n\r\n"
        "Huong dan day du: mo thu muc docs\\ -> SETUP.vi.md\r\n"
        "Full guide in English: docs\\SETUP.en.md\r\n\r\n"
        "Luu y: cam mach ESP32 vao cong USB co chu UART/COM, va phai dung\r\n"
        "cap TRUYEN DU LIEU (cap chi de sac trong y het nhung khong chay).\r\n",
        encoding="utf-8")
    log("staged DOC DAY TRUOC.txt")


def make_zip() -> Path:
    out = DIST / "ROK-Farm-portable.zip"
    if out.exists():
        out.unlink()
    log(f"zipping -> {out.name} (this takes a minute)")
    t0 = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(APP.rglob("*")):
            if path.is_file():
                z.write(path, Path("ROK Farm") / path.relative_to(APP))
    mb = out.stat().st_size / 1024 / 1024
    log(f"zipped {mb:.0f} MB in {time.time() - t0:.0f}s")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the portable ROK Farm folder")
    ap.add_argument("--no-zip", action="store_true", help="skip the zip step")
    ap.add_argument("--clean", action="store_true",
                    help="discard PyInstaller's cached analysis first")
    args = ap.parse_args()

    if args.clean and APP.exists():
        shutil.rmtree(APP, ignore_errors=True)

    run_pyinstaller(args.clean)
    if not (APP / "ROK Farm.exe").is_file():
        raise SystemExit(f"[build] no exe at {APP / 'ROK Farm.exe'}")

    missing = stage_data()
    write_readme()

    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    log(f"folder: {APP}  ({size / 1024 / 1024:.0f} MB)")

    if missing:
        print()
        for m in missing:
            log(f"WARNING: {m} was not staged -- it does not exist yet.")
        if "firmware" in missing:
            log("         Without firmware/, the app cannot flash a board.")
            log("         Build it first:  cd esp32-s3 && pio run")

    if not args.no_zip:
        make_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
