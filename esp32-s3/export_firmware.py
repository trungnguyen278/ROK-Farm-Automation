"""PlatformIO post-build hook: copy the flashable images into ../firmware/.

End users must never need PlatformIO. `pio run` here produces the four images
esptool writes, and this drops them plus a manifest of their flash offsets into
firmware/ at the repo root, where tools/flash_board.py picks them up.

The manifest carries the offsets rather than tools/flash_board.py hardcoding
them, so a partition-table change here cannot silently desync the flasher.
"""
import hashlib
import json
import shutil
from pathlib import Path

Import("env")  # noqa: F821  (injected by PlatformIO's SCons)

PROJECT = Path(env.subst("$PROJECT_DIR")).parent  # noqa: F821
OUT = PROJECT / "firmware"

# ESP32-S3 flash layout. boot_app0 comes from the framework package, the other
# three from this build.
#
# boot_app0 initialises the OTA-select region. Skip it and the bootloader can
# be left pointing at a stale slot on a board that was flashed before -- so a
# missing one is a hard error here, not a warning. $FRAMEWORK_DIR is NOT
# substitutable in a post-action (it expands to nothing, which silently
# produced a firmware/ with three of the four images), hence the package
# lookup below.
def _framework_dir(env) -> Path:
    return Path(env.PioPlatform().get_package_dir("framework-arduinoespressif32"))


def _layout(env):
    fw = _framework_dir(env)
    return [
        ("0x0000", Path(env.subst("$BUILD_DIR")) / "bootloader.bin", "bootloader.bin"),
        ("0x8000", Path(env.subst("$BUILD_DIR")) / "partitions.bin", "partitions.bin"),
        ("0xe000", fw / "tools" / "partitions" / "boot_app0.bin", "boot_app0.bin"),
        ("0x10000", Path(env.subst("$BUILD_DIR/${PROGNAME}.bin")), "firmware.bin"),
    ]


def export(source, target, env):  # noqa: ARG001
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    for offset, src, name in _layout(env):
        if not src.is_file():
            raise Exception(f"export_firmware: missing image {src}")
        dst = OUT / name
        shutil.copy2(src, dst)
        parts.append({
            "offset": offset,
            "file": name,
            "size": dst.stat().st_size,
            "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        })
        print(f"export_firmware: {name:<16} {offset:>8}  {dst.stat().st_size:>8} B")

    manifest = {
        "board": env.subst("$BOARD"),
        "chip": "esp32s3",
        "flash_mode": env.BoardConfig().get("build.flash_mode", "qio"),
        "flash_freq": "80m",
        "flash_size": env.BoardConfig().get("upload.flash_size", "16MB"),
        "parts": parts,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"export_firmware: wrote {OUT / 'manifest.json'}")


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", export)  # noqa: F821
