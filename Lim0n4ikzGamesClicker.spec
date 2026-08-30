# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Lim0n4ikzGamesClicker.py'],
    pathex=[],
    binaries=[],
    datas=[('lim0n4ikzgames.ico', '.')],
    hiddenimports=['pynput.keyboard', 'pynput.mouse'],
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
    name='Lim0n4ikzGamesClicker',
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
    icon=['lim0n4ikzgames.ico'],
)
