# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['bitcoin_node_manager.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['requests'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BitcoinNodeManager',
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
    # Uncomment and set your icon path:
    # icon='app_icon.icns',
)

app = BUNDLE(
    exe,
    name='BitcoinNodeManager.app',
    icon=None,  # Set to 'app_icon.icns' if you have one
    bundle_identifier='com.bitcoin.nodemanager',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'LSMinimumSystemVersion': '10.13.0',
    },
)
