# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_dir = Path(SPECPATH).resolve()
customtkinter_datas, customtkinter_binaries, customtkinter_hiddenimports = collect_all(
    "customtkinter"
)

datas = [
    (str(project_dir / "cat.png"), "."),
    (str(project_dir / "app_icon.ico"), "."),
    (str(project_dir / "shield.png"), "."),
]
datas += customtkinter_datas

a = Analysis(
    [str(project_dir / "app.py")],
    pathex=[str(project_dir)],
    binaries=customtkinter_binaries,
    datas=datas,
    hiddenimports=customtkinter_hiddenimports,
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
    name="DCS VR UI Configurator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "app_icon.ico"),
)
