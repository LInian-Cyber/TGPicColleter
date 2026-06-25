# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


root = Path(SPECPATH)
one_file = os.environ.get("TG_PIC_COLLECTOR_ONEFILE") == "1"

datas = [
    (str(root / "tg_pic_collector" / "assets"), "tg_pic_collector/assets"),
]
for legal_file in ("LICENSE",):
    if (root / legal_file).exists():
        datas.append((str(root / legal_file), "."))
datas += collect_data_files("qfluentwidgets")
datas += copy_metadata("PySide6-Fluent-Widgets")

hidden_imports = collect_submodules("qfluentwidgets")
hidden_imports += [
    "PIL.ImageQt",
    "qrcode.image.pil",
    "telethon.crypto.aes",
    "telethon.crypto.aesctr",
]

a = Analysis(
    ["main.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest.mock"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

common_exe_args = dict(
    name="TG Pic Collector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "tg_pic_collector" / "assets" / "telegram-app-icon.png"),
)
if sys.platform == "win32":
    common_exe_args["version"] = str(root / "version_info.txt")

if one_file:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **common_exe_args,
    )
    if sys.platform == "darwin":
        app = BUNDLE(
            exe,
            name="TG Pic Collector.app",
            icon=str(root / "tg_pic_collector" / "assets" / "telegram-app-icon.png"),
            bundle_identifier="io.github.tg-pic-collector",
        )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        contents_directory="_internal",
        **common_exe_args,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="TG Pic Collector",
    )
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="TG Pic Collector.app",
            icon=str(root / "tg_pic_collector" / "assets" / "telegram-app-icon.png"),
            bundle_identifier="io.github.tg-pic-collector",
        )
