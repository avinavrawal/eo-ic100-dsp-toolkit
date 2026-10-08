#!/usr/bin/env python3
"""Build the native libusb helpers and launchable macOS app; never talks to USB."""
import plistlib
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "macos-tuner"
APP = ROOT / "research/cache/macos-app/EOIC100 DSP Tuner.app"


def main():
    subprocess.run(["python3", str(ROOT / "tools/caps/build_macos.py")], check=True)
    scratch = ROOT / "research/cache/macos-tuner-build"
    module_cache = ROOT / "research/cache/swift-module-cache"
    swiftpm_cache = ROOT / "research/cache/swiftpm-module-cache"
    environment = dict(os.environ)
    environment["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    environment["SWIFTPM_MODULECACHE_OVERRIDE"] = str(swiftpm_cache)
    subprocess.run(["swift", "build", "-c", "release", "--scratch-path", str(scratch), "--package-path", str(PACKAGE)], check=True, env=environment)
    executable = scratch / "arm64-apple-macosx/release/EOIC100DSPTuner"
    contents = APP / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    if APP.exists():
        shutil.rmtree(APP)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copy2(executable, macos / "EOIC100DSPTuner")
    info = {
        "CFBundleExecutable": "EOIC100DSPTuner",
        "CFBundleIdentifier": "local.eoic100.dsp-tuner",
        "CFBundleName": "EO-IC100 DSP Tuner",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    print(f"APP={APP}")
    print(f"EXECUTABLE={macos / 'EOIC100DSPTuner'}")


if __name__ == "__main__":
    main()
