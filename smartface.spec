# smartface.spec
# Run from project root: pyinstaller smartface.spec
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

added_files = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('database/schema.sql', 'database'),
]

# Include shape predictor if present (~95 MB)
_dat = os.path.join('models', 'shape_predictor_68_face_landmarks.dat')
if os.path.exists(_dat):
    added_files.append((_dat, 'models'))

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'face_recognition',
        'dlib',
        'flask',
        'waitress',
        'werkzeug',
        'jinja2',
        'click',
        'psutil',
        'flask_wtf',
        'dotenv',
        'cv2',
        'numpy',
        'PIL',
        'reportlab',
        'sqlalchemy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['psycopg2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartFace',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartFace',
)
