# smartface.spec
# Run from project root: pyinstaller smartface.spec
# Output: dist\SmartFace\SmartFace.exe
import os
import face_recognition_models

block_cipher = None

# face_recognition_models data files (required at runtime)
_frm_models_dir = os.path.join(os.path.dirname(face_recognition_models.__file__), 'models')

added_files = [
    ('templates',        'templates'),
    ('static',           'static'),
    ('database',         'database'),
    # face_recognition_models models dir
    (_frm_models_dir, 'face_recognition_models/models'),
    # face_recognition_models package __init__ files
    (os.path.dirname(face_recognition_models.__file__), 'face_recognition_models'),
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
        'face_recognition_models',
        'face_recognition.api',
        'dlib',
        'flask',
        'flask.templating',
        'waitress',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.security',
        'jinja2',
        'jinja2.ext',
        'click',
        'cv2',
        'numpy',
        'PIL',
        'PIL.Image',
        'reportlab',
        'reportlab.pdfgen',
        'reportlab.lib',
        'sqlite3',
        'dotenv',
        'hypothesis',
        'psutil',
        'app',
        'config',
        'database',
        'database.init_db',
        'database.seed',
        'models',
        'models.db',
        'models.user',
        'models.attendance',
        'models.audit',
        'models.schedule',
        'routes',
        'routes.auth',
        'routes.admin',
        'routes.attendance',
        'routes.api',
        'services',
        'services.face_service',
        'services.attendance_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'psycopg2',
        'flask_wtf',
        'sqlalchemy',
        'tensorflow',
        'torch',
        'tkinter',
    ],
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
    upx=False,   # UPX can break native extensions like dlib
    console=False,
    icon='static/img/smartface.ico',
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
    upx=False,
    upx_exclude=[],
    name='SmartFace',
)

# Post-build: Ensure .env is copied into dist/SmartFace/
import shutil
_spec_dir = os.path.dirname(os.path.abspath(SPEC))
_dist_env = os.path.join(_spec_dir, 'dist', 'SmartFace', '.env')
_src_env = os.path.join(_spec_dir, '.env')
if os.path.exists(_src_env):
    shutil.copy2(_src_env, _dist_env)
    print(f'INFO: Copied .env to {_dist_env}')

